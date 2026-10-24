# Category Analyzer – kontekst projektu (dla nowej rozmowy z Claude)

Stan na 2026-10-11. **Etap 0 zrobiony u użytkownika (probe), etap 1 (crawler) i resolver z etapu 2 napisane
i przetestowane na atrapie – czeka na pierwsze pełne `crawl` u użytkownika.** To repo jest kopią
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
* **Testy**: `analyzer/tests` – 81 testów (w tym klasyfikacja kategorii mieszanych (41 tytułów), migracja v7, dwie kategorie w jednej bazie, próg ceny per kategoria, kraj sprzedawcy, dryf kursów, details, cena minimalna, kontrola pokrycia, resolver na prawdziwych odpowiedziach, probe na atrapie HTTP i parser na prawdziwej pozycji katalogu), syntetyczny rynek (`tests/fakes.py`): pełne pokrycie z i bez
  `pagination`, z `price_to` włącznie i wyłącznie, ponowne przejście (zmiana ceny, rezerwacja, zniknięcie →
  `gone_pending` po 2 przejściach, powrót), cena z liczbą ofert > limit (oversize), wznawianie po błędach.
  Atrapa 50 tys. ofert: wszystkie zebrane, 653 zapytania (minimum 521), drugie przejście 575.
* **Probe u użytkownika 2026-10-11 (laptopy 3580)**: `pagination` jest: `current_page, per_page, time,
  total_entries, total_pages`; **limit = 960 wyników / 10 stron po 96** (`total_entries` jest UCIĘTE do 960 –
  nie mówi, ile ofert jest naprawdę; `page=20` → HTTP 400). Użytkownik potwierdził w przeglądarce: 10 stron.
  **`price_from` i `price_to` są włącznie** (zapytanie [665.98; 665.98] = 32 oferty z dokładnie tą ceną).
  Pola pozycji: `content_source, favourite_count, id, is_favourite, item_box, photo, photos, price, promoted,
  search_tracking_params, service_fee, show_1st_time_seller_discount, title, total_item_price, url, user,
  view_count` – brak `brand_title`, `status`, `is_reserved` (rezerwacji z katalogu NIE znamy → `is_reserved` NULL).
  **Marka / model / stan z `item_box`**: `accessibility_label` = „<tytuł>, Marka: X, Model: Y, Stan: Z, <cena> zł,
  <cena z opłatą> zł” (Model bywa pominięty), `second_line` = stan, `first_line` = marka + model → `listings.brand`,
  `model` (migracja v3), `status_label`. `photo.high_resolution` w katalogu NIE ma `timestamp` (→ `photo_ts` NULL).
  `service_fee` + `total_item_price` są (dict amount/currency_code). **Filtr ceny nie pokrywa się co do grosza
  z `price`**: price_to=666.98 zwróciło oferty 667.76–667.88 zł (prawdopodobnie przeliczenia walut) → zapytania
  poszerzone o `ANALYZER_PRICE_MARGIN` (1 zł) z obu stron, duplikaty usuwa ID. Transfer: strona 96 ofert ≈ 26 KB
  (≈ 0,27 KB/ofertę). Sidebar sprzedanej: karta pamięci 9238023547 i laptop 10295873538 (Razer Blade Pro) – HTTP 200, `code` 0, te same klucze co `sidebar_sold` (endpoint wspólny dla kategorii). Drugi probe: [414.59; 415.59] dał 21 ofert z `price` poza zakresem – filtr działa na jakiejś wewnętrznej cenie (waluta sprzedawcy?), ale to NIE gubi ofert: każda oferta trafia do tej partycji, w której leży jej cena „filtrowa”, a partycje pokrywają cały zakres bez dziur. **Usunięta oferta** (długopis 10327664119, usunięty przez użytkownika): sidebar → **HTTP 404, `code` 104**
  (klucze `code, message, message_code`; strona www: „Page not found”). favourite_count/view_count → ostatnia wartość
  w `listings` (migracja v2). Sortowanie `newest_first` (jedyne sprawdzone).
* **Etap 2 – `resolver.py` (zrobione, test na atrapie)**: `python -m analyzer resolve` – dla `gone_pending` jedno
  zapytanie sidebar: 200 + `item_closing_action=sold` → `sold` (`sold_price` = cena z sidebara sprzedanej, inaczej
  ostatnia z katalogu; `days_to_sell` = od `COALESCE(created_at, first_seen)` do `last_seen`), 404 + code 104 →
  `deleted`, inne zamknięcie → `closed`, `is_reserved` → `reserved`, `is_hidden`/`is_draft` → `hidden`, aktywna →
  `unlisted` (ponownie po `ANALYZER_RECHECK_DAYS`=3, wraca do `active`, gdy znów w katalogu); nieznana odpowiedź →
  zostaje `gone_pending`. Surowa odpowiedź w `raw` (kind `resolve`, dane sprzedawcy wycięte). Uwaga do statystyk:
  oferty z PIERWSZEGO przejścia mają `first_seen` ≠ data wystawienia (zaniżony czas sprzedaży) – w raportach brać
  tylko oferty, które pojawiły się po pierwszym przejściu. `details.py` (opis raz na ofertę) – jeszcze nie.
