# Category Analyzer – architektura i plan

Projekt na start (2026-10-11). Wszystko poniżej to **plan** – założenia oznaczone „⚠ do sprawdzenia” trzeba potwierdzić
na prawdziwych odpowiedziach Vinted (cURL z F12 u użytkownika), zanim powstanie kod, który na nich polega.

## 1. Przegląd

```
                   ┌───────────────────────── co kilka godzin / raz na dobę ─────────────────────────┐
                   │                                                                                  │
 planer partycji ──► crawler katalogu ──► migawka (ID, cena, status z katalogu) ──► diff z poprzednią │
 (dzielenie cen)     (VintedSession,       zapis: listings + observations            │                │
                      proxy IPRoyal)                                                  │                │
                                                         nowe ID ──► detale (1x, ~15 KB) ──► raw + opis
                                                         zmienione ──► observation (cena/status)
                                                         zniknięte ──► resolver (1 zapytanie) ──► sprzedana / usunięta
                                                                                                       │
 extract (regex → AI wsadowo, cache po hashu treści) ◄────────────────────────────────────────────────┘
        │
        ▼
 stats / report (SQL, pandas) ──► CSV / HTML ──► (opcjonalnie) zestawienia dla dużego modelu
        │
        ▼
 Sniper: ceny rynkowe w ocenie AI + dopisywanie nowych ofert do bazy (etap 5)
```

Zasada nadrzędna: **każdy bajt przez proxy pobieramy raz**. Katalog jest tani (~0,4 KB/ofertę), szczegóły drogie
(~15 KB) i pobierane raz na ofertę, zdjęcia najdroższe (50–200 KB) i pobierane tylko wyjątkowo.

## 2. Struktura repo (docelowa)

```
category_analyzer/
├── CLAUDE.md, ARCHITEKTURA.md
├── sniper/                 # kopia Snipera (reużywane: session, config, extractor, traffic, evaluator)
├── analyzer/
│   ├── __init__.py
│   ├── __main__.py         # CLI: crawl | resolve | extract | report | stats | vacuum
│   ├── config.py           # AnalyzerConfig (ANALYZER_* z sniper/.env), reużywa ScoutConfig dla proxy
│   ├── db.py               # SQLite: schemat, migracje (PRAGMA user_version), zapis wsadowy, WAL
│   ├── rawstore.py         # surowy JSON skompresowany (zstd, słownik trenowany na próbce) w tabeli raw
│   ├── catalog.py          # pobranie strony katalogu (params jak sniper.config.get_catalog_params) + parsowanie pozycji
│   ├── partition.py        # planer partycji: dzielenie zakresu cen do < limitu wyników
│   ├── crawler.py          # przejście wszystkich partycji, migawka, tempo, wznawianie po przerwie
│   ├── diff.py             # porównanie migawek: nowe / zmienione / zniknięte
│   ├── resolver.py         # zniknięte → details/sidebar → sold / deleted / hidden / reserved
│   ├── details.py          # pobranie szczegółów nowych ofert (sniper.extractor) - raz na ofertę
│   ├── extract.py          # parametry: regex (CPU/GPU/RAM/SSD/ekran) + AI wsadowo, cache po hashu treści
│   ├── photos.py           # (opcjonalnie) miniatura + perceptual hash → wykrywanie ponownych wystawień
│   ├── stats.py            # zapytania analityczne (mediany, kwantyle, czas sprzedaży)
│   ├── report.py           # raporty CSV/HTML, eksport zestawień dla LLM
│   └── tests/              # pytest bez sieci, fixtures z prawdziwych odpowiedzi
└── data/                   # .gitignore: analyzer.db, raporty, miniatury
```

## 3. Baza danych (SQLite, jeden plik `data/analyzer.db`)

Dlaczego SQLite: jeden plik, bez serwera, SQL do analiz, zapis transakcyjny, pandas/DuckDB czytają go bezpośrednio.
Tryb WAL (zapis i odczyt naraz – crawler pisze, raport czyta). Przy setkach milionów obserwacji można później
eksportować do Parquet/DuckDB – na start niepotrzebne.

