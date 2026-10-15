"""Konfiguracja analizatora - zmienne ANALYZER_* z sniper/.env (proxy, sesja i AI wspólne ze Sniperem)."""
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from sniper import config as sniper_config  # wczytuje sniper/.env (python-dotenv)

ROOT = Path(__file__).resolve().parent.parent


def _env(name, default=""):
    return os.getenv(name, default).strip()


def _env_int(name, default):
    value = _env(name)
    return int(value) if value else default


def _env_float(name, default):
    value = _env(name)
    return float(value) if value else default


def _env_bool(name, default):
    value = _env(name).lower()
    return default if not value else value in ("1", "true", "tak", "yes", "on")


def parse_range(text, default):
    """„2-6” -> (2.0, 6.0), „3” -> (3.0, 3.0); puste -> default."""
    text = (text or "").strip()
    if not text:
        return default
    low, sep, high = text.partition("-")
    low = float(low.replace(",", "."))
    high = float(high.replace(",", ".")) if sep else low
    return (min(low, high), max(low, high))


# Kategorie Vinted (catalog_id z cURL użytkownika 2026-10-12).
CATALOG_NAMES = {3580: "laptopy", 3661: "telefony", 3025: "konsole", 3728: "tablety",
                 # 2026-10-14: kategorie „mieszane” (klasyfikacja ofert regułami - analyzer/classify.py) i gry
                 3582: "podzespoły komputerowe", 3583: "puste nośniki", 3584: "akcesoria komputerowe"}
# Gry (3026) odpuszczone 2026-10-14 (użytkownik: pole „platforma” wypełniane bez ładu) - wrócimy kiedy indziej.
# Domyślna cena minimalna per kategoria (zł). Laptopy: decyzja użytkownika 2026-10-11 (< 700 zł = starocie).
# Telefony / konsole / tablety: 300 zł - propozycja Claude (poniżej głównie akcesoria, zepsute i bardzo stare modele);
# zmiana: ANALYZER_PRICE_MIN_<catalog_id>=..., np. ANALYZER_PRICE_MIN_3025=150.
DEFAULT_PRICE_MIN = {3580: 700.0, 3661: 300.0, 3025: 300.0, 3728: 300.0,
                     # kategorie mieszane: dolna granica crawla (próg każdej NASZEJ kategorii sprawdzamy osobno)
                     3582: 100.0, 3583: 100.0, 3584: 100.0}
# Nasze kategorie przedmiotu: te z własnym katalogiem Vinted biorą próg z katalogu, pozostałe - ANALYZER_PRICE_MIN_<NAZWA>.
CATEGORY_CATALOG = {"laptop": 3580, "phone": 3661, "console": 3025, "tablet": 3728}
DEFAULT_CATEGORY_MIN = {"gpu": 150.0, "ram": 100.0, "storage": 100.0}
# Szczegóły (details/sidebar) każdej oferty - domyślnie wszystkie nasze kategorie.
DEFAULT_DETAILS_CATEGORIES = ("laptop", "phone", "console", "tablet", "gpu", "ram", "storage")


def catalog_label(catalog_id):
    name = CATALOG_NAMES.get(int(catalog_id))
    return f"{catalog_id} ({name})" if name else str(catalog_id)


def _catalogs():
    raw = _env("ANALYZER_CATALOGS", ",".join(str(c) for c in CATALOG_NAMES))
    return tuple(int(c) for c in raw.replace(";", ",").split(",") if c.strip())


def _details_catalogs():
    """Nasze kategorie, dla których pobieramy szczegóły każdej oferty. ANALYZER_DETAILS_CATEGORIES (albo dawne
    ANALYZER_DETAILS_CATALOGS): nazwy (laptop, ram…) lub catalog_id (3580 → laptop); „all” = wszystkie (None)."""
    raw = (_env("ANALYZER_DETAILS_CATEGORIES") or _env("ANALYZER_DETAILS_CATALOGS")).lower()
    if not raw:
        return DEFAULT_DETAILS_CATEGORIES
    if raw in ("all", "*", "wszystkie"):
        return None
    by_catalog = {v: k for k, v in CATEGORY_CATALOG.items()}
    out = []
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if token:
            out.append(by_catalog.get(int(token), token) if token.isdigit() else token)
    return tuple(out)


