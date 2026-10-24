"""Szczegóły oferty (details/sidebar) - RAZ na ofertę: opis, atrybuty, „Dodane”, firma, waluta sprzedawcy.

Odpowiedź ~6–10 KB (probe 2026-10-11). Kolejność: najnowsze ID najpierw (oferty wystawione po starcie
analizatora mają wiarygodny czas sprzedaży). Jeśli w międzyczasie oferta została sprzedana / usunięta - stan
ustawia resolver.apply_result (ta sama odpowiedź, bez dodatkowego zapytania).

Atrybut `upload_date` („Dodane”: „3 min.”, „2 dni”, „3 mies.”) → szacowana data wystawienia `created_at`
(dokładność = jednostka; ⚠ niepotwierdzone, czy podbicie oferty nie zmienia tej daty).
"""
import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta

from sniper.extractor import get_plugin, unwrap_sidebar
from sniper.session import RateLimited

from . import db
from .probe import redact
from .resolver import apply_result, fetch_services, fetch_sidebar, is_not_found, judge

log = logging.getLogger("analyzer.details")

_AGE_UNITS = (  # (wzorzec jednostki, długość)
    (r"min", timedelta(minutes=1)),
    (r"godz|h\b", timedelta(hours=1)),
    (r"dzie|dni", timedelta(days=1)),
    (r"tydz|tyg", timedelta(weeks=1)),
    (r"mies", timedelta(days=30)),
    (r"rok|lat", timedelta(days=365)),
)


def parse_upload_age(text):
    """„3 mies.” -> timedelta(90 dni); „przed chwilą” -> 0; nierozpoznane -> None."""
    text = (text or "").strip().lower()
    if not text:
        return None
    if "chwil" in text or "teraz" in text:
        return timedelta(0)
    match = re.match(r"(\d+)\s*(.*)", text)
    number, unit = (int(match.group(1)), match.group(2)) if match else (1, text)   # „dzień”, „rok” bez liczby
    for pattern, length in _AGE_UNITS:
        if re.match(pattern, unit):
            return number * length
    return None


def attributes(sidebar):
    """{code: value} z pluginu attributes (brand, status, color, upload_date, ... - dla laptopów może być więcej)."""
    found = {}
    for attr in get_plugin(sidebar, "attributes").get("attributes") or []:
        code, data = attr.get("code"), attr.get("data") or {}
        if code:
            found[code] = data.get("value")
    return found


def content_hash(title, description):
    return hashlib.sha1(f"{title or ''}\n{description or ''}".encode("utf-8")).hexdigest()


def store_details(conn, listing_id, body, fetched_at):
    """Zapis szczegółów z odpowiedzi sidebar (200). Zwraca szacowane created_at albo None."""
    sidebar = unwrap_sidebar(body)
    desc_plugin = get_plugin(sidebar, "description")
    description = desc_plugin.get("description")
    attrs = attributes(sidebar)
    age = parse_upload_age(attrs.get("upload_date"))
    created = (datetime.fromisoformat(fetched_at) - age).isoformat(timespec="seconds") if age is not None else None
    conversion = sidebar.get("conversion") if isinstance(sidebar.get("conversion"), dict) else {}
    conn.execute(
        """INSERT OR REPLACE INTO details (listing_id, fetched_at, description, attributes_json, upload_age,
               created_est, business, seller_currency, photo_count, is_localized, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sidebar')""",
        (listing_id, fetched_at, description, json.dumps(attrs, ensure_ascii=False), attrs.get("upload_date"),
         created, None if sidebar.get("business") is None else int(bool(sidebar.get("business"))),
         conversion.get("seller_currency") or sidebar.get("currency"), len(sidebar.get("photos") or []),
         None if desc_plugin.get("is_localized") is None else int(bool(desc_plugin.get("is_localized")))))
    conn.execute("UPDATE listings SET details_at=?, content_hash=?, created_at=COALESCE(created_at, ?) WHERE id=?",
                 (fetched_at, content_hash(sidebar.get("title"), description), created, listing_id))
    db.put_raw(conn, listing_id, "sidebar", redact(body), fetched_at)
    return created


def candidates(conn, limit=None, categories=None):
    """Oferty bez szczegółów; categories - tylko NASZE kategorie z listy (None = wszystkie śledzone)."""
    sql = "SELECT * FROM listings WHERE details_at IS NULL AND state IN ('active', 'reserved', 'unlisted')"
    params = []
    if categories is not None:
        sql += f" AND category IN ({','.join('?' * len(categories)) or 'NULL'})"
        params.extend(categories)
    sql += " ORDER BY id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


async def fetch_details(cfg, session, conn, limit=None, deadline=None, sleep=asyncio.sleep, clock=None):
    """Pobiera szczegóły ofert bez nich. deadline (datetime UTC) - przerwij po tym czasie (tryb watch)."""
    clock = clock or (lambda: datetime.now(deadline.tzinfo) if deadline else None)
    catalogs = getattr(cfg, "details_catalogs", None)
    rows = candidates(conn, limit, catalogs)
    log.info("[DETAILS] Ofert bez szczegółów: %d%s%s.", len(rows), f" (limit {limit})" if limit else "",
             "" if catalogs is None else f" w kategoriach {', '.join(map(str, catalogs))} (pozostałe: tylko przy "
                                         "zniknięciu oferty, ANALYZER_DETAILS_CATEGORIES)")
    counts = {}
    for n, row in enumerate(rows):
        if deadline and clock() >= deadline:
            log.info("[DETAILS] Koniec czasu na szczegóły - reszta w następnym cyklu.")
            break
        if n:
            await sleep(cfg.pick_details_delay())
        try:
            status_code, body = await fetch_sidebar(session, row["id"])
        except RateLimited:
            log.warning("[DETAILS] 429 - przerwa 5 min.")
            await sleep(300)
            continue
        except Exception as exc:
            log.warning("[DETAILS] %s: błąd %r", row["id"], exc)
            counts["błąd"] = counts.get("błąd", 0) + 1
            continue
        services = None
        if is_not_found(status_code, body):
            # Od 2026-10-24 sidebar sprzedanej = 404/104, jak usuniętej - rozstrzyga /services (~1 KB).
            try:
                services = await fetch_services(session, row["id"])
            except Exception as exc:
                log.warning("[DETAILS] %s: /services błąd %r", row["id"], exc)
        state, _ = judge((status_code, body), services)
        now = db.utcnow()
        with conn:
            if state in ("sold", "deleted", "closed", "hidden", "reserved"):
                apply_result(conn, row, state, status_code, body, now, services)   # zapisuje też szczegóły (200)
                key = state
            elif status_code == 200 and isinstance(body, dict) and body.get("code", 0) == 0:
                store_details(conn, row["id"], body, now)
                key = "ok"
            else:
                key = f"HTTP {status_code}"
        counts[key] = counts.get(key, 0) + 1
        if (n + 1) % 200 == 0:
            log.info("[DETAILS] %d/%d: %s", n + 1, len(rows), ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    log.info("[DETAILS] Wynik: %s", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nic do zrobienia")
    return counts