```sql
-- Jedna oferta Vinted (stałe / rzadko zmieniane dane).
CREATE TABLE listings (
  id              INTEGER PRIMARY KEY,      -- ID Vinted (klucz deduplikacji, za darmo z katalogu)
  catalog_id      INTEGER NOT NULL,
  title           TEXT,
  brand           TEXT,                     -- NULL = brak w danych
  status_label    TEXT,                     -- stan („Nowy z metką”, „Bardzo dobry” …)
  currency        TEXT,
  photo_url       TEXT,                     -- URL zdjęcia głównego (bez pobierania)
  created_at      TEXT,                     -- ⚠ do sprawdzenia, czy katalog/sidebar to podaje; NULL = nieznane
  first_seen      TEXT NOT NULL,            -- pierwsze wystąpienie w naszych migawkach (UTC ISO)
  last_seen       TEXT NOT NULL,            -- ostatnie wystąpienie w katalogu
  state           TEXT NOT NULL DEFAULT 'active',  -- active | reserved | gone_pending | sold | deleted | hidden
  state_at        TEXT,                     -- kiedy ustaliliśmy obecny stan
  sold_price      REAL,                     -- ostatnia cena wystawienia przed sprzedażą (górna granica ceny transakcji)
  days_to_sell    REAL,                     -- state_at(sold) - COALESCE(created_at, first_seen)
  details_at      TEXT,                     -- kiedy pobrano szczegóły (NULL = jeszcze nie)
  content_hash    TEXT,                     -- sha1(tytuł + opis) - klucz cache AI
  relist_of       INTEGER,                  -- ID oferty, której to ponowne wystawienie (etap photos)
  seller_hash     TEXT                      -- opcjonalnie: sha256(seller_id + sól) - bez danych osobowych
);

-- Historia: nowy wiersz TYLKO przy zmianie ceny / statusu (nie przy każdej migawce).
CREATE TABLE observations (
  listing_id      INTEGER NOT NULL REFERENCES listings(id),
  seen_at         TEXT NOT NULL,
  price           REAL,
  total_price     REAL,                     -- z opłatą za ochronę kupującego, jeśli katalog ją podaje (⚠)
  is_reserved     INTEGER,                  -- NULL = katalog nie podaje
  favourite_count INTEGER,                  -- ⚠ jeśli jest w katalogu - przydatne do „popytu”
  PRIMARY KEY (listing_id, seen_at)
);

-- Surowe odpowiedzi (do ponownej ekstrakcji bez ponownego scrapowania).
CREATE TABLE raw (
  listing_id      INTEGER NOT NULL,
  kind            TEXT NOT NULL,            -- catalog | sidebar | shipping | resolve
  fetched_at      TEXT NOT NULL,
  body            BLOB NOT NULL,            -- zstd(JSON)
  PRIMARY KEY (listing_id, kind, fetched_at)
);

-- Parametry wyciągnięte z tytułu/opisu; każde pole z wartością i źródłem.
CREATE TABLE specs (
  listing_id      INTEGER PRIMARY KEY,
  cpu TEXT, cpu_src TEXT,                   -- src: title | description | ai | none  (none = szukano, nie znaleziono)
  gpu TEXT, gpu_src TEXT,
  ram_gb INTEGER, ram_src TEXT,
  storage_gb INTEGER, storage_src TEXT,
  screen_in REAL, screen_src TEXT,
  model TEXT, model_src TEXT,               -- np. „Lenovo Legion 5 15ACH6”
  defects TEXT, defects_src TEXT,           -- uszkodzenia / blokady wspomniane w opisie
  extractor_version INTEGER NOT NULL,       -- nowa wersja reguł → ponowna ekstrakcja z raw, bez sieci
  extracted_at TEXT NOT NULL
);

-- Cache AI: ta sama treść = ten sam wynik, bez drugiego wywołania.
CREATE TABLE ai_cache (
  content_hash    TEXT NOT NULL,
  task            TEXT NOT NULL,            -- np. specs_v1
  model           TEXT NOT NULL,
  result_json     TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  PRIMARY KEY (content_hash, task)
);

-- Partycje wyszukiwania i przebiegi crawlera (wznawianie, statystyki transferu).
CREATE TABLE partitions (
  id INTEGER PRIMARY KEY, catalog_id INTEGER, price_from REAL, price_to REAL, extra_json TEXT,
  last_total INTEGER, last_crawled_at TEXT
);
CREATE TABLE crawl_runs (
  id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, kind TEXT,
  requests INTEGER, bytes INTEGER, new_ids INTEGER, changed INTEGER, gone INTEGER, errors INTEGER
);
```