* **Pierwsze pełne przejście u użytkownika (2026-10-11, laptopy 3580)**: 42 min, 535 zapytań, 20,1 MB
  (śr. 38,6 KB/stronę, wysłane nagłówki 1,6 MB), **34 159 unikalnych ofert**, 75 partycji (oversize 0), jeden
  `SSLError bad record mac` (proxy) – ponowione samo. Suma `total_entries` partycji 41 244 > unikalne: duplikaty na
  wspólnych granicach + zapas 1 zł przy cenach skupionych na okrągłych kwotach (atrapa z takim rozkładem: to samo,
  0 zgubionych) → `ANALYZER_PRICE_MARGIN` domyślnie 0; `status` pokazuje kontrolę pokrycia per partycja (oferty
  w bazie z ceną w zakresie ±1 zł vs `total_entries`). Rozkład: 0–2500 zł gęsto (partycje po kilka–kilkadziesiąt zł),
  >20 000 zł 22 oferty. Kolejne przejścia bez dzielenia ≈ 470 zapytań.
* **Cena minimalna 700 zł** (decyzja użytkownika 2026-10-11: laptopy < 700 zł to zwykle bezużyteczne starocie):
  `ANALYZER_PRICE_MIN=700` domyślnie. Istniejący plan partycji jest dopasowywany przy każdym `crawl`
  (`Crawler._apply_price_min`: partycje poniżej wyłączone, przecinające próg przycięte, przy obniżeniu progu dochodzi
  partycja [nowy próg, najniższa]). Oferty z ostatnią ceną < progu → stan `below_min` (nie idą do resolvera);
  resolver: aktywna, ale potaniała poniżej progu → `below_min`; oferta znów ≥ progu w katalogu → `active`.
* **Tryb `watch`** (`python -m analyzer watch`): bez końca crawl + resolve, przerwa `ANALYZER_WATCH_HOURS` (10–14 h).
* **Drugie przejście (od 700 zł, 2026-10-11)**: 17 min, 209 zapytań, 7,7 MB, 17 205 aktywnych ≥ 700 zł
  (17 018 → `below_min`), nowe 64, zmienione 14; kontrola pokrycia: brakuje ~24 (najwięcej 1699–1820 zł: 17 –
  pewnie oferty zagraniczne z ceną filtra ≠ `price`).
* **`details.py` (zrobione)**: `python -m analyzer details [--limit N]` i w `watch` między przejściami (do startu
  następnego): sidebar RAZ na ofertę (najnowsze ID najpierw), tabela `details` (migracja v4: opis, atrybuty JSON,
  „Dodane” → `created_est` i `listings.created_at`, `business`, `seller_currency`, `photo_count`, `is_localized`),
  `listings.details_at` + `content_hash`, surowy sidebar w `raw` (kind `sidebar`, dane sprzedawcy wycięte). Sprzedana /
  usunięta przy okazji → stan przez `resolver.apply_result`; resolver zapisuje szczegóły sprzedanej, jeśli ich nie
  było. Przerwa `ANALYZER_DETAILS_DELAY_S` 2–5 s → zaległość ~17 tys. ≈ 17 h, potem tylko nowe (~kilkaset/dobę).
  „Dodane” w sidebar_active = „tygodnia”, zrzut: „3 mies.”, „3 min.” (⚠ nie wiadomo, czy podbicie zmienia datę).
* **`ATRYBUTY.md`**: segmenty kupujących (gaming, MacBook, biznesowe, ultrabooki, 2w1/dotykowe, stacje robocze,
  budżetowe, Chromebooki, uszkodzone, retro) + parametry wspólne i klucze konfiguracji do grupowania cen;
  sekcja 1a – słownik GPU (prośba użytkownika: profesjonalne NVIDIA RTX A500–A5500 / Ada / Quadro z Delli Precision,
  AMD Radeon RX / Radeon Pro WX/W / Pro 5xxxM z MacBooków, iGPU 680M/780M/890M, Intel Arc) – pro liczone osobno.
  **2026-10-12: obowiązuje wersja użytkownika** (źródła wartości z wagami, zasady „nie zgaduj” dla blokad/usterek/
  baterii/gwarancji, tabela 1b numer modelu → GPU z mocą zasilacza, flagi informacyjne/czerwone/okazji, sekcja 5 =
  powiązanie z `sniper/guidelines.md`) z poprawkami Claude (oznaczone): format AI = obiekty {value, source, evidence}
  + schemat JSON, jedna skala wag, skala `visual_grade` A–D, ⚠ dla pól niewidzianych w danych, kraj sprzedawcy.
