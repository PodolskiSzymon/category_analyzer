# Co wyciągamy z ofert laptopów – segmenty kupujących i parametry

> **Kategoria Vinted 3580 (laptopy).** Zasady wspólne dla wszystkich kategorii (laptopy, telefony, konsole,
> tablety): **`EKSTRAKCJA.md`** – ma pierwszeństwo. *(poprawka Claude 2026-10-12)*: stan wizualny zapisujemy we
> wspólnej skali `condition_grade` (`new_sealed`, `new_open`, `A_plus`, `A`, `B`, `C`, `D`, `unknown`); skala
> `visual_grade` A–D z sekcji 1 mapuje się: A → `A_plus`/`A`, B → `B`, C → `C`, D → `D`. Pola platformy (cena,
> polubienia, „Dodane”, firma, kraj) wypełnia baza, nie AI; parametry z wiedzy o modelu (panel, TGP, rok) – tabela
> `models` raz na model.

Cel: dla każdej oferty ustalić **segment** (kto ją kupuje) i **parametry, od których w tym segmencie zależy cena
i szybkość sprzedaży**. Raporty (etap 4) grupują ceny po „kluczu konfiguracji” właściwym dla segmentu – inaczej
mediana miesza MacBooka M1 8/256 z M1 16/512 albo RTX 4060 80 W z RTX 4060 140 W. Sniper używa tych samych pól
do policzenia maksymalnej ceny zakupu według `guidelines.md` (sekcja 5).

## 0. Źródła danych i oznaczanie pochodzenia

### 0.1. Kolejność pozyskiwania (od najtańszego)

1. **tytuł + `item_box`** – marka, model, stan; za darmo z katalogu,
2. **opis + atrybuty z `details/sidebar`** – raz na ofertę, ~6–10 KB,
3. **AI wsadowo** – tylko dla pól, których reguły nie znalazły (cache po hashu treści),
4. **zdjęcia** (opcjonalnie, drogo) – stan wizualny, naklejki ze specyfikacją, naklejka znamionowa na spodzie,
   zrzuty „O tym Macu” / CPU-Z / GPU-Z / Menedżera urządzeń / stanu baterii.

### 0.2. Źródła wartości

Każde pole ma **wartość + źródło**. Dozwolone źródła:

| Źródło | Znaczenie | Pewność (waga w scoringu) |
|---|---|---|
| `title` | tytuł oferty | 1.0 |
| `description` | opis oferty | 1.0 |
| `attribute` | atrybut z formularza Vinted (marka, stan, kategoria…) | 1.0 (po normalizacji, patrz 0.4) |
| `photo` | odczytane jednoznacznie ze zdjęcia (naklejka znamionowa, zrzut ustawień / Menedżera urządzeń, pudełko) – z `evidence` | 1.0 |
| `model_guess` | wywnioskowane z wiedzy o modelu (np. numer modelu → GPU, panel, TGP) | 0.9 |
| `photo_guess` | oszacowane ze zdjęcia (stan wizualny, rozpoznanie modelu po obudowie) – z `evidence` | 0.85 |
| `none` | szukano, nie ma | – |

*(poprawka Claude 2026-10-12)* Ta sama liczba jest **wagą oferty przy liczeniu mediany** (sekcja 2, 3) – jeden system wag zamiast
dwóch; wartości startowe, do kalibracji na trafności zgadywania (sekcja 3).
*(decyzja użytkownika 2026-10-24)* Zgadywanie tylko **niewiele mniej ważne** od pewnych danych (0.9 / 0.85, nie 0.7 / 0.5),
a to, co AI **odczytało** ze zdjęcia (naklejka, zrzut ekranu), jest tak samo pewne jak tekst (1.0). AI zawsze podaje,
czy wartość odczytało (`photo`), czy zgaduje (`photo_guess` / `model_guess`), i w `evidence` – na którym zdjęciu i co widać.

„Nie podano” jest informacją samą w sobie (np. brak liczby cykli baterii w ofercie MacBooka zwykle obniża cenę,
brak zdjęcia włączonego ekranu to ryzyko).

### 0.3. Format odpowiedzi AI

*(poprawka Claude 2026-10-12)* Każde pole to **obiekt** `value` + `source` + (dla pól krytycznych) `evidence`, wymuszany schematem JSON
(tak jak ocena AI w Sniperze: `response_json_schema` / `output_config.format`). Liczby zostają liczbami, nie
trzeba rozbierać tekstu regexem:

