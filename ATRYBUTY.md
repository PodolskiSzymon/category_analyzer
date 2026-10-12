# Co wyciągamy z ofert laptopów – segmenty kupujących i parametry

Cel: dla każdej oferty ustalić **segment** (kto ją kupuje) i **parametry, od których w tym segmencie zależy cena
i szybkość sprzedaży**. Raporty (etap 4) grupują ceny po „kluczu konfiguracji” właściwym dla segmentu – inaczej
mediana miesza MacBooka M1 8/256 z M1 16/512 albo RTX 4060 80 W z RTX 4060 140 W.

Źródła (od najtańszego): **tytuł + `item_box`** (marka, model, stan – za darmo z katalogu) → **opis + atrybuty
z `details/sidebar`** (raz na ofertę, ~6–10 KB) → **AI wsadowo** tylko dla pól, których reguły nie znalazły
(cache po hashu treści) → (opcjonalnie, drogo) zdjęcia: stan wizualny, naklejki ze specyfikacją, zrzuty
„O tym Macu” / CPU-Z / stan baterii.

Każde pole ma wartość + źródło (`title` / `description` / `attribute` / `ai` / `none` = szukano, nie ma). „Nie
podano” jest informacją samą w sobie (np. brak liczby cykli baterii w ofercie MacBooka zwykle obniża cenę).

## 1. Parametry wspólne dla wszystkich laptopów

| Grupa | Parametry | Uwagi do ekstrakcji |
|---|---|---|
| Identyfikacja | marka, linia/model (Legion 5, ThinkPad T14, MacBook Air), **numer modelu** (15ACH6, 82JW, A2337, 14-dv2xxx), rok / generacja | numer modelu jednoznacznie wyznacza konfigurację bazową – najcenniejsze pole |
| Procesor | producent, rodzina (i5/i7/Ryzen 7/M2), **generacja** (i7-1165G7 = 11. gen), seria (U/P/H/HX/HS), pełny symbol | generacja Intela ≥ 8 = oficjalnie Windows 11 – ważne dla biurowych/budżetowych |
| RAM | GB, typ (DDR4/DDR5/LPDDR), **lutowany czy wymienny**, maks. rozbudowa | „16 GB (2×8)”, „8+8” |
| Dysk | GB/TB, typ (NVMe/SATA SSD/**HDD**/eMMC), drugi slot | HDD/eMMC = staroć/budżet → mocno niżej |
| Ekran | przekątna, rozdzielczość (HD/FHD/WUXGA/QHD/3K/4K), **odświeżanie (Hz)**, matryca (IPS/OLED/mini-LED/TN), dotyk, mat/błysk, jasność (nity), pokrycie sRGB/DCI-P3 | „15,6"”, „15.6 cala”, „144Hz”, „2.8K OLED” |
| Grafika | zintegrowana / dedykowana: model, **VRAM**, **TGP (W)** | patrz segment gamingowy |
| Stan | stan Vinted (`status_label`), stan wizualny (rysy, wgniecenia, wytarte klawisze, pęknięcia), ekran (martwe piksele, przebarwienia, wypalenia, „white spots”) | słownik uszkodzeń + nasilenie |
| Usterki funkcjonalne | nie włącza się, nie ładuje, uszkodzony zawias, ekran, klawiatura, touchpad, port, głośnik, kamera, Wi-Fi; „na części”; po zalaniu | osobny segment „uszkodzone” – inne ceny |
| Blokady | hasło BIOS, **iCloud / Activation Lock**, **MDM / Computrace / Absolute** (laptopy firmowe), konto Microsoft, brak systemu | bardzo silnie obniża cenę lub = części |
| Bateria | **kondycja %**, **cykle**, czas pracy (h), „do wymiany”, „nowa bateria” | kluczowe u Apple i biznesowych |
| Wiek i gwarancja | rok zakupu / wiek, **gwarancja** (do kiedy, producent / sklep / AppleCare / Lenovo Premier), **paragon / faktura (VAT 23%)** | „gwarancja do 03.2027”, „FV 23%” |
| Komplet | oryginalna ładowarka (W), pudełko, torba, mysz, rysik, stacja dokująca | brak ładowarki = minus |
| System | Windows 10/11 Home/Pro (licencja cyfrowa / naklejka), macOS (wersja), Linux, ChromeOS, brak | |
| Klawiatura | **układ** (PL/US/UK/DE QWERTZ/FR AZERTY/IT/nordycki), podświetlenie, podkładka numeryczna | oferty zagraniczne – układ to istotna wada dla kupującego z PL |
| Łączność | Thunderbolt/USB4, ładowanie USB-C, HDMI, czytnik kart, LTE/5G (slot SIM), Wi-Fi 6/6E/7, czytnik linii papilarnych, kamera IR (Windows Hello) | |
| Fizyczne | waga, grubość, materiał (aluminium/magnez/plastik), kolor | ultrabooki |
| Sprzedaż | sprzedawca firma (`business`), kraj / waluta sprzedawcy, „do negocjacji”, „zamiana”, „tylko odbiór osobisty”, „wysyłka poza Vinted” (ryzyko oszustwa), liczba identycznych sztuk (hurtownik) | |