* **Kraj sprzedawcy (migracja v6)**: `listings.seller_country` z `user.country_iso_code|country_code` pozycji
  katalogu; `strip_personal` / `probe.redact` zostawiają tylko pola kraju (login/ID wycięte). ⚠ niepotwierdzone, czy
  svc-catalogue podaje kraj w `user` – sprawdzi `diag` (linia „Kraj sprzedawcy”) po pierwszym przejściu.
* **Przejścia #3 i #4 + pierwszy resolve/details (2026-10-11/12)**: #3: nowe 232, zmienione 150, zniknięte 16
  (8 deleted, 8 unlisted). #4: nowe 17, **zmienione 11 810** (!), zniknięte 199 → resolve: deleted 107, unlisted 50,
  below_min 19, hidden 19, reserved 3, **sold 0** (podejrzane – może sprzedane zostają jakiś czas w katalogu albo
  znikają jako 404; do obserwacji). Po #4 kontrola pokrycia: brak 473 (798–831 zł: Vinted 816, w bazie 563).
  Hipoteza: dryf kursów walut (oferty zagraniczne – w resolve dużo tytułów CZ/LT/HU/SE) albo zmiana opłaty →
  zmiana `price`/`total_price` u wielu ofert. **`diag` (2026-10-12) potwierdził dryf kursów**: 11 810 zmian = cena
  i cena z opłatą naraz, 11 789 < 0,5%, waluty sprzedawców RON 1912, EUR 1550, HUF 815, CZK 689, SEK 472, DKK 382
  (PLN 7; reszta bez details); wiele ofert ma identyczne ceny w zł (np. 706.5 RON, 710.38 EUR = okrągła cena
  w walucie sprzedawcy). Poprawka (migracja v5): `listings.price_now/total_now` aktualizowane co przejście,
  `observations` tylko przy `db.real_change` (PLN: każda zmiana; zagraniczne: ≥ 1%; przed details: ułamkowa cena =
  zagraniczna), kontrola pokrycia z tolerancją max(1 zł, 1,5%) na `price_now`. Stare wiersze dryfu z #4 zostały
  w `observations` (statystyki obniżek mają je filtrować `real_change`). Użytkownik znalazł kursy, z których korzysta
  front Vinted: `api.exchangerate-api.com/v4/latest/USD` (Referer vinted.pl) – na razie niepotrzebne (cena w walucie
  sprzedawcy jest w sidebar `conversion.seller_price`). Details: ~200 ofert / 13 min (~4 s/ofertę), ReadTimeout co kilkaset (ponawiane w kolejnym cyklu).
* **Cztery kategorie (2026-10-12, prośba użytkownika)**: laptopy 3580, **telefony 3661, konsole 3025, tablety 3728**
  (catalog_id z cURL użytkownika – parametry jak dla laptopów; przeglądarka wysyła dodatkowo puste
  `attribute_ids[color|internal_memory_capacity|sim_lock|video_game_platform]`, my ich nie wysyłamy – działało dla
  laptopów). `ANALYZER_CATALOGS` domyślnie wszystkie 4; `watch` bez `--catalog`. Cena minimalna per kategoria:
  `AnalyzerConfig.price_min_for()` – `ANALYZER_PRICE_MIN_<id>` > `ANALYZER_PRICE_MIN` > domyślne (laptopy 700,
  pozostałe 300 – propozycja Claude). Logi/status z nazwą kategorii (`config.catalog_label`).
  Dokumentacja ekstrakcji: **`EKSTRAKCJA.md`** (wspólne: 3 źródła – platforma / oferta / tabela `models` raz na
  model; format obiektowy; wspólny rdzeń pól; jedna skala `condition_grade`; czego nie zbieramy) +
  `ATRYBUTY_TELEFONY.md`, `ATRYBUTY_KONSOLE.md`, `ATRYBUTY_TABLETY.md` (wersje użytkownika z poprawkami:
  [P] = z platformy, [–] = nie zbieramy, ⚠ = niewidziane w danych, segmenty do statystyk).