```json
"gpu_model":    {"value": "GTX 1650 Ti", "source": "model_guess", "evidence": "SKU FX506LI z tytułu"},
"ram_gb":       {"value": 16, "source": "description"},
"model_number": {"value": "FX506LI-HN011T", "source": "photo", "evidence": "zdjęcie 4: naklejka znamionowa"},
"visual_grade": {"value": "B", "source": "photo_guess"},
"battery_cycles": {"value": null, "source": "none"}
```

- `source` ∈ `title` / `description` / `attribute` / `photo` / `photo_guess` / `model_guess` / `none` (tabela 0.2).
- `true`/`false` małymi literami, liczby bez jednostek, enumy z tego dokumentu.
- Zapis dla człowieka (raporty, maile Snipera) dokleja dopisek przy wyświetlaniu: `photo` → „(ze zdjęcia)”,
  `photo_guess` → „(zgaduję: zdjęcie)”, `model_guess` → „(zgaduję: model)” – np. „GTX 1650 Ti (zgaduję: model)”.

### 0.4. Zasady dla AI

1. Pierwszeństwo: tekst/atrybut → zdjęcie → wiedza o modelu. Sprzeczność → wartość z mocniejszego dowodu
   + flaga `inconsistency` z opisem.
2. **Nie zgaduj** pól oznaczonych w tabelach jako „tylko T” (blokady, usterki funkcjonalne, kondycja baterii,
   gwarancja). Brak informacji → `null` / `none`.
3. **Normalizuj oczywiste błędy formularza** (np. „512 MB” dysku w nowoczesnym laptopie = 512 GB) – wartość
   poprawiona ze źródłem `model_guess`, oryginał w `platform_field_errors`.
4. **Sprawdzaj spójność tytułu, opisu i specyfikacji z modelem.** Jeśli podane parametry pasują do innego modelu
   lub innej karty niż w tytule, opisz to w `model_source_conflict` i dodaj flagę `title_spec_mismatch`.
5. Przy polach krytycznych (GPU, blokady, usterki, bateria, stan ekranu) podaj `evidence` – fragment tekstu albo
   opis zdjęcia („zdjęcie 2: naklejka FX506LI-HN011T, MFD 2021-05”).
6. Opis przetłumaczony automatycznie („Przetłumaczone przez Google”) → interpretuj sens, ustaw
   `translated_description: true` (sygnał sprzedawcy zagranicznego).
7. „Ponad X%” przy baterii → wartość X i `battery_health_is_lower_bound: true`.

Legenda kolumny **Źródła** w tabelach: **T** = tytuł/opis/atrybut, **Z** = zdjęcie, **M** = wiedza o modelu.

## 1. Parametry wspólne dla wszystkich laptopów