## 1a. Karty graficzne – co rozpoznajemy (słownik dla `extract`)

GPU zapisujemy jako: **producent**, **rodzina** (GeForce / RTX pro / Quadro / Radeon RX / Radeon Pro / Arc /
zintegrowana), **model**, **VRAM**, **TGP (W)** i **klasa** (`gaming`, `pro`, `entry`, `igpu`). Karty profesjonalne
liczymy w statystykach **osobno** od GeForce/RX – kupują je inni ludzie (CAD, render, sterowniki z certyfikatami
ISV) i inaczej je wyceniają, choć w grach bywają na poziomie słabszych GeForce (np. RTX A2000 Laptop ≈ okolice
RTX 3050 Ti / 3060 zależnie od TGP).

| Rodzina | Modele (laptopowe) | Gdzie typowo | Uwagi do rozpoznawania |
|---|---|---|---|
| **NVIDIA pro – Ampere** | RTX **A500, A1000, A2000, A3000, A4000, A5000, A5500** (Laptop GPU) | Dell Precision 5560/5570/7560/7760/7770, HP ZBook Fury/Studio/Power, ThinkPad P1/P15/P16, MSI WS/Creator | „RTX A2000 4GB/8GB”, „A2000 Laptop”, „NVIDIA A2000” – **nie mylić z Quadro P2000 / T2000 / RTX 2000 Ada** |
| **NVIDIA pro – Ada** | **RTX 500 / 1000 / 2000 / 3000 / 3500 / 4000 / 5000 Ada Generation** | Precision 5680/7680/7780, ZBook (2023+), ThinkPad P1 G6/P16 G2 | „RTX 2000 Ada” ≠ „RTX 2050”/„RTX 2060”; słowo **Ada** rozstrzyga |
| **NVIDIA pro – Turing / Quadro** | Quadro **T500, T550, T600, T1000, T1200, T2000**, **Quadro RTX 3000/4000/5000**, starsze **P520/P620/P1000/P2000/P3200/P4200/P5200**, **M1200/M2200**, K-series | Precision 3540–3570/5540/7540/7550, ZBook G5–G8, ThinkPad P5x/P1 G1–G3, T15g | „T550 4GB”, „Quadro P2000” – P/M/K = starsze pokolenia (niska wartość); T500–T600 ≈ klasa MX/GTX 1650 |
| **NVIDIA GeForce – gaming** | GTX 1050/1050 Ti/1060/1070/1080, GTX 1650/1660 Ti, RTX 2050/2060/2070/2080 (Super, Max-Q), RTX 3050/3050 Ti/3060/3070/3070 Ti/3080/3080 Ti, RTX 4050/4060/4070/4080/4090, RTX 5050/5060/5070/5070 Ti/5080/5090 | gamingowe, kreatorskie | **TGP** decyduje (np. RTX 3060 60–130 W, RTX 4060 35–140 W); „Max-Q” = niskie TGP; RTX 2050 to słaba karta mimo „RTX” |
| **NVIDIA – wejściowe** | MX110–MX570 | biurowe/budżetowe | klasa `entry` – praktycznie nie podnosi ceny |
| **AMD Radeon RX (mobilne)** | RX 5500M/5600M/5700M, RX 6500M/6550M/6600M/6650M/6700M/6800M/6850M XT, RX 6600S/6700S/6800S, RX 7600S/7700S, RX 7600M/7600M XT/7800M | Asus TUF/ROG/Zephyrus (Advantage Edition), Lenovo Legion (AMD), HP Omen/Victus, Dell G5 SE, MSI Alpha/Bravo | sufiks **M / S / XT** ważny (S = cienkie, niższe TGP); „RX 6800M” ≈ RTX 3070 |
| **AMD Radeon Pro (mobilne)** | **Radeon Pro WX 2100/3100/3200/4130/4150/7100**, **Radeon Pro W5500M/W6600M**, **Radeon Pro 555/555X/560/560X/5300M/5500M/5600M/Vega 16/20** | starsze Precision (WX), ZBook G5/G6 (WX 3200), HP ZBook Firefly, **MacBook Pro 15" 2017–2019 i 16" 2019** (Pro 5300M/5500M/5600M) | „Radeon Pro 5500M” (Mac) ≠ „RX 5500M”; klasa `pro` dla WX/W, w MacBookach jako atrybut Maca |
| **AMD zintegrowane** | Vega 6/7/8, Radeon 660M/680M, **760M/780M**, **880M/890M** | Ryzen 5000–8000/AI 300 | 680M/780M/890M to iGPU zdolne do lekkiego grania – cecha warta osobnej flagi |
| **Intel** | UHD/Iris Xe (zintegrowane), **Arc A350M/A370M/A550M/A730M/A770M**, Arc 130V/140V (Lunar Lake) | budżetowe, Samsung/Acer/MSI z Arc | Arc dedykowany – rzadki, osobna klasa |
| **Apple** | rdzenie GPU M1–M4 (7/8/10 rdzeni w Air; 14/16/19/30/32/38/40 w Pro/Max) | MacBook | liczba rdzeni GPU = część klucza konfiguracji Maca |

