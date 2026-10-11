"""Strona katalogu svc-catalogue: zapytanie (parametry jak w Sniperze, sprawdzone na żywo) + parsowanie pozycji.

Pola pozycji katalogu poza `id`, `title`, `price` (dict amount/currency_code) NIE są jeszcze potwierdzone
na odpowiedzi z laptopów - parser czyta je ostrożnie (brak = None) i zawsze zachowuje surowy JSON (`raw`),
więc po zebraniu fixtures z `python -m analyzer probe` można dopisać pola wstecz, bez ponownego scrapowania.
"""
import hashlib
from dataclasses import dataclass, field

from sniper.config import CATALOG_ONLY_HEADERS, CATALOG_URL, get_catalog_params

CATALOG_REFERER = "https://www.vinted.pl/"


def to_float(value):
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        value = value.get("amount")
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def to_bool(value):
    if value is None:
        return None
    return 1 if value else 0


def fmt_price(value):
    """Cena do parametru zapytania: bez zbędnych zer („100”, „99.5”)."""
    if value is None:
        return ""
    return f"{value:.2f}".rstrip("0").rstrip(".")


@dataclass
class CatalogItem:
    id: int
    catalog_id: int
    title: str = None
    price: float = None
    total_price: float = None
    currency: str = None
    brand: str = None
    status_label: str = None
    photo_url: str = None
    photo_ts: int = None
    is_reserved: int = None
    favourite_count: int = None
    seller_hash: str = None
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def state(self):
        return "reserved" if self.is_reserved else "active"


def _seller_hash(item, salt):
    user = item.get("user")
    user_id = user.get("id") if isinstance(user, dict) else item.get("user_id")
    if not salt or user_id is None:
        return None
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()[:24]


def strip_personal(item):
    """Kopia pozycji bez danych sprzedawcy (RODO) - tak trafia do tabeli `raw`."""
    clean = dict(item)
    if isinstance(clean.get("user"), dict):
        clean["user"] = {"redacted": True}
    for key in ("user_id", "user_login"):
        clean.pop(key, None)
    return clean


def parse_item(item, catalog_id, seller_salt=""):
    photo = item.get("photo") if isinstance(item.get("photo"), dict) else {}
    high_res = photo.get("high_resolution") if isinstance(photo.get("high_resolution"), dict) else {}
    price = item.get("price")
    currency = price.get("currency_code") if isinstance(price, dict) else item.get("currency")
    favourites = item.get("favourite_count")
    return CatalogItem(
        id=int(item["id"]),
        catalog_id=int(item.get("catalog_id") or catalog_id),
        title=item.get("title") or None,
        price=to_float(price),
        total_price=to_float(item.get("total_item_price")),
        currency=currency or None,
        brand=item.get("brand_title") or None,
        status_label=item.get("status") or None,
        photo_url=photo.get("url") or None,
        photo_ts=high_res.get("timestamp"),
        is_reserved=to_bool(item.get("is_reserved")),
        favourite_count=int(favourites) if isinstance(favourites, (int, float)) else None,
        seller_hash=_seller_hash(item, seller_salt),
        raw=strip_personal(item),
    )


@dataclass
class CatalogPage:
    items: list
    total_entries: int = None     # None = API nie podało (⚠ do sprawdzenia probe)
    total_pages: int = None
    page: int = 1
    per_page: int = None
    raw_keys: tuple = ()


def parse_page(data, catalog_id, page, per_page, seller_salt=""):
    items = []
    for raw in data.get("items") or []:
        if isinstance(raw, dict) and raw.get("id") is not None:
            items.append(parse_item(raw, catalog_id, seller_salt))
    pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}

    def _int(key):
        value = pagination.get(key)
        return int(value) if isinstance(value, (int, float)) else None

    return CatalogPage(items=items, total_entries=_int("total_entries"), total_pages=_int("total_pages"),
                       page=page, per_page=_int("per_page") or per_page, raw_keys=tuple(data))


def build_params(catalog_id, page, per_page, price_from=None, price_to=None, order="newest_first"):
    return get_catalog_params(category=str(catalog_id), page=page, per_page=per_page, order=order,
                              price_from=fmt_price(price_from), price_to=fmt_price(price_to))


async def fetch_page(session, catalog_id, page, per_page, price_from=None, price_to=None, order="newest_first",
                     seller_salt=""):
    params = build_params(catalog_id, page, per_page, price_from, price_to, order)
    data = await session.get_json(CATALOG_URL, params=params, referer=CATALOG_REFERER,
                                  extra_headers=CATALOG_ONLY_HEADERS)
    return parse_page(data if isinstance(data, dict) else {}, catalog_id, page, per_page, seller_salt)
