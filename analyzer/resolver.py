"""Etap 2: oferty, które zniknęły z katalogu (gone_pending), sprawdzamy JEDNYM zapytaniem details/sidebar.

Odpowiedzi potwierdzone u użytkownika (2026-10-11):
  * sprzedana  - HTTP 200, code 0, plugin item_status: is_closed=true, item_closing_action="sold"
                 (karta pamięci 9238023547, laptop 10295873538; fixture sniper/tests/fixtures.json sidebar_sold),
  * usunięta   - HTTP 404, code 104 (oferta 10327664119 usunięta przez użytkownika; strona: „Page not found”),
  * aktywna    - HTTP 200, item_closing_action=null (sidebar_active).
Aktywna, a niewidoczna w katalogu → stan `unlisted` (sprawdzamy ponownie po ANALYZER_RECHECK_DAYS), chyba że jej
cena spadła poniżej ANALYZER_PRICE_MIN → `below_min` (poza zakresem, nie śledzimy).

Cena sprzedaży: cena z sidebara sprzedanej oferty (stan w chwili sprzedaży, w zł - Vinted przelicza na walutę
kupującego), a gdy jej brak - ostatnia cena z katalogu. To cena WYSTAWIENIA - górna granica ceny transakcji.
Czas sprzedaży: od COALESCE(created_at, first_seen) do last_seen (ostatnie widzenie w katalogu; sprzedaż nastąpiła
między last_seen a następnym przejściem). Dla ofert z pierwszego przejścia first_seen ≠ data wystawienia.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sniper.config import SIDEBAR_URL
from sniper.extractor import get_plugin, unwrap_sidebar
from sniper.session import RateLimited

from . import db
from .catalog import to_float
from .probe import redact

log = logging.getLogger("analyzer.resolver")

DELETED_CODE = 104


def classify(status_code, body):
    """(stan, powód) z odpowiedzi details/sidebar. stan None = nie wiadomo (zostaje gone_pending)."""
    code = body.get("code") if isinstance(body, dict) else None
    if status_code == 404:
        if code == DELETED_CODE:
            return "deleted", "404/104"
        return None, f"404 code={code}"
    if status_code != 200 or not isinstance(body, dict):
        return None, f"HTTP {status_code}"
    sidebar = unwrap_sidebar(body)
    status = get_plugin(sidebar, "item_status")
    action = status.get("item_closing_action")
    if action == "sold":
        return "sold", "item_closing_action=sold"
    if action is not None:
        return "closed", f"item_closing_action={action}"
    if status.get("is_closed") or sidebar.get("is_closed"):
        return "closed", "is_closed"
    if status.get("is_reserved") or sidebar.get("is_reserved"):
        return "reserved", "is_reserved"
    if status.get("is_hidden") or sidebar.get("is_hidden"):
        return "hidden", "is_hidden"
    if status.get("is_draft"):
        return "hidden", "is_draft"
    return "unlisted", "aktywna, brak w katalogu"


async def fetch_sidebar(session, item_id):
    """GET details/sidebar bez raise_for_status (404 to tu normalna odpowiedź). 401/403 → odświeżenie sesji."""
    url = SIDEBAR_URL.format(item_id=item_id)
    headers = {"referer": f"https://www.vinted.pl/items/{item_id}"}
    for attempt in range(2):
        response = await session.client.get(url, headers=headers)
        session.traffic.add_http("details", response)
        if response.status_code in (401, 403) and attempt == 0:
            await session.refresh()
            continue
        if response.status_code == 429:
            raise RateLimited(url)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"_text": response.text[:500]}
    return response.status_code, {}


def _days(start, end):
    try:
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    return round((b - a).total_seconds() / 86400, 2)


def apply_result(conn, row, state, status_code, body, now):
    db.put_raw(conn, row["id"], "resolve", {"_status": status_code, "body": redact(body)}, now)
    if state is None:
        return
    if status_code == 200 and row["details_at"] is None and isinstance(body, dict):
        from .details import store_details   # sprzedana bez szczegółów - opis jest w tej samej odpowiedzi
        store_details(conn, row["id"], body, now)
    if state == "sold":
        sidebar = unwrap_sidebar(body)
        price = to_float(sidebar.get("price"))
        if price is None:
            last = db.last_observation(conn, row["id"])
            price = last["price"] if last else None
        start = row["created_at"] or row["first_seen"]
        conn.execute("UPDATE listings SET state='sold', state_at=?, sold_price=?, days_to_sell=? WHERE id=?",
                     (now, price, _days(start, row["last_seen"]), row["id"]))
    else:
        conn.execute("UPDATE listings SET state=?, state_at=? WHERE id=?", (state, now, row["id"]))


def candidates(conn, recheck_days, limit=None):
    """gone_pending + (unlisted / reserved / hidden, których dalej nie ma w katalogu, sprawdzane co recheck_days)."""
    before = (datetime.now(timezone.utc) - timedelta(days=recheck_days)).isoformat(timespec="milliseconds")
    sql = """SELECT * FROM listings WHERE state='gone_pending'
             OR (state IN ('unlisted', 'reserved', 'hidden') AND missed_runs > 0 AND state_at < ?)
             ORDER BY state='gone_pending' DESC, last_seen"""
    rows = conn.execute(sql + (" LIMIT ?" if limit else ""), (before, limit) if limit else (before,)).fetchall()
    return rows


async def resolve(cfg, session, conn, limit=None, sleep=asyncio.sleep):
    rows = candidates(conn, cfg.recheck_days, limit)
    counts = {}
    log.info("[RESOLVE] Do sprawdzenia: %d ofert.", len(rows))
    for n, row in enumerate(rows):
        if n:
            await sleep(cfg.pick_delay())
        try:
            status_code, body = await fetch_sidebar(session, row["id"])
        except RateLimited:
            log.warning("[RESOLVE] 429 - przerywam, reszta przy następnym uruchomieniu.")
            break
        except Exception as exc:  # sieć / proxy - ta oferta poczeka do następnego razu
            log.warning("[RESOLVE] %s: błąd %r", row["id"], exc)
            counts["błąd"] = counts.get("błąd", 0) + 1
            continue
        state, reason = classify(status_code, body)
        if state == "unlisted" and cfg.price_min:
            price = to_float(unwrap_sidebar(body).get("price"))
            if price is not None and price < cfg.price_min:   # zniknęła z naszego zakresu, bo potaniała
                state, reason = "below_min", f"cena {price:g} zł < {cfg.price_min:g} zł"
        with conn:
            apply_result(conn, row, state, status_code, body, db.utcnow())
        key = state or "nieznany"
        counts[key] = counts.get(key, 0) + 1
        log.info("[RESOLVE] %s %s -> %s (%s)", row["id"], (row["title"] or "")[:40], key, reason)
    log.info("[RESOLVE] Wynik: %s", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nic do zrobienia")
    return counts
