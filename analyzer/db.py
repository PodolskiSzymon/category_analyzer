"""SQLite analizatora: schemat (ARCHITEKTURA.md, sekcja 3), migracje przez PRAGMA user_version, tryb WAL.

Zasada „brak danych jest jawny”: NULL = katalog/szczegóły nie podały wartości (albo jeszcze nie sprawdzaliśmy).
Czas zawsze UTC ISO 8601 (tekst), ceny w zł (REAL).
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import rawstore

SCHEMA_V1 = """
CREATE TABLE listings (
  id              INTEGER PRIMARY KEY,
  catalog_id      INTEGER NOT NULL,
  title           TEXT,
  brand           TEXT,
  status_label    TEXT,
  currency        TEXT,
  photo_url       TEXT,
  photo_ts        INTEGER,                  -- znacznik czasu zdjęcia głównego (przybliżenie daty wystawienia), NULL = brak
  created_at      TEXT,
  first_seen      TEXT NOT NULL,
  last_seen       TEXT NOT NULL,
  last_run_id     INTEGER,                  -- ostatnie przejście, w którym oferta była w katalogu
  missed_runs     INTEGER NOT NULL DEFAULT 0,  -- ile pełnych przejść z rzędu jej nie było
  state           TEXT NOT NULL DEFAULT 'active',
  state_at        TEXT,
  sold_price      REAL,
  days_to_sell    REAL,
  details_at      TEXT,
  content_hash    TEXT,
  relist_of       INTEGER,
  seller_hash     TEXT
);
CREATE INDEX listings_state ON listings(state);
CREATE INDEX listings_catalog ON listings(catalog_id);

CREATE TABLE observations (
  listing_id      INTEGER NOT NULL REFERENCES listings(id),
  seen_at         TEXT NOT NULL,
  price           REAL,
  total_price     REAL,
  is_reserved     INTEGER,
  favourite_count INTEGER,
  PRIMARY KEY (listing_id, seen_at)
);

CREATE TABLE raw (
  listing_id      INTEGER NOT NULL,
  kind            TEXT NOT NULL,
  fetched_at      TEXT NOT NULL,
  body            BLOB NOT NULL,
  PRIMARY KEY (listing_id, kind, fetched_at)
);

CREATE TABLE specs (
  listing_id      INTEGER PRIMARY KEY,
  cpu TEXT, cpu_src TEXT,
  gpu TEXT, gpu_src TEXT,
  ram_gb INTEGER, ram_src TEXT,
  storage_gb INTEGER, storage_src TEXT,
  screen_in REAL, screen_src TEXT,
  model TEXT, model_src TEXT,
  defects TEXT, defects_src TEXT,
  extractor_version INTEGER NOT NULL,
  extracted_at TEXT NOT NULL
);

CREATE TABLE ai_cache (
  content_hash    TEXT NOT NULL,
  task            TEXT NOT NULL,
  model           TEXT NOT NULL,
  result_json     TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  PRIMARY KEY (content_hash, task)
);

-- Partycje wyszukiwania. price_to NULL = bez górnej granicy. Liście drzewa podziału = aktywne partycje
-- (active=1); podzielona partycja zostaje z active=0 dla historii.
CREATE TABLE partitions (
  id INTEGER PRIMARY KEY,
  catalog_id INTEGER NOT NULL,
  price_from REAL,
  price_to REAL,
  extra_json TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  last_total INTEGER,                       -- total_entries z ostatniego przejścia (NULL = API nie podało)
  last_items INTEGER,                       -- ile ofert faktycznie zebrano
  last_crawled_at TEXT,
  done_run_id INTEGER,                      -- przejście, w którym partycję ukończono (wznawianie)
  oversize INTEGER NOT NULL DEFAULT 0       -- 1 = za dużo ofert nawet przy minimalnej szerokości ceny
);

