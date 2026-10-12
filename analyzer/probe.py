"""Etap 0: zebranie u użytkownika odpowiedzi Vinted potrzebnych do potwierdzenia założeń („⚠” w ARCHITEKTURA.md).

Wszystkie zapytania mają parametry Snipera sprawdzone na żywo (svc-catalogue, newest_first, per_page). Zapisuje
odpowiedzi do data/probe/<czas>/ (dane sprzedawców wycięte) + summary.txt - te pliki wklejasz do rozmowy,
z nich powstają fixtures (analyzer/tests/fixtures_catalog.json).

Sprawdza:
  1. czy katalog podaje `pagination` (total_entries, total_pages, per_page) i jakie pola ma pozycja,
  2. co zwracają strony za limitem (pusta lista / błąd / powtórka),
  3. czy price_from / price_to są włącznie i czy filtr działa po cenie, czy po cenie z ochroną kupującego,
  4. (opcjonalnie --item ID) odpowiedź details/sidebar dla wskazanej oferty, np. usuniętej.
Transfer: kilkanaście zapytań, łącznie zwykle < 1 MB.
"""
import asyncio
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

from sniper.config import CATALOG_ONLY_HEADERS, CATALOG_URL, SIDEBAR_URL

from .catalog import CATALOG_REFERER, build_params, parse_page
from .config import ROOT

log = logging.getLogger("analyzer.probe")

PERSONAL_KEYS = {"user", "login", "seller_id", "user_id", "user_login", "user_info_header", "seller", "profile_url",
                 "photo_url_user", "real_name", "email", "phone", "first_name", "last_name"}
LIMIT_PAGES = (10, 20, 30, 50, 100, 200)