„Brak informacji” jest zawsze jawny: `NULL` w kolumnie wartości + `*_src = 'none'` w `specs` (szukano, nie ma) albo
`NULL` w `*_src` (jeszcze nie szukano). Surowy JSON w `raw` pozwala w każdej chwili wyciągnąć nowe pola wstecz.

## 4. Crawler i podział wyszukiwania

**Problem**: jedno wyszukiwanie zwraca ograniczoną liczbę wyników (limit stron × `per_page`), a ofert w kategorii jest
więcej. **Rozwiązanie**: partycje po cenie (dzielenie przedziału na pół), dopóki partycja nie zmieści się w limicie.

```
plan(cat, lo, hi):
    total = total_entries(cat, lo, hi)          # 1 tanie zapytanie (per_page mały)  ⚠ czy API to podaje
    if total <= LIMIT * 0.9 or hi - lo <= 1 zł:  # zapas na oferty dodane w trakcie
        return [(lo, hi)]
    mid = mediana_cen_lub_środek(lo, hi)
    return plan(cat, lo, mid) + plan(cat, mid, hi)
```

* Planer zapamiętuje partycje w `partitions` – kolejne przejścia zaczynają od gotowego podziału i dzielą tylko te,
  które urosły ponad limit (oszczędność zapytań).
* Gdy jedna cena (np. dokładnie 1000 zł) ma więcej ofert niż limit → druga oś: marka (`attribute_ids[brand]`) albo stan
  (`attribute_ids[status]`) – wartości ID tylko z cURL, nie zgadujemy.
* ⚠ Jeśli API **nie** podaje `total_entries`: wykrywamy limit empirycznie (pełna ostatnia strona = partycja za duża).
* Granice: `price_from`/`price_to` – ⚠ sprawdzić, czy są włącznie (żeby nie gubić ofert dokładnie na granicy).
  Bezpiecznie: zakresy nachodzące o 0,01 zł + deduplikacja po ID.
* Sortowanie w partycji: stałe (np. `price_low_to_high` ⚠ nazwa z cURL) – żeby stronicowanie nie „przesuwało się” przy
  nowych ofertach tak bardzo jak przy `newest_first`.
* `per_page` maksymalny sensowny (96 sprawdzone w Sniperze: ~39 KB/stronę ≈ 0,4 KB/ofertę).
* Tempo: losowe przerwy między stronami (`ANALYZER_PAGE_DELAY_S`, np. 2–6 s), pełne przejście rozłożone na godziny;
  401/403 → `VintedSession` sam odświeża sesję. Wznawianie po przerwaniu: postęp per partycja w `crawl_runs`.
* Zapis wsadowy (transakcja na stronę), żeby SQLite nie był wąskim gardłem.

## 5. Migawki, zmiany i sprzedaż

Po każdym pełnym przejściu (migawka = zbiór ID widzianych w tym przebiegu):

| Przypadek | Akcja | Koszt |
|---|---|---|
| nowe ID | `listings` + `observations`; kolejka `details` (raz) | katalog + 1 × ~15 KB |
| znane ID, zmiana ceny / rezerwacji | nowy wiersz w `observations` | 0 (z katalogu) |
| znane ID, bez zmian | tylko `last_seen` | 0 |
| ID zniknęło (2 przejścia z rzędu – odporność na chwilowe braki) | `gone_pending` → `resolver` | 1 zapytanie |

**Resolver** (`details/sidebar`):
* `plugins.item_status.item_closing_action == "sold"` → `sold` (sprawdzone na żywo – fixture `sidebar_sold`),
  `sold_price` = ostatnia cena z `observations`, `days_to_sell` = czas od `created_at` (⚠) albo `first_seen`.