| Grupa | Parametry | Źródła | Uwagi do ekstrakcji |
|---|---|---|---|
| Identyfikacja | marka, linia/model (Legion 5, ThinkPad T14, MacBook Air), **numer modelu** (15ACH6, 82JW, A2337, 14-dv2xxx, FX506HM, G15 5530), **pełny SKU** (FX506LI-HN011T), rok / generacja, **data produkcji (MFD)** | T Z M | numer modelu jednoznacznie wyznacza konfigurację bazową – najcenniejsze pole. Ze zdjęcia: naklejka znamionowa na spodzie (Model, SN, MFD), naklejka z cechami przy touchpadzie („ASUS TUF Gaming F15”), logo na klapie. Model wolno rozpoznać po obudowie → `(zgaduję: zdjęcie)` |
| Procesor | producent, rodzina (i5/i7/Ryzen 7/M2), **generacja** (i7-1165G7 = 11. gen), seria (U/P/H/HX/HS), pełny symbol | T Z M | generacja Intela ≥ 8 = oficjalnie Windows 11. Z numeru modelu/SKU → `(zgaduję: model)`; naklejka „Intel Core i5” na obudowie → tylko rodzina |
| RAM | GB, typ (DDR4/DDR5/LPDDR), **lutowany czy wymienny**, maks. rozbudowa | T Z M | „16 GB (2×8)”, „8+8”; „Pamięć: 16 GB” w opisie laptopa to zwykle RAM. Typ i lutowanie z modelu → `(zgaduję: model)`; ilość z modelu tylko, gdy SKU ma jedną wersję |
| Dysk | GB/TB, typ (NVMe/SATA SSD/**HDD**/eMMC), drugi slot | T Z M | HDD/eMMC = staroć/budżet → mocno niżej. Drugi slot z modelu lub z naklejki „2nd SSD Slot” → `(ze zdjęcia)` |
| Ekran | przekątna, rozdzielczość (HD/FHD/WUXGA/QHD/3K/4K), **odświeżanie (Hz)**, matryca (IPS/OLED/mini-LED/TN), dotyk, mat/błysk, jasność (nity), pokrycie sRGB/DCI-P3 | T Z M | „15,6"”, „15.6 cala”, „144Hz”, „2.8K OLED”. Naklejka „144Hz Adaptive Sync” na ramce → `(ze zdjęcia)`. Panel, jasność i pokrycie z SKU → `(zgaduję: model)` |
| Grafika | zintegrowana / dedykowana: model, **VRAM**, **TGP (W)** | T Z M | patrz 1a i 1b. Logo „GeForce RTX” na naklejce potwierdza tylko rodzinę, nie model |
| Zasilacz | moc (W), napięcie/prąd z naklejki (np. 19,5 V ⎓ 9,23 A = 180 W, 20 V ⎓ 7,5 A = 150 W) | T Z M | **poszlaka konfiguracji GPU** w modelach z kilkoma wariantami karty (patrz 1b) |
| Stan | stan Vinted (`status_label`: Nowy z metką / Nowy bez metki / Bardzo dobry / Dobry / Zadowalający), stan wizualny (rysy, wgniecenia, wytarte klawisze, pęknięcia), ekran (martwe piksele, przebarwienia, wypalenia, „white spots”) | T Z | słownik uszkodzeń + nasilenie. *(poprawka Claude 2026-10-12)* `visual_grade`: **A** = brak widocznych śladów użycia, **B** = drobne
rysy/przetarcia widoczne z bliska, **C** = wyraźne rysy, wgniecenia, wytarte klawisze, **D** = pęknięcia / uszkodzenia
obudowy lub ekranu. Ocena ze zdjęć zawsze `photo_guess`; słabe zdjęcia nie dają oceny lepszej niż `A`. „Zadowalający” bez wyjaśnienia w opisie → flaga `vague_condition` |
| Dowody sprawności | zdjęcie włączonego ekranu, zrzut specyfikacji, zdjęcie w grze/benchmarku | Z | brak zdjęcia włączonego ekranu → flaga `no_photos_of_screen_on` |
| Usterki funkcjonalne | nie włącza się, nie ładuje, uszkodzony zawias, ekran, klawiatura, touchpad, port, głośnik, kamera, Wi-Fi; „na części”; po zalaniu | tylko T (+ Z dla widocznych pęknięć) | osobny segment „uszkodzone” – inne ceny. **Sprawności nie zgadujemy** |
| Blokady | hasło BIOS, **iCloud / Activation Lock**, **MDM / Computrace / Absolute** (laptopy firmowe), konto Microsoft, brak systemu | tylko T (+ Z dla zrzutu ekranu blokady) | bardzo silnie obniża cenę lub = części. **Nie zgadujemy** |
| Bateria | **kondycja %**, **cykle**, czas pracy (h), „do wymiany”, „nowa bateria” | T Z | kluczowe u Apple i biznesowych. Zrzut ustawień/raportu baterii → `(ze zdjęcia)`. **Nie zgadujemy z wieku** |
| Wiek i gwarancja | rok zakupu / wiek, data produkcji (MFD), **gwarancja** (do kiedy, producent / sklep / AppleCare / Lenovo Premier), **paragon / faktura (VAT 23%)** | T Z (MFD), M (szacunek wygaśnięcia) | „gwarancja do 03.2027”, „FV 23%”. MFD z naklejki → `(ze zdjęcia)`; gwarancja prawdopodobnie aktywna na podstawie MFD → `(zgaduję: model)` |
| Komplet | oryginalna ładowarka (W), pudełko, torba, mysz, rysik, stacja dokująca | T Z | brak ładowarki = minus |
| System | Windows 10/11 Home/Pro (licencja cyfrowa / naklejka), macOS (wersja), Linux, ChromeOS, brak | T Z M | sufiks „T” w SKU Asusa = fabryczny Windows 10 Home → `(zgaduję: model)` |
| Klawiatura | **układ** (PL/US/UK/DE QWERTZ/FR AZERTY/IT/nordycki), podświetlenie, podkładka numeryczna | T Z | ze zdjęcia: układ Y/Z, A/Q, dodatkowe litery → `(ze zdjęcia)` lub `(zgaduję: zdjęcie)`. Oferty zagraniczne – układ to istotna wada dla kupującego z PL |
| Łączność | Thunderbolt/USB4, ładowanie USB-C, HDMI, czytnik kart, LTE/5G (slot SIM), Wi-Fi 6/6E/7, czytnik linii papilarnych, kamera IR (Windows Hello) | T Z M | moduł Wi-Fi bywa na naklejce znamionowej (np. MediaTek MT7921 = Wi-Fi 6) → `(ze zdjęcia)` |
| Fizyczne | waga, grubość, materiał (aluminium/magnez/plastik), kolor | T Z M | ultrabooki |
| Sprzedaż | sprzedawca firma (`business`), **kraj sprzedawcy** (PL / zagranica / nieznany), waluta, tłumaczony opis, „do negocjacji”, „zamiana”, „tylko odbiór osobisty”, „wysyłka poza Vinted” (ryzyko oszustwa), liczba identycznych sztuk (hurtownik), **cena przedmiotu i cena łączna z opłatą Vinted**, cena przekreślona (obniżka) ⚠, liczba polubień i wyświetleń, komunikat „X osób złożyło ofertę” ⚠ | tylko T | kraj sprzedawcy jest wejściem do premii za Polskę (sekcja 5). Brak tłumaczenia Google i brak przeliczania waluty → `PL (zgaduję: model)` tylko jako poszlaka – do premii liczy się wyłącznie potwierdzony kraj. *(poprawka Claude 2026-10-12)* Kraj bierzemy z pozycji katalogu (`user.country_iso_code` – zapisywany od 2026-10-12, `listings.seller_country`; ⚠ do potwierdzenia, czy Vinted go tam podaje), waluta sprzedawcy (`details.seller_currency`) tylko jako poszlaka (EUR = kilkanaście krajów). ⚠ = pola niewidziane jeszcze w danych katalogu/sidebar (może tylko w aplikacji) – obniżki i tak liczymy z własnej historii `observations` |