CREATE TABLE crawl_runs (
  id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, kind TEXT, catalog_id INTEGER,
  requests INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0, new_ids INTEGER DEFAULT 0, changed INTEGER DEFAULT 0,
  gone INTEGER DEFAULT 0, errors INTEGER DEFAULT 0, seen INTEGER DEFAULT 0
);
"""

# v2 (probe 2026-10-11): katalog podaje favourite_count i view_count - zmieniają się przy prawie każdym przejściu,
# więc trzymamy tylko ostatnią wartość w listings (bez nowego wiersza observations za każdym razem).
SCHEMA_V2 = """
ALTER TABLE listings ADD COLUMN favourite_count INTEGER;
ALTER TABLE listings ADD COLUMN view_count INTEGER;
"""

# v3: model z item_box (np. „ThinkPad X1 Carbon”) - wypełnia sprzedający, gotowy klucz do grupowania cen.
SCHEMA_V3 = """
ALTER TABLE listings ADD COLUMN model TEXT;
"""

MIGRATIONS = [SCHEMA_V1, SCHEMA_V2, SCHEMA_V3]


def utcnow():
    # Milisekundy: dwa przejścia (albo test) w tej samej sekundzie nie mogą nadpisać obserwacji (klucz seen_at).
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def connect(path):
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def migrate(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        with conn:
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version={number}")


def put_raw(conn, listing_id, kind, obj, fetched_at=None):
    conn.execute("INSERT OR REPLACE INTO raw (listing_id, kind, fetched_at, body) VALUES (?, ?, ?, ?)",
                 (listing_id, kind, fetched_at or utcnow(), rawstore.compress(obj)))


def get_raw(conn, listing_id, kind):
    """Wszystkie surowe odpowiedzi danego rodzaju, od najstarszej: [(fetched_at, obj)]."""
    rows = conn.execute("SELECT fetched_at, body FROM raw WHERE listing_id=? AND kind=? ORDER BY fetched_at",
                        (listing_id, kind)).fetchall()
    return [(r["fetched_at"], rawstore.decompress(r["body"])) for r in rows]


def last_observation(conn, listing_id):
    return conn.execute("SELECT * FROM observations WHERE listing_id=? ORDER BY seen_at DESC LIMIT 1",
                        (listing_id,)).fetchone()


_OBSERVED = ("price", "total_price", "is_reserved", "favourite_count")
# Nowy wiersz observations (i surowy JSON) tylko przy zmianie ceny / rezerwacji; polubienia i wyświetlenia
# aktualizujemy w listings (ostatnia wartość przed zniknięciem oferty = „popyt” w chwili sprzedaży).
_PRICE_STATUS = ("price", "total_price", "is_reserved")
# Stany, z których oferta wraca do active/reserved, gdy znów pojawi się w katalogu.
_REVIVABLE = "('active', 'reserved', 'gone_pending', 'hidden', 'unlisted', 'below_min')"


def upsert_item(conn, item, run_id, seen_at):
    """Zapis jednej pozycji katalogu (CatalogItem). Zwraca 'new' / 'changed' / 'same'.

    Obserwacja (cena, rezerwacja, polubienia) - nowy wiersz tylko przy zmianie. Surowy JSON pozycji katalogu -
    przy pierwszym wystąpieniu i przy każdej zmianie obserwacji (żeby nie powielać identycznych danych).
    """
    row = conn.execute("SELECT id FROM listings WHERE id=?", (item.id,)).fetchone()
    obs = {k: getattr(item, k) for k in _OBSERVED}
    if row is None:
        conn.execute(
            """INSERT INTO listings (id, catalog_id, title, brand, status_label, currency, photo_url, photo_ts,
                   first_seen, last_seen, last_run_id, state, state_at, seller_hash, favourite_count, view_count, model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.id, item.catalog_id, item.title, item.brand, item.status_label, item.currency, item.photo_url,
             item.photo_ts, seen_at, seen_at, run_id, item.state, seen_at, item.seller_hash, item.favourite_count,
             item.view_count, item.model))
        conn.execute("INSERT INTO observations (listing_id, seen_at, price, total_price, is_reserved, favourite_count)"
                     " VALUES (?, ?, ?, ?, ?, ?)", (item.id, seen_at, *obs.values()))
        put_raw(conn, item.id, "catalog", item.raw, seen_at)
        return "new"

    # Dane „stałe” uzupełniamy (COALESCE) - brak w nowej odpowiedzi nie kasuje tego, co już wiemy.
    conn.execute(
        f"""UPDATE listings SET last_seen=?, last_run_id=?, missed_runs=0,
               title=COALESCE(?, title), brand=COALESCE(?, brand), status_label=COALESCE(?, status_label),
               currency=COALESCE(?, currency), photo_url=COALESCE(?, photo_url), photo_ts=COALESCE(photo_ts, ?),
               seller_hash=COALESCE(seller_hash, ?),
               favourite_count=COALESCE(?, favourite_count), view_count=COALESCE(?, view_count),
               model=COALESCE(?, model),
               state_at=CASE WHEN state IN {_REVIVABLE} AND state != ? THEN ? ELSE state_at END,
               state=CASE WHEN state IN {_REVIVABLE} THEN ? ELSE state END
           WHERE id=?""",
        (seen_at, run_id, item.title, item.brand, item.status_label, item.currency, item.photo_url, item.photo_ts,
         item.seller_hash, item.favourite_count, item.view_count, item.model, item.state, seen_at, item.state, item.id))
    last = last_observation(conn, item.id)
    if last is not None and all(last[k] == obs[k] for k in _PRICE_STATUS):
        return "same"
    conn.execute("INSERT OR REPLACE INTO observations (listing_id, seen_at, price, total_price, is_reserved, "
                 "favourite_count) VALUES (?, ?, ?, ?, ?, ?)", (item.id, seen_at, *obs.values()))
    put_raw(conn, item.id, "catalog", item.raw, seen_at)
    return "changed"
