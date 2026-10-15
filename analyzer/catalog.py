"""Strona katalogu svc-catalogue: zapytanie (parametry jak w Sniperze, sprawdzone na żywo) + parsowanie pozycji.

Pola pozycji katalogu poza `id`, `title`, `price` (dict amount/currency_code) NIE są jeszcze potwierdzone
na odpowiedzi z laptopów - parser czyta je ostrożnie (brak = None) i zawsze zachowuje surowy JSON (`raw`),
więc po zebraniu fixtures z `python -m analyzer probe` można dopisać pola wstecz, bez ponownego scrapowania.
"""
import hashlib
import re
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
    model: str = None
    photo_url: str = None
    photo_ts: int = None
    is_reserved: int = None
    favourite_count: int = None
    view_count: int = None
    seller_hash: str = None
    seller_country: str = None
    # Nasza kategoria przedmiotu (classify.py); None = z katalogu Vinted.
    category: str = None
    category_src: str = None
    category_rule: str = None
    category_check: str = None     # pending = kategorię rozstrzygnie AI ze zdjęcia (classify.needs_photo_check)
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def state(self):
        return "reserved" if self.is_reserved else "active"


# item_box.accessibility_label (probe 2026-10-11):
#   "ThinkPad X1 Carbon 10th, 14\" WUXGA, i5-1245U, Marka: Lenovo, Model: ThinkPad X1 Carbon, Stan: Dobry, 1371.44 zł, 1442.91 zł"
# Tytuł może mieć przecinki, więc szukamy OSTATNIEGO wystąpienia etykiety (zachłanne ^.*). Model bywa pominięty.
_LABEL_FIELDS = {
    "brand": re.compile(r"^.*, Marka: (.+?)(?:, Model: |, Stan: |, \d[\d.,]* zł|$)"),
    "model": re.compile(r"^.*, Model: (.+?)(?:, Stan: |, \d[\d.,]* zł|$)"),
    "status": re.compile(r"^.*, Stan: (.+?)(?:, \d[\d.,]* zł|$)"),
}


def parse_item_box(item):
    """{'brand', 'model', 'status'} z item_box (brak = None). Stan: second_line, a gdy pusty - z etykiety."""
    box = item.get("item_box") if isinstance(item.get("item_box"), dict) else {}
    label = box.get("accessibility_label") or ""
    found = {}
    for key, pattern in _LABEL_FIELDS.items():
        match = pattern.search(label)
        found[key] = match.group(1).strip() if match else None
    found["status"] = (box.get("second_line") or "").strip() or found["status"]
    return found


def _seller_hash(item, salt):
    user = item.get("user")
    user_id = user.get("id") if isinstance(user, dict) else item.get("user_id")
    if not salt or user_id is None:
        return None
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()[:24]


# Kraj sprzedawcy nie jest daną osobową, a jest potrzebny (premia za Polskę w guidelines, oferty zagraniczne).
# ⚠ Niepotwierdzone, czy pozycja katalogu svc-catalogue ma te pola w `user` (Sniper czyta je stamtąd z założenia).
COUNTRY_KEYS = ("country_iso_code", "country_code", "country_title", "country_id")


def seller_country(item):
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    code = user.get("country_iso_code") or user.get("country_code")
    return str(code).upper() if code else None


def strip_personal(item):
    """Kopia pozycji bez danych sprzedawcy (RODO) - tak trafia do tabeli `raw`. Zostaje tylko kraj sprzedawcy."""
    clean = dict(item)
    if isinstance(clean.get("user"), dict):
        kept = {k: clean["user"][k] for k in COUNTRY_KEYS if clean["user"].get(k) is not None}
        clean["user"] = {"redacted": True, **kept}
    for key in ("user_id", "user_login"):
        clean.pop(key, None)
    return clean


def parse_item(item, catalog_id, seller_salt=""):
    photo = item.get("photo") if isinstance(item.get("photo"), dict) else {}
    high_res = photo.get("high_resolution") if isinstance(photo.get("high_resolution"), dict) else {}
    price = item.get("price")
    currency = price.get("currency_code") if isinstance(price, dict) else item.get("currency")
    favourites = item.get("favourite_count")
    views = item.get("view_count")
    box = parse_item_box(item)
    return CatalogItem(
        id=int(item["id"]),
        catalog_id=int(item.get("catalog_id") or catalog_id),
        title=item.get("title") or None,
        price=to_float(price),
        total_price=to_float(item.get("total_item_price")),
        currency=currency or None,
        brand=box["brand"] or item.get("brand_title") or None,
        status_label=box["status"] or item.get("status") or None,
        model=box["model"],
        photo_url=photo.get("url") or None,
        photo_ts=high_res.get("timestamp"),
        is_reserved=to_bool(item.get("is_reserved")),
        favourite_count=int(favourites) if isinstance(favourites, (int, float)) else None,
        view_count=int(views) if isinstance(views, (int, float)) else None,
        seller_hash=_seller_hash(item, seller_salt),
        seller_country=seller_country(item),
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


def widen(price_from, price_to, margin):
    """Zapytanie szersze o `margin` zł z obu stron. Probe 2026-10-11: filtr ceny Vinted nie pokrywa się dokładnie
    z polem `price` (price_to=666.98 zwróciło oferty po 667.76-667.88 zł - prawdopodobnie przeliczenia walut),
    więc nie ufamy granicy co do grosza; nadmiarowe oferty usuwa klucz = ID."""
    if not margin:
        return price_from, price_to
    low = None if price_from is None else max(0.0, price_from - margin)
    high = None if price_to is None else price_to + margin
    return low, high


def build_params(catalog_id, page, per_page, price_from=None, price_to=None, order="newest_first"):
    return get_catalog_params(category=str(catalog_id), page=page, per_page=per_page, order=order,
                              price_from=fmt_price(price_from), price_to=fmt_price(price_to))


async def fetch_page(session, catalog_id, page, per_page, price_from=None, price_to=None, order="newest_first",
                     seller_salt="", margin=0.0):
    price_from, price_to = widen(price_from, price_to, margin)
    params = build_params(catalog_id, page, per_page, price_from, price_to, order)
    data = await session.get_json(CATALOG_URL, params=params, referer=CATALOG_REFERER,
                                  extra_headers=CATALOG_ONLY_HEADERS)
    return parse_page(data if isinstance(data, dict) else {}, catalog_id, page, per_page, seller_salt)