## 1a. Karty graficzne – co rozpoznajemy (słownik dla `extract`)

GPU zapisujemy jako: **producent**, **rodzina** (GeForce / RTX pro / Quadro / Radeon RX / Radeon Pro / Arc /
zintegrowana), **model**, **VRAM**, **TGP (W)**, **klasa** (`gaming`, `pro`, `entry`, `igpu`) i **pozycja
w guidelines** (`listed` / `not_listed`, patrz sekcja 5). Karty profesjonalne liczymy w statystykach **osobno** od
GeForce/RX – kupują je inni ludzie (CAD, render, sterowniki z certyfikatami ISV) i inaczej je wyceniają, choć
w grach bywają na poziomie słabszych GeForce (np. RTX A2000 Laptop ≈ okolice RTX 3050 Ti / 3060 zależnie od TGP).

| Rodzina | Modele (laptopowe) | Gdzie typowo | Uwagi do rozpoznawania |
|---|---|---|---|
| **NVIDIA pro – Ampere** | RTX **A500, A1000, A2000, A3000, A4000, A5000, A5500** (Laptop GPU) | Dell Precision 5560/5570/7560/7760/7770, HP ZBook Fury/Studio/Power, ThinkPad P1/P15/P16, MSI WS/Creator | „RTX A2000 4GB/8GB”, „A2000 Laptop”, „NVIDIA A2000” – **nie mylić z Quadro P2000 / T2000 / RTX 2000 Ada** |
| **NVIDIA pro – Ada** | **RTX 500 / 1000 / 2000 / 3000 / 3500 / 4000 / 5000 Ada Generation** | Precision 5680/7680/7780, ZBook (2023+), ThinkPad P1 G6/P16 G2 | „RTX 2000 Ada” ≠ „RTX 2050”/„RTX 2060”; słowo **Ada** rozstrzyga |
| **NVIDIA pro – Turing / Quadro** | Quadro **T500, T550, T600, T1000, T1200, T2000**, **Quadro RTX 3000/4000/5000**, starsze **P520/P620/P1000/P2000/P3200/P4200/P5200**, **M1200/M2200**, K-series | Precision 3540–3570/5540/7540/7550, ZBook G5–G8, ThinkPad P5x/P1 G1–G3, T15g | „T550 4GB”, „Quadro P2000” – P/M/K = starsze pokolenia (niska wartość); T500–T600 ≈ klasa MX/GTX 1650 |
| **NVIDIA GeForce – gaming (RTX)** | RTX 2050/2060/2070/2080 (Super, Max-Q), RTX 3050/3050 Ti/3060/3070/3070 Ti/3080/3080 Ti, RTX 4050/4060/4070/4080/4090, RTX 5050/5060/5070/5070 Ti/5080/5090 | gamingowe, kreatorskie | **TGP** decyduje (np. RTX 3060 60–130 W, RTX 4060 35–140 W); „Max-Q” = niskie TGP; RTX 2050 to słaba karta mimo „RTX” |
| **NVIDIA GeForce – GTX** | GTX 1050/1050 Ti/1060/1070/1080, GTX 1650/1650 Ti/1660 Ti | starsze gamingowe (np. TUF FX506LH/LI, FX505) | **poza progami `guidelines.md`** – flaga `gpu_not_in_guidelines`; sniper odrzuca (sekcja 5). Brak DLSS i RT |
| **NVIDIA – wejściowe** | MX110–MX570 | biurowe/budżetowe | klasa `entry` – praktycznie nie podnosi ceny |
| **AMD Radeon RX (mobilne)** | RX 5500M/5600M/5700M, RX 6500M/6550M/6600M/6650M/6700M/6800M/6850M XT, RX 6600S/6700S/6800S, RX 7600S/7700S, RX 7600M/7600M XT/7800M | Asus TUF/ROG/Zephyrus (Advantage Edition), Lenovo Legion (AMD), HP Omen/Victus, Dell G5 SE, MSI Alpha/Bravo | sufiks **M / S / XT** ważny (S = cienkie, niższe TGP); „RX 6800M” ≈ RTX 3070 |
| **AMD Radeon Pro (mobilne)** | **Radeon Pro WX 2100/3100/3200/4130/4150/7100**, **Radeon Pro W5500M/W6600M**, **Radeon Pro 555/555X/560/560X/5300M/5500M/5600M/Vega 16/20** | starsze Precision (WX), ZBook G5/G6 (WX 3200), HP ZBook Firefly, **MacBook Pro 15" 2017–2019 i 16" 2019** (Pro 5300M/5500M/5600M) | „Radeon Pro 5500M” (Mac) ≠ „RX 5500M”; klasa `pro` dla WX/W, w MacBookach jako atrybut Maca |
| **AMD zintegrowane** | Vega 6/7/8, Radeon 660M/680M, **760M/780M**, **880M/890M** | Ryzen 5000–8000/AI 300 | 680M/780M/890M to iGPU zdolne do lekkiego grania – cecha warta osobnej flagi |
| **Intel** | UHD/Iris Xe (zintegrowane), **Arc A350M/A370M/A550M/A730M/A770M**, Arc 130V/140V (Lunar Lake) | budżetowe, Samsung/Acer/MSI z Arc | Arc dedykowany – rzadki, osobna klasa |
| **Apple** | rdzenie GPU M1–M4 (7/8/10 rdzeni w Air; 14/16/19/30/32/38/40 w Pro/Max) | MacBook | liczba rdzeni GPU = część klucza konfiguracji Maca |