Pułapki: „8GB” obok GPU to zwykle VRAM, ale bywa RAM – brać liczbę z kontekstu („RTX 3060 6GB”, „16GB RAM”);
„RTX 3000” bez „Quadro”/„Ada” = najpewniej **Quadro RTX 3000** (Turing) w ZBooku/Precision, a nie GeForce;
w ofertach Dell Precision model GPU często jest tylko w opisie albo w numerze modelu (Precision 5560 → T1200/A2000)
– wtedy AI albo tabela „model laptopa → możliwe GPU”.

## 2. Segmenty i ich klucze

Segment ustalamy regułami (model/linia, GPU, słowa w tytule), oferta może mieć segment główny + cechy
(np. „biznesowy” + „dotykowy”). Klucz konfiguracji = pola, po których grupujemy ceny w raportach.

| Segment | Kto kupuje / na co patrzy | Klucz konfiguracji (grupowanie cen) | Dodatkowe pola specyficzne |
|---|---|---|---|
| **Gamingowe** (Legion, ROG/TUF, Omen/Victus, Predator/Nitro, MSI, Alienware, Razer, Gigabyte Aorus, Dell G) | GPU ponad wszystko, potem TGP, CPU H/HX, ekran Hz, RAM | GPU + VRAM + TGP (przedział) + klasa CPU + RAM | **TGP (W)**, MUX switch / Advanced Optimus, chłodzenie i temperatury, wymiana pasty/podkładek, odświeżanie i jasność ekranu, zasilacz (W), RGB, „po kopaniu kryptowalut” |
| **MacBook** (Air/Pro, Intel vs Apple Silicon) | stan wizualny, cykle i kondycja baterii, wiek, gwarancja/AppleCare, brak blokad | układ (M1/M2/M3/M4 + Pro/Max + rdzenie CPU/GPU) + RAM + SSD + przekątna (+ rok) | **cykle baterii, kondycja %**, AppleCare/gwarancja do, **iCloud/MDM**, numer modelu A****, klawiatura (układ, „motylkowa” 2016–2019), ekran (staingate, delaminacja), komplet (ładowarka, pudełko), Intel = osobna grupa |
| **Biznesowe / poleasingowe** (ThinkPad T/X/L/E, Latitude, EliteBook/ProBook, Precision/ZBook lżejsze) | generacja CPU, stan baterii, ekran FHD vs HD, LTE, klawiatura, faktura VAT, gwarancja od refurbishera | model + generacja CPU + RAM + SSD + ekran (HD/FHD/dotyk) | vPro, LTE, stacja dokująca, **MDM/Computrace**, klasa A/B/C (refurbisherzy), faktura VAT, „poleasingowy”, liczba sztuk |
| **Ultrabooki / premium konsumenckie** (XPS, Zenbook, Yoga Slim, Spectre/Envy, Swift, Galaxy Book, Surface Laptop, LG Gram) | ekran (OLED/3K), waga, czas pracy, jakość wykonania | model + CPU + RAM + SSD + typ ekranu | waga, czas pracy baterii, OLED, Thunderbolt |
| **2 w 1 / dotykowe / konwertowalne** (Surface Pro/Go/Book, Yoga, x360, Flip, ThinkPad X1 Yoga, iPad z klawiaturą – inna kategoria) | **dotyk**, zawias 360° lub odłączana klawiatura, **rysik w zestawie**, klawiatura (Type Cover) w zestawie | model + CPU + RAM + SSD + komplet (klawiatura/rysik) | rysik (model, w zestawie?), klawiatura w zestawie, obsługa rysika (MPP/USI) |
| **Mobilne stacje robocze / dla twórców** (MacBook Pro Max, Dell Precision, HP ZBook, ThinkPad P, ProArt, Studiobook) | GPU profesjonalne (NVIDIA RTX A500–A5500, RTX Ada, Quadro T/P/RTX; AMD Radeon Pro WX/W – patrz 1a), RAM 32–64 GB, ekran 4K/kalibracja, CPU HX/Xeon | GPU (model + pokolenie) + CPU + RAM + ekran | pokrycie barw (100% DCI-P3/Adobe RGB), kalibracja, ECC, certyfikaty ISV |
| **Budżetowe / do nauki / biura** (IdeaPad, Vivobook, Aspire, HP 15/255, Inspiron, Modern) | cena, SSD (nie HDD), RAM ≥ 8 GB, Windows 11, bateria, waga | CPU (generacja/klasa) + RAM + typ dysku + ekran | zgodność z Windows 11, Office w zestawie |
| **Chromebooki** | **data końca aktualizacji (AUE)**, dotyk, cena | model (+ AUE) | AUE – po tej dacie wartość spada do zera |
| **Uszkodzone / na części** | co działa, czego brakuje, która część jest wartościowa (płyta, matryca, GPU) | model + rodzaj usterki | lista usterek, „bez dysku/RAM/ładowarki”, „nie włącza się” |
| **Retro / kolekcjonerskie** (ThinkPad X220/T420/T60, PowerBook, stare Toshiby) | kompletność, oryginalność, stan | model | zwykle < 700 zł – poza zakresem, chyba że rzadkie |