* **Kategoria RAM (2026-10-14, prośba użytkownika)** – do wyceny konfiguracji laptopów i strategii „rozbiórki”
  (ATRYBUTY.md §6: z = x + y − zakup − c). **Czeka na cURL kategorii od użytkownika** (catalog_id nieznany; DIMM vs
  SO-DIMM). Propozycja: próg 100 zł, bez details każdej oferty (parametry w tytule).
  **Kategoria dysków (2026-10-14)** – rozbiórka dysków (np. 2 TB NVMe → 512 GB): czeka na cURL; pola: forma
  (M.2 2280/2242/2230, 2,5" SATA), interfejs (NVMe PCIe 3/4/5, SATA), pojemność, zużycie (TBW / health %).
  Konsole: tabela części do wyjęcia w ATRYBUTY_KONSOLE.md §16.
* **Kategorie mieszane + gry (2026-10-14, cURL użytkownika)**: 3582 „Części i podzespoły komputerowe”, 3583 „Puste
  nośniki”, 3584 „Akcesoria komputerowe” (wszędzie mieszanka: karty graficzne, RAM, dyski, ale też płyty główne,
  zasilacze, wentylatory, klawiatury, myszki, pendrive'y, płyty CD, karty SIM, komputery stacjonarne, a nawet laptopy
  i konsole). Zbieramy tylko: `gpu`, `ram`, `storage` (SSD/NVMe, także dyski do konsol; bez HDD) + laptop/konsola/
  telefon/tablet z złej kategorii → istniejące kategorie. **Gry (3026) odpuszczone** (użytkownik 2026-10-14: pole
  platforma wypełniane bez ładu; wrócimy kiedy indziej) – gry z kategorii mieszanych → `ignored`.
  **Migracja v7**: `listings.category` (NASZA kategoria przedmiotu, niezależna od catalog_id Vinted),
  `category_src` (catalog / rule / ai / manual), `category_rule`. `analyzer/classify.py`: reguły na tytuł + marka/model
  z `item_box` (bez sieci): zwroty „do laptopa / na PS5” usuwane → akcesoria i części spoza zakresu (STRONG_JUNK, HDD)
  → komputery stacjonarne → urządzenia (laptop, konsola – tylko z wersją/pojemnością/„konsola”, sama platforma =
  gra) → gpu → ram → storage → gra (→ ignored) → słabe śmieci → `unknown`. Stany: `ignored` (sam wiersz, bez obserwacji/raw,
  nie idzie do resolvera/details), `unclassified` (unknown – bez kosztu proxy), `below_min` wg progu NASZEJ kategorii
  (`AnalyzerConfig.category_min`: laptop/phone/console/tablet z progów katalogów; gpu 150, ram 100, storage
  100 – `ANALYZER_PRICE_MIN_GPU|RAM|STORAGE`); kategorie mieszane crawlowane od 100 zł.
  `classify-report` (udział nasze / nierozpoznane / odrzucone + przykłady) i `reclassify` (po poprawce reguł, bez
  sieci). Details: `ANALYZER_DETAILS_CATEGORIES` (domyślnie wszystkie nasze kategorie; dawne
  `ANALYZER_DETAILS_CATALOGS` z numerami nadal działa). **AI do nierozpoznanych – NIE (decyzja 2026-10-15)**
  po pierwszym `classify-report` (3582: 31,8 tys. ofert, nasze 42%, nierozpoznane 32%; 3583/3584: nierozpoznane
  ~60%): nierozpoznane to prawie same części spoza zakresu po obcemu (procesory, płyty „alaplap/zakladna doska”,
  zasilacze „sursa/tápegység”, chłodzenie, HDD „pevný/tvrdi disk”) → zamiast AI reguły: słowa w ~10 językach,
  numery modeli (Ryzen/Intel desktop, chipsety płyt, Samsung MZ…, Legend 720, FireCuda), a wybór reguły =
  słowo, które pada w tytule NAJWCZEŚNIEJ („Laptop Dell + zasilacz” = laptop, „Zasilacz Dell” = część); procesor
  laptopowy (H/HS/HX/U) = laptop. AI nie oszczędza proxy (crawl i tak pobiera każdą stronę), a `unclassified` ma
  historię cen w `observations` – po miesiącu można je sklasyfikować offline (reguły / AI wsadowo na samych
  tytułach, grosze), `reclassify` przywraca stan `active`, a zniknięte pójdą przez resolver (sidebar sprzedanej
  działa i później).
* **RAM ze zdjęcia przez AI (2026-10-15, prośba użytkownika)**: gdy tytuł z kategorii mieszanych pasuje do RAM-u
  i do innej kategorii (`classify.needs_photo_check`: „Laptop 16GB RAM”, „Płyta + procesor + RAM”), o kategorii
  decyduje AI ze zdjęcia głównego (`analyzer/ai_classify.py`), a nie kolejność słów. Migracja v8:
  `listings.category_check` (pending / done / failed); do czasu odpowiedzi kategoria z reguł. Zdjęcie jako URL –
  pobiera dostawca AI, bez proxy. Dostawca/klucz z `SNIPER_AI_*`, model `ANALYZER_AI_MODEL` (domyślnie
  gemini-3.8-flash / claude-haiku-5-5), cache `ai_cache` (task `photo_category_v1`), wynik `category_src='ai'`.
  W `watch` po przejściu katalogów (limit `ANALYZER_AI_CLASSIFY_LIMIT`=500/cykl); ręcznie `classify-ai
  [--limit N] [--retry-failed]`; `reclassify` oznacza konflikty w starych ofertach.
* **⚠ SPRZEDAŻ NIE JEST ROZPOZNAWANA (2026-10-24, po 2 tyg. `watch`)** – `status`: 0 `sold`, 0 `closed` przy ~14 tys.
  `deleted`, ~9 tys. `unlisted`, ~1,7 tys. `hidden`. Ustalenia z `check` u użytkownika:
  - **sprzedana myszka 9011596531** (w przeglądarce „Sprzedane”, „Dodane 4 mies.”): stary sidebar
    `www.vinted.pl/api/v2/items/{id}/details/sidebar` → **HTTP 404, code 104** = to samo co usunięta. 11.10 sprzedany
    laptop dawał 200 + `item_closing_action=sold` → Vinted zmienił zachowanie (użytkownik: „kilka dni temu”; strona
    pokazuje sprzedane, więc bierze status z innego źródła – NIE ustalone, czeka na cURL z F12; trop użytkownika
    `api.vinted.pl/item-details/more-items/{id}?content_source=similar_items&screen=item` wygląda raczej na „podobne
    oferty”, nie status – nie używać bez odpowiedzi z przeglądarki). Strona oferty może być renderowana na serwerze
    (HTML) – wtedy status w HTML, a strona waży dużo więcej niż sidebar (koszt proxy).
  - **aktywny MacBook 10292094832**: `deleted` od 2026-10-12, a `last_seen` 2026-10-24, `missed_runs` 0 – czyli był
    w katalogu cały czas po oznaczeniu. Sidebar dziś: 200, aktywna. **Błąd A:** `deleted` / `sold` / `closed` nie są
    w `db.REVIVABLE` → oferta widziana znów w katalogu zostaje `deleted` na zawsze. **Błąd B:** 404/104 nie znaczy
    już „usunięta” (sprzedane też; możliwe też chwilowe 404 dla aktywnych – MacBook 12.10 dostał 404 i/lub zniknął na
    2 przejścia, a był aktywny). Wniosek: `deleted` = mieszanka usuniętych, sprzedanych i fałszywych.
  - Do zrobienia (po decyzji użytkownika): (1) oferta znów w katalogu → wraca do `active` (+ licznik „fałszywych
    zniknięć”), (2) 404/104 → stan `gone_404` (nie wiadomo: usunięta albo sprzedana) z ponownym sprawdzeniem,
    (3) nowe źródło statusu sprzedaży z F12, (4) jednorazowe ponowne sprawdzenie wszystkich `deleted` nowym źródłem
    (dane – ceny, daty, opisy – są w bazie; sprzedane oferty Vinted pokazuje miesiącami).
* **Źródło statusu sprzedaży – strona HTML oferty (analiza 2026-10-24, pliki od użytkownika, incognito)**:
  `api.vinted.pl/item-details/more-items/{id}` = tylko „Podobne rzeczy” / „Przedmioty użytkownika” (BEZ statusu –
  odpada). Strona `www.vinted.pl/items/{id}` (Next.js, ~1,9 MB, gzip ~365 KB) zawiera osadzony obiekt `type: sidebar`
  z NOWYM zestawem pluginów: sprzedana → plugin **`buyer_item_status`** `{"theme": "SUCCESS", "title": "Sprzedane"}`,
  `can_buy: false`, brak `buy`/`make_offer`/`ask_seller`; aktywna → brak `buyer_item_status`, `can_buy: true`, są
  `buy`, `make_offer`, `ask_seller`. Starego pluginu `item_status` (`item_closing_action`) w stronie nie ma wcale.
  Osadzony JSON jest daleko (~78–97% pliku), ALE wyrenderowany HTML ma status wcześnie: pierwsza karta w
  `<aside id="sidebar">` (~290–315 KB, gzip ~30 KB) – sprzedana: `web_ui__Cell__success` → „Sprzedane”, aktywna: od
  razu `ymptpG_box--item-details`, dalej `data-testid="item-buy-button"` (~325 KB). Plan: pobierać stronę
  strumieniowo i przerwać po karcie sidebara → ~30–35 KB transferu na ofertę (zamiast ~365 KB). ⚠ Niesprawdzone:
  strona usuniętej (pewnie 404 „Page not found”), zarezerwowanej / ukrytej (inny `theme`/`title`?), czy Datadome
  wpuszcza nasze zapytania HTML przez proxy, czy klasy CSS (`ymptpG_…`) są stałe (hash – mogą się zmieniać;
  `web_ui__Cell__success` i `aside id="sidebar"` wyglądają na stałe).
* **Obserwacja użytkownika (2026-10-24, przeglądarka)**: `www.vinted.pl/api/v2/items/{id}/details/sidebar` zwraca
  dane dla **aktywnych** (także nowych) ofert, ale **NIE dla sprzedanych** (404/104, np. myszka 9011596531).
  Natomiast `www.vinted.pl/api/v2/items/{id}/services` odpowiada **zarówno dla aktywnych, jak i sprzedanych**
  (np. 9011596531). ⚠ Zawartość odpowiedzi `/services` jeszcze nieznana – czy rozróżnia sprzedaną / aktywną / usuniętą
  (i ile waży) – czeka na Response z F12 dla: sprzedanej, aktywnej i naprawdę usuniętej oferty. Jeśli rozróżnia,
  to jest tańsze źródło statusu niż strona HTML (~30 KB przy przerwanym pobieraniu).
* **`/services` – zawartość (Response od użytkownika 2026-10-24)**: sprzedana myszka i aktywny MacBook mają TĘ SAMĄ
  budowę, **bez pola statusu**: `services.buyer_protection` (opłata 5% + 2,90 zł), `services.shipping` (cena wysyłki,
  także w walucie sprzedawcy + `exchange_rate`), `original_asking_amount` (cena w zł), `seller_original_asking_amount`
  (cena w walucie sprzedawcy, np. 55.0 RON, 2299.0 DKK), `total_amount`. ~1,3 KB. Sama w sobie NIE rozróżnia
  sprzedanej od aktywnej. **Pomysł (do potwierdzenia):** status z pary zapytań – sidebar 200 → aktywna / zarezerwowana /
  ukryta (stary `item_status`); sidebar 404/104 + `/services` 200 → oferta istnieje, ale sidebar jej nie pokazuje →
  **sprzedana** (myszka); sidebar 404/104 + `/services` 404 → **usunięta**. Do tego `/services` daje cenę w chwili
  sprawdzenia w zł i w walucie sprzedawcy (cena sprzedaży bez kursowego dryfu). **Potwierdzone (użytkownik
  2026-10-24): naprawdę usunięta oferta → `/services` = `{"code":104,"message":"Zawartość nieodnaleziona",
  "message_code":"not_found"}`** (jak sidebar usuniętej). ⚠ Jeszcze potrzebne: `/services` i sidebar dla ukrytej i zarezerwowanej (czy sidebar dla nich też daje 404 –
  wtedy pomyliłyby się ze sprzedanymi), oraz walidacja na próbce: kilkadziesiąt ofert sprawdzonych parą zapytań
  i stroną HTML (`buyer_item_status`) – zgodność > ~98%, inaczej status ze strony HTML.
* **Naprawa rozpoznawania sprzedaży (2026-10-24, zrobione, test na atrapie z prawdziwymi odpowiedziami)**:
  `resolver.resolve_item`: najpierw `/services` (404/104 → `deleted`, 1 zapytanie), potem sidebar (404/104 →
  `sold`, 200 → jak dawniej; `unlisted` przy `missed_runs = 0` → `active`). Używają tego resolve (watch), details
  (sidebar 404 → `/services`), check i nowe **`python -m analyzer recheck [--states deleted] [--limit N] [--delay 2-4]
  [--again]`** – jednorazowa naprawa starych `deleted` (najświeższe zniknięcia najpierw, wznawialne po
  `services_at`). Migracja v9: `listings.services_at`, `seller_price`, `seller_currency` (z `/services`);
  `sold_price` = `original_asking_amount` z `/services`. Surowe `/services` w `raw` (kind `services`). **Błąd A
  naprawiony**: `deleted`/`sold`/`closed` w `REVIVABLE` – oferta znów w katalogu wraca do `active` (sold_price
  kasowany, log `[DB] … znów w katalogu`). Użytkownik: rezerwacje na Vinted przestały działać.
  Następny krok (decyzja użytkownika 2026-10-24): **opisy sprzedanych bez details ze strony HTML** – wyrenderowany
  `<aside id="sidebar">` (status, atrybuty, `itemprop="description"`, „Dodane”) kończy się ~320–345 KB strony
  (gzip ~33–37 KB) → pobieranie strumieniowe przerwane na `</aside>`.
* **`html-details` (2026-10-24, zrobione, test na stronach zapisanych przez użytkownika)**: `analyzer/html_details.py`
  – sprzedane bez szczegółów: strona oferty strumieniowo, przerwane na `data-testid="item-shipping-banner"` (za nim
  nazwa sprzedawcy – nie czytamy), parser panelu (`status` „Sprzedane”, cena, `item-attributes-<kod>` → te same kody
  co atrybuty API, `itemprop="description"`, „Dodane”) → `details` (`source='html'`, migracja v10), czas sprzedaży
  przeliczany z „Dodane”. Nagłówki jak nawigacja przeglądarki (bez `x-next-app` itd.) – ⚠ do potwierdzenia na żywo
  (`html-details --limit 5`). Fixture: `analyzer/tests/fixtures_html.json` (fragment panelu, bez danych sprzedawcy).
* **`extract.py` v1 (2026-10-24, reguły, bez AI)**: tabela `features` (migracja v11: kolumny model, cpu, cpu_line, gpu,
  ram_gb, storage_gb, screen_in, refresh_hz, battery_pct, condition_grade, for_parts, locked, cracked, segment +
  `fields_json` z źródłami + `config_key`). Źródła: atrybuty formularza > tytuł > opis; pomyłki formularza (RAM
  „256 GB”, dysk „8 GB”) → `platform_field_errors`. Słowa usterek/blokad/baterii w ~10 językach. Na próbce 1050
  ofert klucz konfiguracji: laptopy 96%, telefony 94%, RAM 97%, dyski 88%, GPU 79%, tablety 75%, konsole 100%
  (platforma). `python -m analyzer extract [--again]`, `extract-report` (pokrycie pól + konfiguracje z medianą ceny
  i ceny sprzedaży); w `watch` przyrostowo po resolve. AI dla braków – później (po pierwszym raporcie).
* **Wynik `recheck` u użytkownika (2026-10-24)**: 13 841 ofert w 5,1 h, 78,6 MB (5,6 KB/ofertę): deleted 13 300
  (96%), sold 454 (3,3%), unlisted 53, active 23, hidden 2, błąd 9. Hipotezy: (1) dużo „usunięć” to usuwanie
  i ponowne wystawianie (podbicie na górę „najnowsze”) – do wykrycia przy raportach (tytuł/cena/zdjęcie/hash
  sprzedawcy); (2) część „sold” to oszustwa zdjęte przez Vinted (powtarzane „iPhone 16 Pro 512 GB” za 519 zł,
  „iPhone 15 Pro” za 900 zł) – `/services` 200 + sidebar 404, ale **strona oferty 404** (`html-details --limit 5`:
  3 z 5) → nowy stan **`blocked`** (html_details; nie liczy się do sprzedaży; w `REVIVABLE`/`GONE_STATES`).
  Poprawka: `traffic.request_bytes` nie wywraca się na zapytaniu po przekierowaniu (`/items/ID` → `/items/ID-slug`,
  httpx `RequestNotRead`).
* **`html-details` – poprawka po `--dump` (2026-10-24)**: strona przychodzi strumieniowo, panel boczny na początku to
  szkielet (`react-loading-skeleton`) – treść setki KB dalej. Pełny opis + tytuł są w `<head>` (`<meta name="description"
  content="<tytuł> - <opis>">`, ~17 KB) → pobieranie do `</head>`; bez atrybutów i „Dodane”. 200 = istnieje, 404 =
  `blocked`. Fixtures `head_sold_iphone`, `head_active_macbook`.
* **Następne**: po `recheck` u użytkownika: `html-details` (opisy sprzedanych), `extract`, pierwszy raport; potem AI
  dla braków ekstrakcji i `report` (etap 4).

## Obserwacja: oferty z innych rynków Vinted (użytkownik, 2026-10-11) – do wykorzystania w Sniperze

* Użytkownik ma drugie konto na rynku niemieckim (aplikacja po niemiecku). Wystawił tam testowo „długopis premium”
  (ID **10327664119**, BIC, Długopisy) – po to, żeby go usunąć i zobaczyć `probe --item` dla **usuniętej** oferty.
* Z polskiego konta ogłoszenie otwiera się z linku `www.vinted.pl/items/10327664119-dlugopis-premium` – cena
  przeliczona na zł (88,80 zł / 96,14 zł z opłatą, „Cena przedmiotu i wszystkie pozostałe opłaty są przeliczone na
  twoją walutę”), „Dodane 3 min.”. Vinted pytał, w jakim języku otworzyć ogłoszenie (tłumaczenie Google opisu).
* **Ale w polskim katalogu (Długopisy, `newest_first`) tej oferty nie było widać.** Niepotwierdzone, dlaczego:
  opóźnienie indeksowania? nowe konto bez opinii? oferty z DE nie trafiają do katalogu PL (albo tylko część)?
  Jednocześnie katalog PL laptopów MA oferty zagraniczne (np. fińska „Asus kannettava tietokone” za 665,98 zł =
  przeliczone EUR) – więc część zagranicznych ofert w PL jest, część nie.
* Wnioski / hipotezy do sprawdzenia:
  - **ID ofert są globalne** (ta sama numeracja ~10327… co oferty PL) → klucz bazy = ID działa dla wszystkich rynków,
    a `details/sidebar` na vinted.pl działa także dla ofert z innych krajów.
  - Katalog PL może NIE pokazywać całego rynku europejskiego → **Sniper może przeglądać też inne rynki**
    (vinted.de / .fr / .it …) i znajdować okazje, których nie widać na .pl, a kupować przez konto PL (oferta otwiera
    się z linku na .pl). ⚠ Endpoint katalogu innych rynków (np. `api.vinted.de/svc-catalogue/items`?) i warunki
    wysyłki do PL – tylko z cURL z F12 / testu u użytkownika, NIE zgadywać.
  - Ceny zagranicznych ofert w PL są przeliczane z waluty sprzedawcy – to prawdopodobnie tłumaczy, czemu filtr
    `price_from/price_to` nie pokrywa się co do grosza z `price` (filtr na cenie w walucie sprzedawcy?).
  - Przy analizie rynku: rozdzielić oferty krajowe i zagraniczne (waluta sprzedawcy z `sidebar.conversion.seller_currency`),
    bo mają inne koszty wysyłki i inną dynamikę sprzedaży.
* Do zrobienia u użytkownika: po usunięciu długopisu `python -m analyzer probe --catalog 3580 --item 10327664119`
  (odpowiedź dla usuniętej oferty → resolver), i sprawdzić, czy długopis pojawił się później w katalogu PL.

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
python -m analyzer resolve [--limit N]          # zniknięte z katalogu -> sold / deleted / unlisted
python -m analyzer details [--limit N]          # opis + atrybuty raz na ofertę
python -m analyzer watch                        # bez końca: crawl wszystkich kategorii + resolve, między przejściami details
python -m analyzer recheck                      # naprawa starych 'deleted' (/services + sidebar), ntfy na koniec
python -m analyzer html-details                 # opisy sprzedanych ze strony HTML (~35 KB/ofertę)
python -m analyzer extract && python -m analyzer extract-report   # parametry regułami + konfiguracje z cenami
# jeszcze nie istnieje: report (etap 4)
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
* **Budżet na proxy jest OGRANICZONY** (użytkownik 2026-10-13: IPRoyal drogie – zostajemy przy 4 kategoriach, bez
  szerokiego przeglądu wielu kategorii). Wcześniejsza notatka „duży budżet” nieaktualna. ~500 GB miejsca na dysku.
  Oszczędność transferu ważniejsza niż wygoda; propozycje cięć: details tylko dla zniknętych (nowe kategorie),
  rzadsze przejścia, sticky session IPRoyal. **Zrobione: `ANALYZER_DETAILS_CATALOGS`** (domyślnie `3580`) –
  szczegóły każdej oferty tylko dla laptopów; telefony/konsole/tablety: opis tylko przy zniknięciu (resolver zapisuje
  sidebar sprzedanej/ukrytej/zarezerwowanej; usunięte 404 – bez opisu). Raport IPRoyal 8–13.10: **Sniper ~110 MB/dzień**
  (`api.vinted.pl`, ~5800 skanów × ~19 KB przy `SNIPER_PER_PAGE=20`) – zalecone `SNIPER_PER_PAGE=5` (~35 MB/dzień);
  analizator: katalog laptopów ~15 MB/dzień, zaległe details ~80–90 MB/dzień (`www.vinted.pl`, ~12 KB/ofertę z TLS);
  „requests count” w IPRoyal = połączenia, nie zapytania. Sniper działa równolegle na tym samym koncie IPRoyal.
* **Serwer użytkownika** (od 2026-10-13): stary laptop i5-5200U, 4 GB RAM, SSD, Wi-Fi, `C:\Users\szymo\category_analyzer`
  (klon gałęzi `claude/focused-johnson-6ytqgt` – `main` ma tylko PR #1 z etapem 1!).