Pułapki:
- „8GB” obok GPU to zwykle VRAM, ale bywa RAM – brać liczbę z kontekstu („RTX 3060 6GB”, „16GB RAM”).
- „RTX 3000” bez „Quadro”/„Ada” = najpewniej **Quadro RTX 3000** (Turing) w ZBooku/Precision, a nie GeForce.
- W ofertach Dell Precision model GPU często jest tylko w opisie albo w numerze modelu (Precision 5560 →
  T1200/A2000) – wtedy AI albo tabela „model laptopa → możliwe GPU” (1b).
- Tytuł ogólny („Laptop Gamingowy ASUS”) nie przesądza o karcie – sprawdzić opis, naklejki i numer modelu.
- „Gamingowy” w tytule laptopa z GTX 1650 to nadal GTX – ustaw klasę po modelu karty, nie po tytule.

## 1b. Numer modelu → możliwe GPU (tabela pomocnicza)

Gdy GPU nie ma w tekście, a numer modelu/SKU jest znany (z tekstu albo z naklejki znamionowej), AI może wpisać
kartę jako `(zgaduję: model)`. Jeśli model ma kilka wariantów karty, wpisz listę możliwych w `gpu_candidates`,
a w `gpu_model` tylko wtedy, gdy poszlaki (zasilacz, TGP, rok, SKU) wskazują jeden wariant.

| Model / SKU | GPU | Uwagi |
|---|---|---|
| Asus TUF F15 **FX506LH** | GTX 1650 4 GB | Intel 10. gen |
| Asus TUF F15 **FX506LI** | GTX 1650 Ti 4 GB | Intel 10. gen (zwykle i5-10300H); np. FX506LI-HN011T |
| Asus TUF F15 **FX506HM** | RTX 3060 6 GB (⚠ TGP do potwierdzenia, np. zrzutem GPU-Z – *(poprawka Claude 2026-10-12)*) | Intel 11. gen (i5-11400H / i7-11800H) |
| Dell **G15 5530** | RTX 3050 6 GB / RTX 4050 / RTX 4060 | **zasilacz 180 W** → raczej RTX 3050; **240 W** → raczej RTX 4050/4060 |
| Dell **Precision 5560** | T1200 / RTX A2000 | |

