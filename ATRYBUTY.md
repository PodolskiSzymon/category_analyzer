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
| **Mobilne stacje robocze / dla twórców** (MacBook Pro Max, Precision, ZBook, ThinkPad P, ProArt, Studiobook) | GPU profesjonalne (RTX A/Ada), RAM 32–64 GB, ekran 4K/kalibracja, CPU HX | GPU + CPU + RAM + ekran | pokrycie barw (100% DCI-P3/Adobe RGB), kalibracja, ECC, certyfikaty ISV |
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
