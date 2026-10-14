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
  `ANALYZER_DETAILS_CATALOGS` z numerami nadal działa). **AI do nierozpoznanych – jeszcze nie**: decyzja po pierwszym
  `classify-report` (crawl i tak pobiera każdą stronę katalogu; klasyfikacja oszczędza tylko details/resolve
  i tokeny; nierozpoznane nic nie kosztują, dopóki są `unclassified`).
* **Następne**: `extract.py` v1 wg `ATRYBUTY.md` (reguły + raport pokrycia na prawdziwych opisach) → AI dla braków.

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
# jeszcze nie istnieją: extract (etap 3), report (etap 4)
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
