"""Szczegóły ofert ze STRONY oferty (HTML)

⚠ AKTUALIZACJA 2026-10-24 (pliki `--dump` od użytkownika): strona przychodzi STRUMIENIOWO (Next.js) - panel boczny
na początku to tylko szkielet (`react-loading-skeleton`), prawdziwa treść (status „Sprzedane”, atrybuty, „Dodane”)
dochodzi setki KB później. Natomiast **pełny opis i tytuł są w nagłówku** (`<meta name="description" content="<tytuł> -
<opis>">`, `<title>`) w pierwszych ~17 KB → pobieramy tylko do `</head>` (kilka KB transferu). Stan: strona 200 =
oferta istnieje (sprzedaż potwierdzona parą /services + sidebar), 404 = zdjęta (`blocked`). Bez atrybutów formularza
i „Dodane” (byłoby to ~350 KB na ofertę). Parser panelu (niżej) zostaje - działa, gdy strona ma pełny panel (zapis
z przeglądarki).

Pierwotny opis: - dla tych, których sidebar API już nie poda (sprzedane: 404/104 od
2026-10-24), a szczegółów nie zdążyliśmy pobrać, póki były aktywne.

Strona `www.vinted.pl/items/{id}` waży ~1,9 MB (gzip ~365 KB), ale wyrenderowany panel boczny
(`<aside id="sidebar">`: status „Sprzedane”, cena, atrybuty `data-testid="item-attributes-<kod>"`, opis
`itemprop="description"`, „Dodane”) kończy się po ~320-345 KB → pobieramy strumieniowo i PRZERYWAMY na banerze
wysyłki (`data-testid="item-shipping-banner"`, zaraz po opisie) → ~35 KB transferu na ofertę.
Za banerem jest nazwa sprzedawcy - nie czytamy jej (RODO); zapisujemy tylko wyciągnięte pola, bez surowego HTML.
Struktura sprawdzona na stronach zapisanych przez użytkownika (2026-10-24: sprzedana myszka, aktywny MacBook).
⚠ Nagłówki zapytania o stronę jak przy zwykłym wejściu przeglądarką (nawigacja) - do potwierdzenia na żywo
(`html-details --limit 5`).

Sprzedana według /services (sidebar 404, /services 200), ale strona oferty 404 → stan `blocked` (zdjęta przez Vinted,
np. zablokowane konto oszusta - pierwsze 5 sprawdzonych u użytkownika 2026-10-24: 3 takie, powtarzane „iPhone 16 Pro”
za 519 zł) - nie liczy się do sprzedaży.

`python -m analyzer html-details [--states sold] [--limit N]`
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser

from sniper.session import RateLimited

from . import db
from .details import content_hash, parse_upload_age
from .resolver import _days

log = logging.getLogger("analyzer.html")

PAGE_URL = "https://www.vinted.pl/items/{item_id}"
HEAD_END = b"</head>"         # opis i tytuł są w nagłówku - dalej nie czytamy
MAX_BYTES = 800_000          # bezpiecznik: dalej nie czytamy, nawet jeśli nie znaleziono panelu
# Zapytanie o stronę jak przy wejściu z linku w przeglądarce (dokument, nie API).
PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "referer": "https://www.vinted.pl/",
}
DROP_HEADERS = ("x-next-app", "platform", "locale", "origin", "x-csrf-token", "x-anon-id", "priority")


class _SidebarParser(HTMLParser):
    """Wyciąga z panelu bocznego: status (komórka przed szczegółami), tytuł, cenę, atrybuty, opis."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []                # (tag, rola) - rola: status / title / price / attr_label / attr_value / desc
        self.attr_code = None
        self.result = {"status": None, "title": None, "price": None, "attributes": {}, "description": None}
        self._buf = {}
        self._details_seen = False
        self._skip = 0

    def _role(self, tag, attrs):
        cls = attrs.get("class") or ""
        testid = attrs.get("data-testid") or ""
        prop = attrs.get("itemprop") or ""
        if "box--item-details" in cls or "details-list--main-info" in cls:
            self._details_seen = True
        if not self._details_seen and "web_ui__Cell__body" in cls:
            return "status"
        if testid.startswith("item-attributes-") and not testid.endswith(("-link", "-button", "-faq-link")):
            self.attr_code = testid[len("item-attributes-"):]
        if tag == "h1":
            return "title"
        if testid == "item-price":
            return "price"
        if prop == "description":
            return "desc"
        if self.attr_code and prop == self.attr_code:
            return "attr_value"
        return None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg", "button"):
            self._skip += 1
        if tag in ("br", "img", "input", "meta", "link", "hr"):
            if tag == "br":
                for role in list(self._buf):
                    self._buf[role].append("\n")
            return
        role = self._role(tag, dict(attrs))
        self.stack.append((tag, role))
        if role and role not in self._buf:
            self._buf[role] = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg", "button"):
            self._skip = max(0, self._skip - 1)
        while self.stack:
            open_tag, role = self.stack.pop()
            if role:
                text = re.sub(r"[ \t]+", " ", "".join(self._buf.pop(role, []))).strip()
                self._finish(role, text)
            if open_tag == tag:
                break

    def handle_data(self, data):
        if self._skip:
            return
        for role in self._buf:
            self._buf[role].append(data)

    def _finish(self, role, text):
        r = self.result
        if role == "status" and text and r["status"] is None:
            r["status"] = text
        elif role == "title" and r["title"] is None:
            r["title"] = text
        elif role == "price" and r["price"] is None:
            r["price"] = text
        elif role == "desc" and r["description"] is None:
            r["description"] = re.sub(r"\n{3,}", "\n\n", text).strip()
        elif role == "attr_value" and self.attr_code and self.attr_code not in r["attributes"]:
            r["attributes"][self.attr_code] = text
            self.attr_code = None


