# Category Analyzer – kontekst projektu (dla nowej rozmowy z Claude)

Stan na 2026-10-11. **Etap 1 napisany i przetestowany na atrapie (bez sieci), czeka na etap 0 u użytkownika**
(`python -m analyzer probe` → wkleić `data/probe/<czas>/summary.txt` + pliki JSON). To repo jest kopią
`PodolskiSzymon/unreachable_sniper` (gałąź `claude/epic-darwin-evl0s1`, commit `1ddb11b`), żeby nowy program mógł
korzystać z gotowych, sprawdzonych na żywo modułów Snipera (sesja Vinted przez proxy, ekstrakcja ofert, ocena AI).
Szczegóły Snipera: **`sniper/CONTEXT.md`** (pełny kontekst tamtego projektu – czytaj przy pracy z modułami `sniper/`).

Rozmawiamy po polsku. Użytkownik: Windows, Python 3.12, folder roboczy Snipera `C:\Users\Szymek\unreachable_sniper`
(ten projekt sklonuje obok, np. `C:\Users\Szymek\category_analyzer`). **Claude nie ma dostępu do vinted.pl** ze swojego
środowiska – wszystko, co dotyka Vinted, uruchamia użytkownik i wkleja log / pliki. Zmiany testujemy atrapami
(httpx MockTransport, fixtures z prawdziwych odpowiedzi), dopiero potem wypychamy.

## Cel

Pełny research rynku jednej kategorii Vinted (start: laptopy, `catalog_id` 3580):

1. **Zebrać całą kategorię**, a nie tylko pierwsze kilkaset/tysiąc wyników jednego wyszukiwania – dzielenie wyszukiwania
   na wąskie zakresy (cena, ewentualnie marka/stan), aż każdy mieści się w limicie wyników.
2. **Zapisać wszystko lokalnie** (SQLite + skompresowany surowy JSON), z jawnym rozróżnieniem „wartość” / „brak danych”.
3. **Śledzić zmiany w czasie**: zmiana ceny, rezerwacja, **sprzedaż** (po jakiej cenie wystawienia i po jakim czasie),
   usunięcie.
4. **Wyciągnąć parametry** (CPU, GPU, RAM, dysk, ekran, stan) – regułami, AI tylko jako uzupełnienie.
5. **Analiza**: mediany cen sprzedaży i czas sprzedaży per konfiguracja → raporty; duży model językowy dostaje
   zestawienia (nie surowe miliony wierszy).
6. **Później: połączenie ze Sniperem** – Sniper dopisuje nowe oferty do tej samej bazy, a jego ocena AI korzysta
   z prawdziwych cen rynkowych zamiast ręcznych progów z `sniper/guidelines.md`.

Pełna architektura, schemat bazy, etapy i kryteria ukończenia: **`ARCHITEKTURA.md`**.

## Najważniejsze zasady (ustalone z użytkownikiem)

* **Oszczędność transferu proxy bez utraty danych**: klucz oferty = **ID Vinted** (przychodzi za darmo w katalogu).
  Szczegóły oferty (~15 KB) pobieramy **raz** na ofertę; potem tylko tanie przejścia katalogu (~0,4 KB/ofertę).
  Zdjęć NIE pobieramy hurtowo (to byłby największy koszt) – zapisujemy URL-e; miniatura + perceptual hash tylko do
  wykrywania ponownie wystawionych ofert (etap późniejszy). Pomysł użytkownika „hash zdjęcia jako klucz” omówiony:
  do deduplikacji wystarcza ID (za darmo), hash zdjęcia ma sens do wykrywania ponownych wystawień.
* **AI**: cache po hashu treści (tytuł + opis) – ta sama treść = brak drugiego wywołania; masowo tryb wsadowy (batch API,
  ~50% taniej); reguły (regex) przed AI.
* **Parametry zapytań do Vinted tylko na podstawie realnego ruchu przeglądarki (cURL z F12) albo testu u użytkownika –
  bez zgadywania endpointów** (zasada przeniesiona ze Snipera).