* rezerwacja (`is_reserved`) → `reserved`, sprawdzić ponownie później.
* oferta usunięta → **HTTP 404, `code` 104** (sprawdzone u użytkownika 2026-10-11) → `deleted`; aktywna, ale
  niewidoczna w katalogu → `unlisted` (ponowne sprawdzenie co kilka dni).
* Ponowne wystawienie (ta sama oferta pod nowym ID) – etap `photos`: miniatura (kilka KB) + pHash, porównanie
  z ofertami tego samego „modelu” w oknie czasu → `relist_of`. Bez tego `days_to_sell` bywa zaniżone.

Częstotliwość: pełne przejście katalogu np. co 6–12 h (zmiany cen/statusów widać w katalogu); resolver zaraz po
przejściu, tylko dla zniknętych.

## 6. Parametry (extract)

1. **Reguły** (`extract.py`, wersjonowane `extractor_version`): regex na tytuł + opis – CPU (i5/i7/i9-xxxxx, Ryzen
   5/7/9 xxxx, M1/M2/M3…), GPU (RTX/GTX xxxx, „Radeon”), RAM („16 GB RAM”, „16gb”), dysk („512 SSD”, „1TB”), ekran
   („15,6"”, „15.6 cala”), słowa o usterkach („uszkodz”, „na części”, „blokada icloud/bios”). Testy na prawdziwych tytułach.
2. **AI** tylko dla ofert, gdzie reguły nie dały modelu/CPU/GPU: tryb wsadowy (Gemini batch / Anthropic Message Batches),
   wynik w JSON-schema (`specs`), cache `ai_cache` po `content_hash`. Backendy z `sniper/evaluator.py`.
3. Zmiana reguł → ponowna ekstrakcja z `raw` (bez sieci).

## 7. Analiza i raporty

* `stats.py` – zapytania SQL: mediana / kwartyle `sold_price` i `days_to_sell` per (GPU, CPU, RAM, model), liczba
  sprzedanych w 30/90 dni, odsetek ofert, które zeszły z ceny, średnia obniżka przed sprzedażą.
* `report.py` – CSV + prosty HTML (jak `sniper/report.py`), eksport „zestawień dla LLM” (tabela agregatów, nie surowe
  wiersze) – do wklejenia do rozmowy z Claude albo do wywołania dużego modelu.
* Próg minimalnej liczby próbek (np. ≥ 10 sprzedanych) przed podaniem mediany – inaczej „za mało danych”.

## 8. Integracja ze Sniperem (etap 5)

1. **Wspólna baza**: Sniper (w `unreachable_sniper`) dostaje opcjonalny zapis każdej złapanej oferty do
   `data/analyzer.db` (`ANALYZER_DB` w `.env`) – te same tabele `listings`/`observations`/`raw`. Sniper i tak pobiera
   szczegóły nowych ofert → analizator nie musi pobierać ich drugi raz.
2. **Ceny rynkowe w ocenie AI**: `sniper/evaluator.py` przed wywołaniem modelu pyta `stats` o medianę ceny sprzedaży
   i czas sprzedaży dla wykrytej konfiguracji i dokleja je do promptu („podobne sprzedały się za X zł w Y dni, n=Z”).
   `guidelines.md` zostaje jako zasady, ale progi cen biorą się z danych.
3. Jeden proces czy dwa: na start dwa osobne programy na tej samej bazie (WAL pozwala na równoczesny odczyt; zapis
   krótkimi transakcjami). Nie uruchamiać dwóch crawlerów tej samej kategorii naraz.

## 9. Budżet transferu i miejsca (szacunek do weryfikacji pomiarem `traffic.py`)

| Operacja | Na ofertę | 100 tys. ofert |
|---|---|---|
| Przejście katalogu (`per_page` 96) | ~0,4 KB | ~40 MB / przejście |
| Szczegóły (raz) | ~15 KB | ~1,5 GB (jednorazowo) |
| Resolver (tylko zniknięte) | ~15 KB | zależnie od rotacji |
| Miniatura do pHash (opcjonalnie) | ~5–15 KB | ~1 GB |

Miejsce: ~5 KB surowego JSON na ofertę → po zstd ~1 KB; 1 mln ofert ≈ kilka GB z indeksami. Pełne zdjęcia (pominąć!)
to setki GB. 500 GB wystarcza z ogromnym zapasem; dodatkowy SSD niepotrzebny.

## 10. Konfiguracja (`sniper/.env`, sekcja ANALYZER_*)

```
ANALYZER_DB=data/analyzer.db
ANALYZER_CATALOGS=3580                # laptopy; lista po przecinku
ANALYZER_PER_PAGE=96
ANALYZER_PAGE_DELAY_S=2-6             # losowo, jak SCRAPER_* w Sniperze
ANALYZER_PARTITION_FILL=0.9           # dziel partycję powyżej 90% limitu
ANALYZER_GONE_AFTER_RUNS=2            # ile przejść bez oferty, zanim resolver
ANALYZER_AI_BATCH=true
ANALYZER_PHOTOS=false                 # pHash miniatur (etap później)
```
Proxy, nagłówki, klucz AI – wspólne ze Sniperem (`SNIPER_PROXY_*`, `SNIPER_AI_*`).

## 11. Testy

* pytest bez sieci: `httpx.MockTransport` z fixtures katalogu (od użytkownika), planer partycji na syntetycznym
  „rynku” (np. 50 tys. cen, limit 960) – sprawdza, że suma partycji pokrywa wszystkie ID bez dziur na granicach.
* `diff`/`resolver` na sekwencjach migawek (nowa → zmiana ceny → zniknięcie → sold).
* `extract` na zestawie prawdziwych tytułów (z `offers.jsonl` Snipera) z oczekiwanymi wartościami.

## 12. Etapy i kryteria ukończenia

Stan 2026-10-11: etap 1 napisany (+ `diff.py` z etapu 2 i `probe.py` do etapu 0), testy na atrapie przechodzą;
etap 0 czeka na uruchomienie `python -m analyzer probe` u użytkownika. Odstępstwa od planu wyżej: planer nie robi
osobnych zapytań „ile ofert” – używa `total_entries` z 1. strony partycji, którą i tak pobiera; partycje dzielą
granicę ([lo, mid] + [mid, hi]) zamiast nakładać się o 0,01 zł; sortowanie `newest_first` (jedyne sprawdzone).

| Etap | Zakres | Gotowe, gdy |
|---|---|---|
| 0 | cURL katalogu + odpowiedzi od użytkownika → fixtures, odpowiedzi na „⚠” | wiadomo: `total_entries`, limit stron, pola pozycji, zachowanie granic cen, odpowiedź dla usuniętej oferty |
| 1 | `db`, `catalog`, `partition`, `crawler`, CLI `crawl` | jedno pełne przejście kategorii u użytkownika; unikalne ID ≈ suma `total_entries`; transfer w `crawl_runs` |
| 2 | `diff`, `resolver`, `details` | po 2–3 dniach: lista sprzedanych z `sold_price` i `days_to_sell` |
| 3 | `extract` (regex + AI wsadowo, cache) | ≥ 80% ofert z CPU i GPU; reszta z `*_src` |
| 4 | `stats`, `report` | raport mediana ceny / czas sprzedaży per GPU+CPU+RAM |
| 5 | integracja ze Sniperem | Sniper zapisuje do bazy; ocena AI z cenami rynkowymi w prompcie |
| 6 | `photos` (pHash) – opcjonalnie | wykryte ponowne wystawienia, poprawione `days_to_sell` |

## 13. Ryzyka i otwarte pytania

* ⚠ Limit wyników i obecność `total_entries` – od tego zależy algorytm partycji.
* ⚠ Czy katalog podaje datę utworzenia oferty (inaczej `days_to_sell` od pierwszego wystąpienia – dokładne tylko dla
  ofert, które pojawiły się po starcie analizatora).
* Faktyczna cena transakcji niewidoczna (oferty/negocjacje) – raportować jako „cena wystawienia przy sprzedaży”.
* Regulamin Vinted zabrania automatycznego pobierania danych – prywatny research, rozsądne tempo, bez danych osobowych.
* Zmiany API Vinted – trzymać surowe odpowiedzi (`raw`) i testy na fixtures, żeby szybko wykryć zmianę formatu.