def redact(obj):
    """Rekurencyjnie wycina dane osobowe (RODO) - zostaje sama struktura klucza (i kraj sprzedawcy, jeśli jest)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in PERSONAL_KEYS and v is not None:
                if isinstance(v, dict):
                    from .catalog import COUNTRY_KEYS
                    kept = {c: v[c] for c in COUNTRY_KEYS if v.get(c) is not None}
                    out[k] = {"redacted": True, **kept} if kept else "<redacted>"
                else:
                    out[k] = "<redacted>"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class Probe:
    def __init__(self, session, catalog_id, out_dir=None):
        self.session = session
        self.catalog_id = catalog_id
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.out = Path(out_dir) if out_dir else ROOT / "data" / "probe" / stamp
        self.out.mkdir(parents=True, exist_ok=True)
        self.lines = []

    def note(self, text=""):
        print(text)
        self.lines.append(text)

    def save(self, name, payload):
        (self.out / f"{name}.json").write_text(json.dumps(redact(payload), ensure_ascii=False, indent=1),
                                               encoding="utf-8")

    async def raw_get(self, url, params=None, referer=CATALOG_REFERER, extra_headers=CATALOG_ONLY_HEADERS):
        """GET bez raise_for_status - chcemy widzieć także 4xx (np. strona za limitem, usunięta oferta)."""
        headers = dict(extra_headers or {})
        headers["referer"] = referer
        for attempt in range(2):
            response = await self.session.client.get(url, params=params, headers=headers)
            self.session.traffic.add_http("catalog" if response.url.host == "api.vinted.pl" else "details", response)
            if response.status_code not in (401, 403) or attempt:
                break
            await self.session.refresh()   # brak/wygasła sesja - Playwright przez proxy, jak w Sniperze
        try:
            body = response.json()
        except ValueError:
            body = {"_text": response.text[:2000]}
        return response.status_code, body

    async def catalog(self, name, page=1, per_page=96, price_from=None, price_to=None):
        params = build_params(self.catalog_id, page, per_page, price_from, price_to)
        status, body = await self.raw_get(CATALOG_URL, params)
        self.save(name, {"_status": status, "_params": params, "body": body})
        parsed = parse_page(body if isinstance(body, dict) else {}, self.catalog_id, page, per_page)
        await asyncio.sleep(2.0)
        return status, body, parsed

    async def run(self, item_ids=()):
        self.note(f"Probe katalogu {self.catalog_id} -> {self.out}")

        # 1. Pierwsza strona, bez filtra ceny.
        status, body, first = await self.catalog("01_page1", per_page=96)
        self.note(f"\n[1] Strona 1: HTTP {status}, klucze odpowiedzi: {', '.join(first.raw_keys) or '-'}")
        pagination = body.get("pagination") if isinstance(body, dict) else None
        self.note(f"    pagination: {json.dumps(pagination, ensure_ascii=False)}")
        self.note(f"    pozycji: {len(first.items)}")
        keys = Counter(k for it in (body.get("items") or []) for k in it) if isinstance(body, dict) else Counter()
        self.note(f"    pola pozycji (ile pozycji je ma): {dict(keys)}")
        if not first.items:
            self.note("    Brak pozycji - dalsze testy pominięte (sprawdź sesję/proxy).")
            return self.finish()

        # 2. Strony za limitem.
        self.note("\n[2] Strony za limitem (per_page 96):")
        first_ids = {it.id for it in first.items}
        for page in LIMIT_PAGES:
            status, body, parsed = await self.catalog(f"02_page{page}", page=page)
            repeat = len(first_ids & {it.id for it in parsed.items})
            self.note(f"    page={page}: HTTP {status}, pozycji {len(parsed.items)}, powtórek ze strony 1: {repeat}, "
                      f"pagination: {json.dumps((body or {}).get('pagination') if isinstance(body, dict) else None)}")
            if status >= 400 or not parsed.items:
                break

        # 3. Granice ceny: najczęstsza cena ze strony 1.
        prices = Counter(it.price for it in first.items if it.price is not None)
        price = prices.most_common(1)[0][0]
        self.note(f"\n[3] Granice ceny - cena testowa {price:g} zł:")
        for name, lo, hi in (("03_eq", price, price), ("03_from", price, price + 1), ("03_to", price - 1, price)):
            status, body, parsed = await self.catalog(name, per_page=96, price_from=lo, price_to=hi)
            at_price = sum(1 for it in parsed.items if it.price == price)
            outside = [it for it in parsed.items if it.price is not None and not (lo <= it.price <= hi)]
            total_in = sum(1 for it in parsed.items if it.total_price is not None and lo <= it.total_price <= hi)
            self.note(f"    [{lo:g}; {hi:g}]: HTTP {status}, pozycji {len(parsed.items)}, z ceną dokładnie "
                      f"{price:g}: {at_price}, poza zakresem (po price): {len(outside)}, total_entries "
                      f"{parsed.total_entries}, z total_item_price w zakresie: {total_in}")
        self.note("    Interpretacja: [eq] > 0 = obie granice włącznie; [from] > 0 = price_from włącznie; "
                  "[to] > 0 = price_to włącznie.")

        # 4. Szczegóły wskazanych ofert (np. usuniętej).
        for item_id in item_ids:
            status, body = await self.raw_get(SIDEBAR_URL.format(item_id=item_id),
                                              referer=f"https://www.vinted.pl/items/{item_id}", extra_headers={})
            self.save(f"04_sidebar_{item_id}", {"_status": status, "body": body})
            code = body.get("code") if isinstance(body, dict) else None
            self.note(f"\n[4] sidebar {item_id}: HTTP {status}, code={code}, klucze: "
                      f"{', '.join(body) if isinstance(body, dict) else type(body).__name__}")
            if isinstance(body, dict):
                from sniper.extractor import get_plugin, unwrap_sidebar
                sidebar = unwrap_sidebar(body)
                status_plugin = {k: v for k, v in get_plugin(sidebar, "item_status").items() if k != "seller_id"}
                self.note(f"    item_status: {json.dumps(status_plugin, ensure_ascii=False)}")
                from .resolver import classify
                self.note(f"    rozpoznany stan (resolver.classify): {classify(status, body)}")
            await asyncio.sleep(2.0)
        return self.finish()

    def finish(self):
        traffic = self.session.traffic.total
        used = sum(b["sent"] + b["received"] for b in traffic.values())
        parts = ", ".join(f"{k} {(b['sent'] + b['received']) / 1024:.1f} KB / {b['requests']} zap."
                          for k, b in traffic.items() if b["requests"])
        self.note(f"\nTransfer: {used / 1024:.1f} KB ({parts}). Pliki: {self.out}")
        (self.out / "summary.txt").write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        return self.out


def latest_probe_dir():
    dirs = sorted(p for p in (ROOT / "data" / "probe").glob("*") if p.is_dir())
    return dirs[-1] if dirs else None


def show(probe_dir=None):
    """Krótki wyciąg z zapisanych plików probe (do wklejenia w rozmowie) - bez sieci. Zapis też do show.txt."""
    probe_dir = Path(probe_dir) if probe_dir else latest_probe_dir()
    if not probe_dir or not probe_dir.exists():
        print("Brak folderu data/probe/* - najpierw: python -m analyzer probe")
        return None
    lines = [f"Folder: {probe_dir}"]

    def load(name):
        path = probe_dir / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    page1 = load("01_page1")
    items = ((page1 or {}).get("body") or {}).get("items") or []
    if items:
        sample = dict(items[0])
        if isinstance(sample.get("photos"), list):
            sample["photos"] = sample["photos"][:1] + ([f"... (+{len(items[0]['photos']) - 1})"]
                                                       if len(items[0]["photos"]) > 1 else [])
        lines += ["", "[A] Pierwsza pozycja katalogu (strona 1):", json.dumps(sample, ensure_ascii=False, indent=1)]
        lines += ["", "[B] item_box kolejnych 5 pozycji:"]
        lines += [json.dumps(it.get("item_box"), ensure_ascii=False) for it in items[1:6]]

    data = load("03_from")
    if data:
        params = data.get("_params") or {}
        lo, hi = float(params.get("price_from", 0)), float(params.get("price_to", 0))
        outside = []
        for it in (data.get("body") or {}).get("items") or []:
            price = it.get("price")
            amount = float(price.get("amount")) if isinstance(price, dict) else None
            if amount is not None and not (lo <= amount <= hi):
                outside.append((amount, json.dumps(price, ensure_ascii=False),
                                json.dumps(it.get("total_item_price"), ensure_ascii=False)))
        lines += ["", f"[C] Zapytanie price_from={params.get('price_from')} price_to={params.get('price_to')}: "
                      f"pozycji spoza zakresu {len(outside)}; przykłady (price | total_item_price):"]
        lines += [f"    {p} | {t}" for _, p, t in sorted(set(outside))[:15]]

    for path in sorted(probe_dir.glob("04_sidebar_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        body = data.get("body") or {}
        from sniper.extractor import get_plugin, unwrap_sidebar
        from .details import attributes
        sidebar = unwrap_sidebar(body)
        lines += ["", f"[D] {path.name}: HTTP {data.get('_status')}, pluginy: "
                      f"{[p.get('name') for p in sidebar.get('plugins') or []]}",
                  f"    atrybuty: {json.dumps(attributes(sidebar), ensure_ascii=False)}",
                  f"    opis: {(get_plugin(sidebar, 'description').get('description') or '')[:1500]}"]

    text = "\n".join(lines)
    print(text)
    (probe_dir / "show.txt").write_text(text + "\n", encoding="utf-8")
    return probe_dir
