"""Sprawdzenie pojedynczych ofert: `python -m analyzer check <link lub ID> [...]`.

Dla każdej oferty:
  1. co wie baza: stan, pierwsze / ostatnie widzenie w katalogu, cena, ostatnia zapisana pozycja katalogu
     (pola, w których może być znacznik sprzedaży - item_box, badge, status…),
  2. sprawdzenie jak w resolverze (resolver.resolve_item): /services, a gdy odpowie - sidebar → jak program by ją
     sklasyfikował (sold / deleted / closed / reserved / hidden / unlisted) i na podstawie czego.
Bazy NIE zmienia (tylko odczyt) - do sprawdzania, czy rozpoznawanie sprzedaży działa.
"""
import json
import re

from . import db
from .resolve_diag import fingerprint
from .resolver import resolve_item

_ID = re.compile(r"(?:items/)?(\d{6,})")
SOLD_HINTS = re.compile(r"sold|sprzed|closed|zamkni|status|badge|reserved|rezerw", re.I)


def parse_id(text):
    match = _ID.search(str(text))
    return int(match.group(1)) if match else None


def _hints(obj, path=""):
    """Pola surowej pozycji katalogu, których nazwa albo wartość wygląda na znacznik stanu oferty."""
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{path}.{key}" if path else key
            if isinstance(value, (dict, list)):
                found += _hints(value, here)
            elif SOLD_HINTS.search(key) or (isinstance(value, str) and SOLD_HINTS.search(value)):
                found.append(f"{here} = {value!r}"[:200])
    elif isinstance(obj, list):
        for n, value in enumerate(obj):
            found += _hints(value, f"{path}[{n}]")
    return found


def db_lines(conn, item_id):
    row = conn.execute("SELECT id, title, category, state, state_at, first_seen, last_seen, missed_runs, price_now, "
                       "sold_price, details_at FROM listings WHERE id=?", (item_id,)).fetchone()
    if row is None:
        return ["  baza: BRAK tej oferty (nie trafiła do żadnej zbieranej kategorii / progu ceny)"]
    lines = [f"  baza: stan {row['state']} (od {row['state_at']}), kategoria {row['category']}, cena {row['price_now']}",
             f"        w katalogu: pierwszy raz {row['first_seen']}, ostatni raz {row['last_seen']}, "
             f"pominięte przejścia {row['missed_runs']}",
             f"        tytuł: {row['title']}"]
    catalog = db.get_raw(conn, item_id, "catalog")
    if catalog:
        at, item = catalog[-1]
        lines.append(f"  ostatnia pozycja katalogu ({at}):")
        box = item.get("item_box") if isinstance(item, dict) else None
        if box:
            lines.append(f"        item_box: {json.dumps(box, ensure_ascii=False)[:600]}")
        for hint in _hints(item):
            lines.append(f"        {hint}")
    return lines


async def check(session, conn, items):
    out = []
    for text in items:
        item_id = parse_id(text)
        if item_id is None:
            out.append(f"\n{text}: to nie jest link ani ID oferty")
            continue
        out.append(f"\n=== https://www.vinted.pl/items/{item_id}")
        if conn is not None:
            out += db_lines(conn, item_id)
        res = await resolve_item(session, item_id)
        out.append(f"  Vinted teraz: program uznałby: {(res.state or 'NIE WIADOMO').upper()} ({res.reason})")
        s_status, s_body = res.services
        if s_status == 200 and isinstance(s_body, dict):
            asking = s_body.get("original_asking_amount") or {}
            seller = s_body.get("seller_original_asking_amount") or {}
            out.append(f"        /services: HTTP 200, cena {asking.get('amount')} {asking.get('currency_code')}"
                       f" (sprzedawca: {seller.get('amount')} {seller.get('currency_code')})")
        else:
            out.append(f"        /services: HTTP {s_status} {json.dumps(s_body, ensure_ascii=False)[:120]}")
        if res.sidebar is not None:
            fp = fingerprint({"_status": res.sidebar[0], "body": res.sidebar[1]})
            out.append("        sidebar: " + ", ".join(f"{k}={v}" for k, v in fp.items() if k != "plugins"))
    return out