@dataclass
class AnalyzerConfig:
    db_path: str = _env("ANALYZER_DB") or str(ROOT / "data" / "analyzer.db")
    catalogs: tuple = field(default_factory=_catalogs)
    per_page: int = _env_int("ANALYZER_PER_PAGE", 96)
    # Losowa przerwa między zapytaniami do katalogu (sekundy, zakres „od-do”).
    page_delay: tuple = field(default_factory=lambda: parse_range(_env("ANALYZER_PAGE_DELAY_S"), (2.0, 6.0)))
    # ⚠ Limit wyników jednego wyszukiwania - do potwierdzenia `python -m analyzer probe`.
    # Partycja jest dzielona, gdy total_entries > max_results * partition_fill.
    max_results: int = _env_int("ANALYZER_MAX_RESULTS", 960)
    partition_fill: float = _env_float("ANALYZER_PARTITION_FILL", 0.9)
    # Zakres cen całej kategorii w zł; powyżej price_max jest jedna otwarta partycja „od price_max”.
    # Oferty tańsze niż próg kategorii nie są crawlowane ani śledzone (stan below_min) - patrz price_min_for().
    # ANALYZER_PRICE_MIN (wspólny dla wszystkich kategorii) - tylko gdy ustawiony; domyślnie progi per kategoria.
    price_min: float = field(default_factory=lambda: _env_float("ANALYZER_PRICE_MIN", None))
    price_max: float = _env_float("ANALYZER_PRICE_MAX", 20000.0)
    initial_partitions: int = _env_int("ANALYZER_INITIAL_PARTITIONS", 8)
    # Partycja węższa niż tyle zł nie jest już dzielona po cenie (potrzebna druga oś - marka/stan, później).
    min_width: float = _env_float("ANALYZER_MIN_WIDTH", 1.0)
    # Zapas (zł) dokładany do granic zapytania. Domyślnie 0: filtr Vinted działa na swojej cenie (nie zawsze = `price`),
    # ale sąsiednie partycje dzielą granicę włącznie, więc każda oferta i tak trafia do którejś z nich. Zapas 1 zł
    # w 1. przejściu (2026-10-11) dawał tylko duplikaty na okrągłych cenach.
    price_margin: float = _env_float("ANALYZER_PRICE_MARGIN", 0.0)
    order: str = _env("ANALYZER_ORDER", "newest_first")   # jedyne sprawdzone na żywo sortowanie
    # Aktywna oferta niewidoczna w katalogu (unlisted) / zarezerwowana / ukryta - ponowne sprawdzenie co tyle dni.
    recheck_days: float = _env_float("ANALYZER_RECHECK_DAYS", 3.0)
    gone_after_runs: int = _env_int("ANALYZER_GONE_AFTER_RUNS", 2)
    # Sól do hasha sprzedawcy (RODO). Pusta = hash sprzedawcy nie jest zapisywany wcale.
    seller_salt: str = _env("ANALYZER_SELLER_SALT")
    # Kategorie, w których szczegóły pobieramy dla KAŻDEJ śledzonej oferty (details w watch). W pozostałych tylko
    # przy zniknięciu oferty (resolver zapisuje opis sprzedanej z tej samej odpowiedzi) - oszczędność transferu
    # proxy (decyzja użytkownika 2026-10-13). „all” = wszystkie kategorie.
    details_catalogs: tuple = field(default_factory=lambda: _details_catalogs())
    # Szczegóły ofert (details): losowa przerwa między zapytaniami (s).
    details_delay: tuple = field(default_factory=lambda: parse_range(_env("ANALYZER_DETAILS_DELAY_S"), (2.0, 5.0)))
    # Tryb `watch`: odstęp między startami pełnych przejść (godziny, zakres „od-do” - losowo).
    watch_hours: tuple = field(default_factory=lambda: parse_range(_env("ANALYZER_WATCH_HOURS"), (10.0, 14.0)))
    # Niedokończone przejście młodsze niż tyle godzin jest wznawiane zamiast zaczynane od nowa.
    resume_hours: float = _env_float("ANALYZER_RESUME_HOURS", 24.0)
    # Kategoria ze zdjęcia głównego przez AI, gdy tytuł pasuje do RAM-u i innej kategorii (ai_classify.py).
    # Dostawca i klucz z SNIPER_AI_*; model ANALYZER_AI_MODEL (puste = tani domyślny dostawcy).
    ai_classify: bool = _env_bool("ANALYZER_AI_CLASSIFY", True)
    ai_model: str = _env("ANALYZER_AI_MODEL")
    ai_classify_limit: int = _env_int("ANALYZER_AI_CLASSIFY_LIMIT", 500)     # ofert na jeden cykl watch

    def price_min_for(self, catalog_id):
        """Próg ceny kategorii: ANALYZER_PRICE_MIN_<id> > ANALYZER_PRICE_MIN > DEFAULT_PRICE_MIN > 700."""
        own = _env(f"ANALYZER_PRICE_MIN_{int(catalog_id)}")
        if own:
            return float(own)
        if self.price_min is not None:
            return self.price_min
        return DEFAULT_PRICE_MIN.get(int(catalog_id), 700.0)

    def category_min(self, category):
        """Próg ceny NASZEJ kategorii (laptop → próg katalogu 3580; gpu/ram/storage → ANALYZER_PRICE_MIN_GPU itd.)."""
        if category in CATEGORY_CATALOG:
            return self.price_min_for(CATEGORY_CATALOG[category])
        own = _env(f"ANALYZER_PRICE_MIN_{str(category).upper()}")
        if own:
            return float(own)
        return DEFAULT_CATEGORY_MIN.get(category, 0.0)

    @property
    def split_above(self):
        return int(self.max_results * self.partition_fill)

    def pick_delay(self):
        return random.uniform(*self.page_delay)

    def pick_details_delay(self):
        return random.uniform(*self.details_delay)


def build_session():
    """VintedSession z ustawieniami Snipera (proxy IPRoyal, odświeżanie sesji, zapis sesji na dysk)."""
    from sniper.session import VintedSession

    scout = sniper_config.ScoutConfig()
    sniper_config.require_proxy_url()
    session = VintedSession(
        proxy_url=scout.proxy_url,
        timeout=scout.request_timeout,
        browser_wait_ms=scout.browser_wait_ms,
        refresh_attempts=scout.refresh_attempts,
        refresh_retry_delay=scout.refresh_retry_delay,
        refresh_timeout=scout.refresh_timeout,
        browser_light=scout.browser_light,
        state_file=Path(scout.log_dir) / "session.json" if scout.log_dir else None,
    )
    session.load_state(scout.session_max_age_min * 60)
    return session