Tabelę rozbudowujemy przy każdym potwierdzonym przypadku (np. ze zrzutu GPU-Z w ofercie). Wiersze z wariantami
GPU zawsze zaznaczamy w `confidence_overall` jako `medium` lub niżej, dopóki karta nie jest potwierdzona.

## 2. Segmenty i ich klucze

Segment ustalamy regułami (model/linia, GPU, słowa w tytule), oferta może mieć segment główny + cechy
(np. „biznesowy” + „dotykowy”). Klucz konfiguracji = pola, po których grupujemy ceny w raportach. Pole klucza
pochodzące ze zgadywania (`model_guess`, `photo_guess`) oznaczamy w raporcie – oferta trafia do grupy, ale
z niższą wagą przy liczeniu mediany – *(poprawka Claude 2026-10-12)* waga = pewność źródła z tabeli 0.2 (`model_guess` 0.9,
`photo_guess` 0.85 – decyzja użytkownika 2026-10-24), zamiast osobnej wagi 0.2.

| Segment | Kto kupuje / na co patrzy | Klucz konfiguracji (grupowanie cen) | Dodatkowe pola specyficzne |
|---|---|---|---|
| **Gamingowe** (Legion, ROG/TUF, Omen/Victus, Predator/Nitro, MSI, Alienware, Razer, Gigabyte Aorus, Dell G) | GPU ponad wszystko, potem TGP, CPU H/HX, ekran Hz, RAM | GPU + VRAM + TGP (przedział) + klasa CPU + RAM | **TGP (W)**, MUX switch / Advanced Optimus, chłodzenie i temperatury, wymiana pasty/podkładek, odświeżanie i jasność ekranu, zasilacz (W), RGB, „po kopaniu kryptowalut”, **pozycja GPU w guidelines** |
| **MacBook** (Air/Pro, Intel vs Apple Silicon) | stan wizualny, cykle i kondycja baterii, wiek, gwarancja/AppleCare, brak blokad | układ (M1/M2/M3/M4 + Pro/Max + rdzenie CPU/GPU) + RAM + SSD + przekątna (+ rok) | **cykle baterii, kondycja %**, AppleCare/gwarancja do, **iCloud/MDM**, numer modelu A****, klawiatura (układ, „motylkowa” 2016–2019), ekran (staingate, delaminacja), komplet (ładowarka, pudełko), Intel = osobna grupa. Ekran „hello” na zdjęciu = reset, **nie wyklucza** blokady aktywacji |
| **Biznesowe / poleasingowe** (ThinkPad T/X/L/E, Latitude, EliteBook/ProBook, Precision/ZBook lżejsze) | generacja CPU, stan baterii, ekran FHD vs HD, LTE, klawiatura, faktura VAT, gwarancja od refurbishera | model + generacja CPU + RAM + SSD + ekran (HD/FHD/dotyk) | vPro, LTE, stacja dokująca, **MDM/Computrace**, klasa A/B/C (refurbisherzy), faktura VAT, „poleasingowy”, liczba sztuk |
| **Ultrabooki / premium konsumenckie** (XPS, Zenbook, Yoga Slim, Spectre/Envy, Swift, Galaxy Book, Surface Laptop, LG Gram) | ekran (OLED/3K), waga, czas pracy, jakość wykonania | model + CPU + RAM + SSD + typ ekranu | waga, czas pracy baterii, OLED, Thunderbolt |
| **2 w 1 / dotykowe / konwertowalne** (Surface Pro/Go/Book, Yoga, x360, Flip, ThinkPad X1 Yoga, HP Elite x2; iPad z klawiaturą – inna kategoria) | **dotyk**, zawias 360° lub odłączana klawiatura, **rysik w zestawie**, klawiatura (Type Cover) w zestawie | model + CPU + RAM + SSD + komplet (klawiatura/rysik) | rysik (model, w zestawie?), klawiatura w zestawie (oryginał/zamiennik, **układ**), obsługa rysika (MPP/USI). Te same urządzenia trafiają też do kategorii „Tablety” – deduplikacja po ID oferty |
| **Mobilne stacje robocze / dla twórców** (MacBook Pro Max, Dell Precision, HP ZBook, ThinkPad P, ProArt, Studiobook) | GPU profesjonalne (NVIDIA RTX A500–A5500, RTX Ada, Quadro T/P/RTX; AMD Radeon Pro WX/W – patrz 1a), RAM 32–64 GB, ekran 4K/kalibracja, CPU HX/Xeon | GPU (model + pokolenie) + CPU + RAM + ekran | pokrycie barw (100% DCI-P3/Adobe RGB), kalibracja, ECC, certyfikaty ISV |
| **Budżetowe / do nauki / biura** (IdeaPad, Vivobook, Aspire, HP 15/255, Inspiron, Modern) | cena, SSD (nie HDD), RAM ≥ 8 GB, Windows 11, bateria, waga | CPU (generacja/klasa) + RAM + typ dysku + ekran | zgodność z Windows 11, Office w zestawie |
| **Chromebooki** | **data końca aktualizacji (AUE)**, dotyk, cena | model (+ AUE) | AUE (`(zgaduję: model)`) – po tej dacie wartość spada do zera |
| **Uszkodzone / na części** | co działa, czego brakuje, która część jest wartościowa (płyta, matryca, GPU) | model + rodzaj usterki | lista usterek, „bez dysku/RAM/ładowarki”, „nie włącza się” |
| **Retro / kolekcjonerskie** (ThinkPad X220/T420/T60, PowerBook, stare Toshiby) | kompletność, oryginalność, stan | model | zwykle < 700 zł – poza zakresem, chyba że rzadkie |

