"""Atrapa katalogu Vinted: syntetyczny „rynek” z limitem wyników, sortowaniem newest_first i filtrem cen."""
import random

from analyzer.catalog import parse_page, widen


class FakeMarket:
    def __init__(self, prices, limit=960, with_pagination=True, upper_inclusive=True, fail=None):
        # id -> cena; wyższe id = nowsza oferta
        self.items = {1000 + i: float(p) for i, p in enumerate(prices)}
        self.limit = limit
        self.with_pagination = with_pagination
        self.upper_inclusive = upper_inclusive
        self.reserved = set()
        self.titles = {}          # id -> tytuł (domyślnie „Laptop <id>”)
        self.fail = fail          # funkcja (price_from, price_to, page) -> True = rzuć błąd
        self.requests = []

    def query(self, price_from, price_to):
        def ok(p):
            if price_from is not None and p < price_from:
                return False
            if price_to is not None and (p > price_to if self.upper_inclusive else p >= price_to):
                return False
            return True
        return sorted((i for i, p in self.items.items() if ok(p)), reverse=True)

    def response(self, page, per_page, price_from, price_to):
        ids = self.query(price_from, price_to)
        visible = ids[:self.limit]
        chunk = visible[(page - 1) * per_page: page * per_page]
        data = {"items": [{"id": i, "title": self.titles.get(i, f"Laptop {i}"), "price": {"amount": f"{self.items[i]:.2f}",
                                                                       "currency_code": "PLN"},
                           "item_box": {"accessibility_label": f"Laptop {i}, Marka: Lenovo, Stan: Bardzo dobry, "
                                                               f"{self.items[i]:.2f} zł", "second_line": "Bardzo dobry"},
                           "is_reserved": i in self.reserved,
                           "user": {"id": i % 7, "login": "ktos"},
                           "photo": {"url": f"https://images1.vinted.net/{i}.webp",
                                     "high_resolution": {"timestamp": 1780000000 + i}}} for i in chunk]}
        if self.with_pagination:
            data["pagination"] = {"current_page": page, "per_page": per_page, "total_entries": len(ids),
                                  "total_pages": max(1, -(-len(visible) // per_page))}
        return data

    async def fetch(self, session, catalog_id, page, per_page, price_from=None, price_to=None, order="newest_first",
                    seller_salt="", margin=0.0):
        self.requests.append((price_from, price_to, page))
        price_from, price_to = widen(price_from, price_to, margin)
        if self.fail and self.fail(price_from, price_to, page):
            raise OSError("atrapa: zerwane połączenie")
        return parse_page(self.response(page, per_page, price_from, price_to), catalog_id, page, per_page, seller_salt)


def market_prices(n, seed=1):
    rnd = random.Random(seed)
    prices = []
    for _ in range(n):
        p = rnd.lognormvariate(7.3, 0.6)          # mediana ~1500 zł, jak laptopy
        prices.append(round(min(p, 30000), 0 if rnd.random() < 0.7 else 2))
    return prices


async def no_sleep(_seconds):
    return None