def _pln(text):
    match = re.search(r"([\d\s.]+(?:,\d+)?)", (text or "").replace("\xa0", " "))
    if not match:
        return None
    try:
        return float(match.group(1).replace(" ", "").replace(".", "").replace(",", "."))
    except ValueError:
        return None


_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_META_DESC = re.compile(r'<meta name="description" content="(.*?)"\s*/?>', re.S)


def parse_head(html):
    """Nagłówek strony → {title, description, ...} (opis = meta description bez przedrostka „<tytuł> - ”)
    albo None, gdy to nie strona oferty."""
    title_m, desc_m = _TITLE.search(html or ""), _META_DESC.search(html or "")
    if not title_m or not desc_m:
        return None
    title = unescape(title_m.group(1)).strip()
    title = re.sub(r"\s*\|\s*Vinted\s*$", "", title)
    desc = unescape(desc_m.group(1)).strip()
    if desc.startswith(title + " - "):
        desc = desc[len(title) + 3:]
    elif desc == title:
        desc = ""
    return {"status": None, "sold": None, "title": title, "price": None, "attributes": {},
            "description": desc.strip() or None}


def parse_page(html):
    """Pełny panel boczny, jeśli jest (zapis z przeglądarki), inaczej nagłówek (to, co pobiera program)."""
    side = parse_sidebar_html(html)
    if side and (side["title"] or side["description"]):
        return side
    return parse_head(html)


def parse_sidebar_html(html):
    """Panel boczny strony oferty → {status, sold, title, price, attributes{kod: wartość}, description}
    albo None, gdy na stronie nie ma panelu (np. „Page not found”)."""
    start = html.find('<aside id="sidebar"')
    if start < 0:
        return None
    parser = _SidebarParser()
    parser.feed(html[start:])
    r = parser.result
    r["price"] = _pln(r["price"])
    status = (r["status"] or "").strip()
    r["status"] = status or None
    r["sold"] = status.lower().startswith("sprzedan")
    if r["description"]:
        r["description"] = unescape(r["description"])
    return r


async def fetch_sidebar_html(session, item_id):
    """(status HTTP, HTML do końca panelu bocznego). Czyta strumieniowo i przerywa po opisie - reszty strony nie
    pobiera. 401/403 → odświeżenie sesji, 429 → RateLimited."""
    url = PAGE_URL.format(item_id=item_id)
    for attempt in range(2):
        request = session.client.build_request("GET", url, headers=PAGE_HEADERS)
        for name in DROP_HEADERS:
            request.headers.pop(name, None)
        response = await session.client.send(request, stream=True, follow_redirects=True)
        try:
            if response.status_code in (401, 403) and attempt == 0:
                await response.aclose()
                session.traffic.add_http("details", response)
                await session.refresh()
                continue
            if response.status_code == 429:
                raise RateLimited(url)
            buf = bytearray()
            async for chunk in response.aiter_bytes():
                buf += chunk
                end = buf.find(HEAD_END)
                if end >= 0:
                    del buf[end + len(HEAD_END):]     # reszty strony (nazwa sprzedawcy itd.) nie zwracamy
                    break
                if len(buf) > MAX_BYTES:
                    break
            return response.status_code, buf.decode("utf-8", errors="replace")
        finally:
            await response.aclose()
            session.traffic.add_http("details", response)
    return response.status_code, ""