## 2a. Flagi przekrojowe

Flagi nie są segmentami – oferta może mieć ich kilka.

**Informacyjne:**
- `foreign` – waluta sprzedawcy ≠ PLN, tłumaczony opis, cena „przeliczona na twoją walutę”, układ klawiatury,
- `business` – sprzedawca firma,
- `new_tagged` – stan Vinted „Nowy z metką/bez metki”, plomby, „nieużywany”,
- `bulk` – wiele identycznych ofert,
- `price_dropped` – cena przekreślona / obniżka w historii `observations`.

**Czerwone flagi (`red_flags`):**
- `fraud_risk` – cena dużo poniżej mediany modelu, kontakt lub płatność poza Vinted, zdjęcia ze sklepu, nowe konto,
- `pickup_only` / `not_for_sale` – w opisie „tylko odbiór osobisty” albo „to nie jest przedmiot na sprzedaż”,
- `screen_damaged` – zniszczona / porysowana matryca (w droższych modelach = omijać),
- `no_photos_of_screen_on` – na żadnym zdjęciu ekran nie jest włączony,
- `vague_condition` – stan „Zadowalający” bez wyjaśnienia w opisie,
- `title_spec_mismatch` – tytuł/opis nie zgadza się z modelem lub naklejką (np. „RTX” przy SKU z GTX),
- `gpu_not_in_guidelines` – karta poniżej progów (GTX, MX, iGPU) w segmencie gamingowym,
- `foreign_keyboard_layout`,
- `inconsistency`.

**Sygnały okazji (`opportunity_signals`):**
- `vague_title` – tytuł bez modelu („Laptop Gamingowy ASUS”) – mniej trafień w wyszukiwarce,
- `model_underlabeled` – zdjęcie/naklejka wskazuje lepszy model lub kartę niż tytuł,
- `price_dropped` – sprzedawca obniżał cenę (zmotywowany),
- `high_demand` – dużo polubień / komunikat o ofertach (szybka odsprzedaż, ale też konkurencja),
- `negotiable`, `urgent_sale`, `wrong_category`, `warranty_likely_active`, `full_set`.

## 3. Na co patrzymy przy analizie (etap 4)

* Mediana ceny wystawienia przy sprzedaży (górna granica ceny transakcji) i czas sprzedaży per klucz segmentu,
  z liczbą próbek (n ≥ 10, inaczej „za mało danych”). Oferty z kluczem ze zgadywania – z niższą wagą (sekcja 2).
* Wpływ pojedynczych cech: o ile niższa cena przy braku ładowarki, HDD zamiast SSD, układzie klawiatury DE/FR,
  braku liczby cykli, uszkodzeniu wizualnym, stanie „Zadowalający”, braku zdjęcia włączonego ekranu; o ile
  szybciej schodzi RTX 4060 140 W niż 80 W.
* Oferty zagraniczne vs krajowe osobno (inny koszt wysyłki i dynamika).
* Obniżki przed sprzedażą (historia `observations`), popyt (`favourite_count`, `view_count`, komunikat o ofertach).
* Trafność zgadywania: odsetek ofert, w których `model_guess` / `photo_guess` zgadzał się z potem potwierdzoną
  wartością – do kalibracji wag z sekcji 0.2.

## 4. Kolejność wdrożenia

1. `details` – opis + atrybuty + „Dodane” + firma + waluta sprzedawcy, raz na ofertę (zrobione 2026-10-11).
2. `extract` v1 – reguły: segment, CPU (z generacją), GPU (+VRAM, TGP), RAM, dysk (typ), ekran (przekątna,
   rozdzielczość, Hz, dotyk, OLED), Apple (układ, rdzenie, cykle, kondycja %), bateria, gwarancja/faktura,
   ładowarka, układ klawiatury, blokady, usterki, kraj sprzedawcy, cena łączna. Raport pokrycia (ile ofert ma
   każde pole) + przykłady braków.