* **Tempo**: pełne przejście katalogu rozłożone w czasie, losowe przerwy; budżet na proxy nie jest problemem, problemem
  jest zbyt agresywne tempo.
* **RODO**: nazw/ID sprzedawców nie zapisujemy (do analizy cen niepotrzebne) – najwyżej hash, jeśli trzeba liczyć
  „ofert na sprzedawcę”.
* **Cena „sprzedaży” = ostatnia cena wystawienia** (Vinted ma „Zaproponuj cenę” – faktyczna cena transakcji bywa niższa
  i nie jest widoczna). W raportach traktować jako górną granicę.
* Dane (`data/`) i `.env` nigdy w repo. Nie commitować sekretów.

## Stan prac (2026-10-11)

* **Zrobione (`analyzer/`)**: `config.py` (ANALYZER_*), `db.py` (schemat z ARCHITEKTURA.md + `photo_ts`,
  `last_run_id`, `missed_runs`, partycje `active/oversize/done_run_id`; migracje `PRAGMA user_version`, WAL),
  `rawstore.py` (zstd albo zlib), `catalog.py` (zapytanie = `sniper.config.get_catalog_params`, parser odporny na brak
  pól, sprzedawca wycięty z `raw`, hash sprzedawcy tylko z `ANALYZER_SELLER_SALT`), `partition.py` (podział po
  medianie cen, wspólne granice sąsiednich partycji), `crawler.py` (planowanie w trakcie crawlowania: strona 1 podaje
  `total_entries` → za duża partycja dzielona; bez `total_entries` – przepełnienie = pełna ostatnia dozwolona strona;
  wznawianie przerwanego przejścia; 429 → przerwa), `diff.py` (migawka: `missed_runs`, `gone_pending`; oferty
  w partycjach oversize pomijane), `probe.py` (etap 0), CLI `probe | crawl | status`.
* **Testy**: `analyzer/tests` – 17 testów (w tym probe na atrapie HTTP), syntetyczny rynek (`tests/fakes.py`): pełne pokrycie z i bez
  `pagination`, z `price_to` włącznie i wyłącznie, ponowne przejście (zmiana ceny, rezerwacja, zniknięcie →
  `gone_pending` po 2 przejściach, powrót), cena z liczbą ofert > limit (oversize), wznawianie po błędach.
  Atrapa 50 tys. ofert: wszystkie zebrane, 653 zapytania (minimum 521), drugie przejście 575.
* **Założenia do potwierdzenia probe** (domyślne wartości w kodzie): limit 960 wyników (`ANALYZER_MAX_RESULTS`),
  pola pozycji katalogu (`brand_title`, `status`, `is_reserved`, `favourite_count`, `total_item_price`, `photo`),
  `pagination.total_entries`, granice cen. Sortowanie `newest_first` (jedyne sprawdzone).
* **Następne**: fixtures z probe → poprawki parsera/limitu → pierwsze pełne `crawl` u użytkownika → etap 2
  (`resolver.py`, `details.py` – resolver potrzebuje odpowiedzi sidebar dla USUNIĘTEJ oferty: `probe --item ID`).

## Za co wziąć się najpierw (kolejność dla nowego czatu)

0. **Przed pisaniem crawlera – dane od użytkownika** (bez nich nie zgadujemy):
   * cURL z F12 zapytania katalogu `api.vinted.pl/svc-catalogue/items` (laptopy, sortowanie, zakres cen) **z odpowiedzią**
     (Response) – BEZ nagłówków `cookie`/`authorization`/`x-csrf-token`. Szukamy: czy jest `pagination`
     (`total_entries`, `total_pages`, `per_page`), jaki jest limit stron/wyników, jakie pola ma pozycja katalogu
     (cena, waluta, marka, stan, rozmiar, `photo`, data utworzenia/podbicia?, `is_reserved`?, `item_closing_action`?).
   * Co zwraca strona za limitem (np. `page=50`, `page=100`) – pusta lista, błąd, czy powtórka.
   * Odpowiedź `details/sidebar` dla oferty **usuniętej** (sprzedana jest w `sniper/tests/fixtures.json` jako
     `sidebar_sold`, aktywna jako `sidebar_active`).
   Z tych odpowiedzi zrobić fixtures (`analyzer/tests/fixtures_catalog.json`).
