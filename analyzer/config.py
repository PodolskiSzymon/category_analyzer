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


def parse_range(text, default):
    """„2-6” -> (2.0, 6.0), „3” -> (3.0, 3.0); puste -> default."""
    text = (text or "").strip()
    if not text:
        return default
    low, sep, high = text.partition("-")
    low = float(low.replace(",", "."))
    high = float(high.replace(",", ".")) if sep else low
    return (min(low, high), max(low, high))


def _catalogs():
    raw = _env("ANALYZER_CATALOGS", "3580")
    return tuple(int(c) for c in raw.replace(";", ",").split(",") if c.strip())


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
    # Laptopy tańsze niż price_min nas nie interesują (decyzja użytkownika 2026-10-11: < 700 zł to zwykle
    # bezużyteczne starocie) - nie crawlujemy ich i nie śledzimy (stan below_min).
    price_min: float = _env_float("ANALYZER_PRICE_MIN", 700.0)
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
    # Tryb `watch`: odstęp między startami pełnych przejść (godziny, zakres „od-do” - losowo).
    watch_hours: tuple = field(default_factory=lambda: parse_range(_env("ANALYZER_WATCH_HOURS"), (10.0, 14.0)))
    # Niedokończone przejście młodsze niż tyle godzin jest wznawiane zamiast zaczynane od nowa.
    resume_hours: float = _env_float("ANALYZER_RESUME_HOURS", 24.0)

    @property
    def split_above(self):
        return int(self.max_results * self.partition_fill)

    def pick_delay(self):
        return random.uniform(*self.page_delay)


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
