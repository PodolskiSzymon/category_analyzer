"""Etap 2: oferty, które zniknęły z katalogu (gone_pending), sprawdzamy JEDNYM zapytaniem details/sidebar.

Odpowiedzi potwierdzone u użytkownika (2026-10-11):
  * sprzedana  - HTTP 200, code 0, plugin item_status: is_closed=true, item_closing_action="sold"
                 (karta pamięci 9238023547, laptop 10295873538; fixture sniper/tests/fixtures.json sidebar_sold),
  * usunięta   - HTTP 404, code 104 (oferta 10327664119 usunięta przez użytkownika; strona: „Page not found”),
  * aktywna    - HTTP 200, item_closing_action=null (sidebar_active).
**Zmiana Vinted (ustalenia użytkownika 2026-10-24):** sidebar SPRZEDANEJ oferty zwraca teraz 404/104 - tak samo jak
usuniętej. Rozróżnia je `/api/v2/items/{id}/services` (z przeglądarki użytkownika): odpowiada (200, ceny i opłaty) dla
aktywnej i sprzedanej, a dla usuniętej 404/104. Dlatego `resolve_item`:
  1. /services 404/104                      → deleted (1 zapytanie, ~1 KB),
  2. /services 200 → sidebar 404/104        → sold (oferta istnieje, ale sidebar jej już nie pokazuje),
  3. /services 200 → sidebar 200            → jak dawniej: sold (item_closing_action) / reserved / hidden / unlisted,
     a gdy oferta jest jeszcze w katalogu (missed_runs = 0) → active.
/services daje też cenę w zł i w walucie sprzedawcy w chwili sprawdzenia (cena sprzedaży bez kursowego dryfu).

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
# Adres z ruchu przeglądarki użytkownika (2026-10-24, strona sprzedanej oferty).
SERVICES_URL = "https://www.vinted.pl/api/v2/items/{item_id}/services"


def is_not_found(status_code, body):
    return status_code == 404 and isinstance(body, dict) and body.get("code") == DELETED_CODE


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


async def _get(session, url, referer):
    """GET bez raise_for_status (404 to tu normalna odpowiedź). 401/403 → odświeżenie sesji, 429 → RateLimited."""
    headers = {"referer": referer}
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


async def fetch_sidebar(session, item_id):
    return await _get(session, SIDEBAR_URL.format(item_id=item_id), f"https://www.vinted.pl/items/{item_id}")


async def fetch_services(session, item_id):
    return await _get(session, SERVICES_URL.format(item_id=item_id), f"https://www.vinted.pl/items/{item_id}")


class Resolution:
    """Wynik sprawdzenia jednej oferty: stan (None = nie wiadomo), powód i surowe odpowiedzi."""

    def __init__(self, state, reason, sidebar=None, services=None):
        self.state, self.reason = state, reason
        self.sidebar = sidebar        # (status, body) albo None, gdy nie pytaliśmy
        self.services = services


def judge(sidebar, services):
    """Stan z pary odpowiedzi (sidebar, /services) - każda (status, body) albo None."""
    if services is not None:
        status, body = services
        if is_not_found(status, body):
            return "deleted", "services 404/104"
        if status != 200:
            return None, f"services HTTP {status}"
    if sidebar is None:
        return None, "brak odpowiedzi sidebar"
    status, body = sidebar
    if is_not_found(status, body):
        if services is None:
            return None, "sidebar 404/104 - bez /services nie wiadomo: sprzedana czy usunięta"
        return "sold", "sidebar 404/104 + services 200"
    return classify(status, body)


async def resolve_item(session, item_id, sidebar=None):
    """Najpierw /services (usunięta = 1 zapytanie), potem sidebar - chyba że sidebar już mamy (details)."""
    services = await fetch_services(session, item_id)
    if sidebar is None and not is_not_found(*services) and services[0] == 200:
        sidebar = await fetch_sidebar(session, item_id)
    state, reason = judge(sidebar, services)
    return Resolution(state, reason, sidebar, services)


def _days(start, end):
    try:
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    return round((b - a).total_seconds() / 86400, 2)


def _money(obj):
    if isinstance(obj, dict):
        return to_float(obj.get("amount")), obj.get("currency_code")
    return None, None


def apply_result(conn, row, state, status_code, body, now, services=None):
    """Zapisuje wynik sprawdzenia. status_code/body - odpowiedź sidebar (albo None), services - (status, body)."""
    if status_code is not None:
        db.put_raw(conn, row["id"], "resolve", {"_status": status_code, "body": redact(body)}, now)
    seller_price = seller_currency = services_price = None
    if services is not None:
        s_status, s_body = services
        db.put_raw(conn, row["id"], "services", {"_status": s_status, "body": s_body}, now)
        if s_status == 200 and isinstance(s_body, dict):
            services_price, _ = _money(s_body.get("original_asking_amount"))
            seller_price, seller_currency = _money(s_body.get("seller_original_asking_amount"))
        conn.execute("UPDATE listings SET services_at=?, seller_price=COALESCE(?, seller_price), "
                     "seller_currency=COALESCE(?, seller_currency) WHERE id=?",
                     (now, seller_price, seller_currency, row["id"]))
    if state is None:
        return
    if status_code == 200 and row["details_at"] is None and isinstance(body, dict):
        from .details import store_details   # sprzedana bez szczegółów - opis jest w tej samej odpowiedzi
        store_details(conn, row["id"], body, now)
    if state == "unlisted" and row["missed_runs"] == 0:
        state = "active"                     # wciąż w katalogu (ostatnie przejście ją widziało)
    if state == "sold":
        price = services_price
        if price is None and status_code == 200:
            price = to_float(unwrap_sidebar(body).get("price"))
        if price is None:
            price = row["price_now"]
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


def _below_min(cfg, row, res):
    """Aktywna, ale niewidoczna w katalogu, bo potaniała poniżej progu kategorii → below_min."""
    state, reason = res.state, res.reason
    low = cfg.category_min(row["category"]) if row["category"] else cfg.price_min_for(row["catalog_id"])
    if state == "unlisted" and low and res.sidebar and res.sidebar[0] == 200:
        price = to_float(unwrap_sidebar(res.sidebar[1]).get("price"))
        if price is not None and price < low:
            return "below_min", f"cena {price:g} zł < {low:g} zł"
    return state, reason


async def _pause(seconds, label, sleep, progress, state):
    """Przerwa; z paskiem postępu odliczana co sekundę (widać, że program żyje)."""
    if progress is None or seconds < 3:
        await sleep(seconds)
        return
    left = seconds
    while left > 0:
        progress(dict(state, stage="pause", label=label or "odstęp", left=left))
        step = min(1.0, left)
        await sleep(step)
        left -= step


RATE_LIMIT_WAITS = (300, 900, 1800, 3600)    # 429 w recheck: czekamy 5, 15, 30, potem co 60 min


async def _run(cfg, session, conn, rows, tag, sleep=asyncio.sleep, verbose=True, pacer=None, progress=None,
               wait_on_429=False):
    """Sprawdza oferty po kolei (resolve_item) i zapisuje wyniki. Zwraca {stan: liczba}.
    pacer - HumanPacer („ludzkie” przerwy) zamiast cfg.pick_delay(); progress(dict) - pasek postępu (recheck);
    wait_on_429 - przy „za dużo zapytań” czekaj (RATE_LIMIT_WAITS) i ponów tę samą ofertę zamiast przerywać."""
    import time

    counts = {}
    started = time.monotonic()
    total = len(rows)
    state = {"total": total, "counts": counts, "n": 0, "eta": None}
    for n, row in enumerate(rows):
        if n:
            delay, label = pacer.next() if pacer else (cfg.pick_delay(), None)
            await _pause(delay, label, sleep, progress, state)
        state.update(n=n, row=row)
        if progress:
            progress(dict(state, stage="check"))
        res, limited, stop = None, 0, False
        while res is None:
            try:
                res = await resolve_item(session, row["id"])
            except RateLimited:
                if not wait_on_429:
                    stop = True
                    break
                wait = RATE_LIMIT_WAITS[min(limited, len(RATE_LIMIT_WAITS) - 1)]
                limited += 1
                log.warning("[%s] 429 (za dużo zapytań) - czekam %d min i ponawiam (%d. raz z rzędu).", tag,
                            wait // 60, limited)
                await _pause(wait, "429 - czekam", sleep, progress, state)
            except Exception as exc:  # sieć / proxy - ta oferta poczeka do następnego razu
                log.warning("[%s] %s: błąd %r", tag, row["id"], exc)
                counts["błąd"] = counts.get("błąd", 0) + 1
                break
        if stop:
            log.warning("[%s] 429 - przerywam, reszta przy następnym uruchomieniu.", tag)
            break
        if res is None:
            continue
        result, reason = _below_min(cfg, row, res)
        status_code, body = res.sidebar if res.sidebar else (None, None)
        with conn:
            apply_result(conn, row, result, status_code, body, db.utcnow(), res.services)
        if result == "unlisted" and row["missed_runs"] == 0:
            result = "active"
        key = result or "nieznany"
        counts[key] = counts.get(key, 0) + 1
        per = (time.monotonic() - started) / (n + 1)
        state.update(n=n + 1, eta=per * (total - n - 1))
        if progress:
            progress(dict(state, stage="done", key=key, reason=reason))
        if verbose:
            log.info("[%s] %s %s -> %s (%s)", tag, row["id"], (row["title"] or "")[:40], key, reason)
        elif (n + 1) % 50 == 0 or n + 1 == total:
            log.info("[%s] %d/%d (zostało ~%.1f h): %s", tag, n + 1, total, state["eta"] / 3600,
                      ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    log.info("[%s] Wynik: %s", tag, ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nic do zrobienia")
    return counts


async def resolve(cfg, session, conn, limit=None, sleep=asyncio.sleep):
    rows = candidates(conn, cfg.recheck_days, limit)
    log.info("[RESOLVE] Do sprawdzenia: %d ofert.", len(rows))
    return await _run(cfg, session, conn, rows, "RESOLVE", sleep)


RECHECK_STATES = ("deleted",)


def recheck_candidates(conn, states=RECHECK_STATES, limit=None, again=False):
    """Oferty w podanych stanach, jeszcze niesprawdzone przez /services (again=True - wszystkie), najświeższe
    zniknięcia najpierw (ich strony Vinted na pewno jeszcze ma)."""
    marks = ",".join("?" * len(states))
    sql = (f"SELECT * FROM listings WHERE state IN ({marks})" + ("" if again else " AND services_at IS NULL")
           + " ORDER BY last_seen DESC")
    params = list(states)
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


async def recheck(cfg, session, conn, states=RECHECK_STATES, limit=None, again=False, sleep=asyncio.sleep,
                  pacer=None, progress=None, wait_on_429=True):
    """Jednorazowa naprawa (2026-10-24): oferty oznaczone dawną metodą (`deleted` = sprzedane + usunięte + aktywne)
    sprawdzane od nowa: /services → (sidebar) → deleted / sold / active / unlisted / hidden / reserved.
    Można przerwać i wznowić - pomija już sprawdzone (services_at)."""
    rows = recheck_candidates(conn, states, limit, again)
    log.info("[RECHECK] Do sprawdzenia: %d ofert (stany: %s).", len(rows), ", ".join(states))
    return await _run(cfg, session, conn, rows, "RECHECK", sleep, verbose=False, pacer=pacer, progress=progress,
                      wait_on_429=wait_on_429)