Inne cechy przekrojowe (flagi, nie segmenty): **zagraniczna** (waluta sprzedawcy ≠ PLN, układ klawiatury),
**firma** (`business`), **nowy / z metką** (stan Vinted, plomby, „nieużywany”), **ryzyko oszustwa** (cena dużo
poniżej mediany modelu, kontakt poza Vinted, zdjęcia ze sklepu, nowe konto), **hurt** (wiele identycznych ofert).

## 3. Na co patrzymy przy analizie (etap 4)

* Mediana ceny wystawienia przy sprzedaży (górna granica ceny transakcji) i czas sprzedaży per klucz segmentu,
  z liczbą próbek (n ≥ 10, inaczej „za mało danych”).
* Wpływ pojedynczych cech: o ile niższa cena przy braku ładowarki, HDD zamiast SSD, układzie klawiatury DE/FR,
  braku liczby cykli, uszkodzeniu wizualnym; o ile szybciej schodzi RTX 4060 140 W niż 80 W.
* Oferty zagraniczne vs krajowe osobno (inny koszt wysyłki i dynamika).
* Obniżki przed sprzedażą (historia `observations`), popyt (`favourite_count`, `view_count`).

## 4. Kolejność wdrożenia

1. `details` – opis + atrybuty + „Dodane” + firma + waluta sprzedawcy, raz na ofertę (zrobione 2026-10-11).
2. `extract` v1 – reguły: segment, CPU (z generacją), GPU (+VRAM, TGP), RAM, dysk (typ), ekran (przekątna,
   rozdzielczość, Hz, dotyk, OLED), Apple (układ, rdzenie, cykle, kondycja %), bateria, gwarancja/faktura,
   ładowarka, układ klawiatury, blokady, usterki. Raport pokrycia (ile ofert ma każde pole) + przykłady braków.
3. AI wsadowo dla braków w polach kluczowych dla segmentu (cache po `content_hash`).
4. Zdjęcia – tylko jeśli okaże się, że stan wizualny / zrzuty specyfikacji realnie zmieniają wyceny.