def store_html_details(conn, row, parsed, fetched_at):
    """Zapis szczegółów ze strony do tabeli details (source='html'); dla sprzedanych przelicza czas sprzedaży
    z „Dodane” (wcześniej był liczony od pierwszego widzenia)."""
    attrs = dict(parsed["attributes"])
    age = parse_upload_age(attrs.get("upload_date"))
    created = (datetime.fromisoformat(fetched_at) - age).isoformat(timespec="seconds") if age is not None else None
    conn.execute(
        """INSERT OR REPLACE INTO details (listing_id, fetched_at, description, attributes_json, upload_age,
               created_est, business, seller_currency, photo_count, is_localized, source)
           VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, 'html')""",
        (row["id"], fetched_at, parsed["description"], json.dumps(attrs, ensure_ascii=False),
         attrs.get("upload_date"), created, row["seller_currency"]))
    conn.execute("UPDATE listings SET details_at=?, content_hash=?, created_at=COALESCE(created_at, ?) WHERE id=?",
                 (fetched_at, content_hash(parsed["title"] or row["title"], parsed["description"]), created, row["id"]))
    if row["state"] == "sold":
        start = conn.execute("SELECT created_at, first_seen FROM listings WHERE id=?", (row["id"],)).fetchone()
        conn.execute("UPDATE listings SET days_to_sell=? WHERE id=?",
                     (_days(start["created_at"] or start["first_seen"], row["last_seen"]), row["id"]))
    db.put_raw(conn, row["id"], "html_sidebar", {"status": parsed["status"], "price": parsed["price"],
                                                 "title": parsed["title"]}, fetched_at)


def candidates(conn, states=("sold",), limit=None, random_order=False):
    marks = ",".join("?" * len(states))
    # + oferty z pustymi szczegółami ze strony (pierwsza wersja czytała szkielet panelu - 2026-10-24)
    sql = (f"SELECT * FROM listings WHERE (details_at IS NULL OR id IN (SELECT listing_id FROM details "
           f"WHERE source='html' AND description IS NULL)) AND state IN ({marks}) "
           "AND category NOT IN ('ignored', 'unknown') ORDER BY " + ("RANDOM()" if random_order else "last_seen DESC"))
    params = list(states)
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


async def fetch_html_details(cfg, session, conn, states=("sold",), limit=None, sleep=asyncio.sleep, progress=None,
                             random_order=False):
    """Pobiera szczegóły ze strony HTML dla ofert bez szczegółów w podanych stanach. Zwraca {wynik: liczba}."""
    import time

    rows = candidates(conn, states, limit, random_order)
    log.info("[HTML] Ofert bez szczegółów (stany: %s): %d.", ", ".join(states), len(rows))
    counts, started = {}, time.monotonic()
    state = {"total": len(rows), "counts": counts, "n": 0, "eta": None}
    for n, row in enumerate(rows):
        if n:
            await sleep(cfg.pick_delay())
        state.update(n=n, row=row)
        if progress:
            progress(dict(state, stage="check"))
        try:
            status, html = await fetch_sidebar_html(session, row["id"])
        except RateLimited:
            log.warning("[HTML] 429 - czekam 10 min.")
            await sleep(600)
            continue
        except Exception as exc:
            log.warning("[HTML] %s: błąd %r", row["id"], exc)
            counts["błąd"] = counts.get("błąd", 0) + 1
            continue
        parsed = parse_page(html) if status == 200 else None
        if parsed is None and status == 404 and row["state"] == "sold":
            # /services odpowiadał (stąd „sold”), ale strony nie ma: oferta zdjęta przez Vinted (np. konto
            # oszusta zablokowane) - to NIE jest sprzedaż.
            with conn:
                conn.execute("UPDATE listings SET state='blocked', state_at=?, sold_price=NULL, days_to_sell=NULL "
                             "WHERE id=?", (db.utcnow(), row["id"]))
                db.put_raw(conn, row["id"], "html_sidebar", {"http": status, "blocked": True}, db.utcnow())
            key = "zablokowana (strona 404)"
        elif parsed is None:
            key = f"brak strony (HTTP {status})"
            if row["state"] == "deleted" and status == 404:
                key = "potwierdzona usunięta (strona 404)"
        else:
            with conn:
                store_html_details(conn, row, parsed, db.utcnow())
            key = "ok" + (" (bez napisu Sprzedane!)" if parsed["sold"] is False and row["state"] == "sold" else "")
            if row["state"] == "deleted":
                key = "STRONA ISTNIEJE mimo 'deleted'"
                log.info("[HTML] %s - 'deleted', a strona istnieje: https://www.vinted.pl/items/%s  %s",
                         row["id"], row["id"], (row["title"] or "")[:50])
        counts[key] = counts.get(key, 0) + 1
        state.update(n=n + 1, eta=(time.monotonic() - started) / (n + 1) * (len(rows) - n - 1))
        if progress:
            progress(dict(state, stage="done", key=key, reason=""))
        elif (n + 1) % 50 == 0:
            log.info("[HTML] %d/%d: %s", n + 1, len(rows), ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    log.info("[HTML] Wynik: %s", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nic do zrobienia")
    return counts