1. **Etap 1 – baza + crawler katalogu z podziałem cen** (`analyzer/db.py`, `partition.py`, `crawler.py`), reużywając
   `sniper.session.VintedSession` i `sniper.config` (proxy, nagłówki katalogu). Kryterium: pełne przejście kategorii
   zapisane w SQLite, liczba unikalnych ID ≈ suma `total_entries` partycji.
2. **Etap 2 – migawki i rozpoznawanie sprzedaży** (`diff.py`, `resolver.py`): oferta zniknęła z katalogu → jedno
   zapytanie o szczegóły → sprzedana / usunięta / ukryta, czas od pierwszego wystąpienia.
3. **Etap 3 – parametry** (`extract.py`): regex na tytuł/opis (CPU, GPU, RAM, SSD, ekran), AI wsadowo dla reszty, cache.
4. **Etap 4 – analiza i raporty** (`stats.py`, `report.py`): mediany, rozkłady czasu sprzedaży, eksport CSV/HTML.
5. **Etap 5 – integracja ze Sniperem** (patrz `ARCHITEKTURA.md`, sekcja „Integracja ze Sniperem”).

## Uruchomienie

```bash
pip install -r sniper/requirements.txt          # te same biblioteki (+ opcjonalnie: pip install zstandard)
cp sniper/.env.example sniper/.env              # proxy IPRoyal itd. (ten sam .env co w Sniperze, sekcja ANALYZER_*)
python -m analyzer probe --catalog 3580 [--item ID_USUNIETEJ]   # etap 0 -> data/probe/<czas>/
python -m analyzer crawl --catalog 3580         # pełne przejście kategorii -> data/analyzer.db (wznawia przerwane)
python -m analyzer status                       # podsumowanie bazy
python -m pytest analyzer/tests sniper/tests    # testy bez sieci
# jeszcze nie istnieją: resolve (etap 2), extract (etap 3), report (etap 4)
```

## Moduły Snipera do ponownego użycia (bez zmian w ich zachowaniu)

| Moduł | Po co analizatorowi |
|---|---|
| `sniper/session.py` (`VintedSession`) | `httpx` za proxy IPRoyal, odświeżanie sesji Playwrightem przy 401/403, `get_json()` z ponowieniami, licznik transferu. |
| `sniper/proxy_relay.py` | Przekaźnik proxy dla Chromium (logowanie do proxy przy HTTPS). |
| `sniper/config.py` | `build_proxy_url()`, `CATALOG_HEADERS` / `BASE_HEADERS`, `get_catalog_params()` – parametry katalogu sprawdzone na żywo. |
| `sniper/extractor.py` | Parsowanie `details/sidebar` + `shipping_details` → `Offer` (opis, zdjęcia, wysyłka, suma). |
| `sniper/traffic.py` | Liczenie bajtów przez proxy (budżet transferu). |
| `sniper/evaluator.py` | Backendy AI (Gemini / Anthropic) – do ekstrakcji parametrów i analiz. |

Moduły konta / auto-zakupu (`account_session.py`, `buyer.py`, `autobuy.py`) analizatora nie dotyczą. Sniper rozwija się
dalej w `unreachable_sniper`; zmiany w `sniper/` tutaj tylko, gdy analizator ich potrzebuje (i warto je oddać tam).

## Preferencje użytkownika

* Odpowiedzi i komentarze w kodzie po polsku; konkretnie, z wynikami testów.
* Zmiany parametrów zapytań do Vinted tylko na podstawie realnego ruchu przeglądarki (cURL z F12) albo testu
  u użytkownika – bez zgadywania endpointów.
* Nie commitować sekretów (hasła, ciastka, tokeny, `.env`) ani danych (`data/`).
* Użytkownik ma duży budżet na proxy i ~500 GB miejsca (może dokupić SSD 1 TB), ale chce oszczędności transferu
  bez utraty danych.