3. AI wsadowo dla braków w polach kluczowych dla segmentu (cache po `content_hash`), z formatem obiektowym (0.3,
   schemat JSON) i tabelą 1b w promptcie.
4. Zdjęcia (*(poprawka Claude 2026-10-12)*: obrazy pobiera dostawca AI, więc nie kosztują transferu proxy, ale kosztują tokeny, a Gemini
   miewa problemy z URL-ami `images1.vinted.net` – w Sniperze jest tryb pobierania z domowego IP) – w pierwszej kolejności **naklejka znamionowa** (numer modelu/SKU, MFD, moc zasilacza) i **zdjęcie
   włączonego ekranu** w segmencie gamingowym, bo rozstrzygają GPU i ryzyko matrycy; stan wizualny dopiero, jeśli
   okaże się, że realnie zmienia wyceny.

## 5. Powiązanie z `guidelines.md` (sniper)

Pola potrzebne do policzenia decyzji zakupowej:

| Pole | Skąd | Do czego |
|---|---|---|
| `gpu_model` | 1a / 1b | wybór progu „Maksymalna cena zakupu” |
| `gpu_series` | z modelu (2000/3000/4000/5000) | korekta wydajnościowa (zasada 1) |
| `seller_country` | sekcja 1 „Sprzedaż” | premia za Polskę (zasada 2) – tylko gdy kraj potwierdzony |
| `price_item` / `price_total` | oferta | porównanie z progiem; opłata Vinted = 5% + 2,90 zł (sprawdzone na danych: 510 → 28,40; 706,50 → 38,23) |
| `red_flags` | 2a | zasada 3 (omijać) |
| `visual_grade`, `status_label` | sekcja 1 „Stan” | korekta szacowanej ceny sprzedaży w dół przy stanie „Zadowalający” / uszkodzeniach |

Kolejność liczenia: próg bazowy → korekta za serię 3000 → premia za Polskę → porównanie z ceną łączną → zysk
= szacowana cena sprzedaży − cena łączna − 150 zł kosztów.

**Do ustalenia w `guidelines.md`:** czy progi dla RTX 3050/3060/3070/3080 już zawierają korektę z zasady 1, czy
trzeba ją jeszcze odjąć. Dopóki to nie jest dopisane, sniper liczy oba warianty i raportuje niższy próg jako
decydujący, a wyższy w uwagach.

**Reguła odrzucenia:** oferty z flagą `gpu_not_in_guidelines` (GTX, MX, iGPU w segmencie gamingowym) sniper
odrzuca bez liczenia progu, ale zapisuje je do statystyk segmentu.

## 6. Strategia „rozbiórki” – RAM / dysk osobno (pomysł użytkownika 2026-10-14)

Kupić laptopa, którego normalnie bym nie kupił, gdy ma cenny RAM (albo dysk): wyjąć i sprzedać osobno, włożyć
tańszy, sprzedać laptopa. Zysk **z = x + y − cena zakupu (z opłatą) − c − wysyłki**, gdzie
x = mediana sprzedaży wyjętych kości (kategoria RAM, używane, ten typ/pojemność/układ), y = mediana sprzedaży tego
modelu z mniejszym RAM-em (laptopy), c = koszt kości zastępczych (najtańszy pasujący zestaw z kategorii RAM).
Próg użytkownika: z ≥ ~1500 zł.

Wymagane pola (wiedza o modelu – tabela `models`, bo sprzedawcy rzadko to podają):
`ram_soldered` (lutowany = rozbiórka niemożliwa: MacBooki, większość ultrabooków, część cienkich gamingowych),
`ram_type` (DDR4/DDR5 SO-DIMM, LPDDR), `ram_slots`, `ram_config` (2×16 ≠ 1×32), `max_ram_gb`; analogicznie
dysk: `ssd_slots`, `ssd_interface` (NVMe PCIe 3/4). Wymaga kategorii **RAM** w crawlu (czeka na cURL od
użytkownika, z rozróżnieniem DIMM / SO-DIMM).

Przykład (oferta zagraniczna, 2026-10-14): ASUS ROG Strix SCAR 17 G733QS, R9 5900HX, RTX 3080 Laptop 16 GB,
32 GB **DDR4-3200 SO-DIMM** (Armoury Crate: 3200 MT/s, 31,4 GB; Ryzen 5000H = tylko DDR4), 2 sloty wymienne
(⚠ z wiedzy o modelu – potwierdzić CPU-Z/SPD), 3 658,37 zł z opłatą.
