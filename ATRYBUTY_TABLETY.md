> **Kategoria Vinted 3728 (tablety).** Wersja użytkownika z poprawkami Claude pod analizę rynku
> (2026-10-12). Zasady wspólne – **`EKSTRAKCJA.md`** (ma pierwszeństwo). Zmiany względem wersji użytkownika:
> 1. Format: każde pole to obiekt `{value, source, evidence}` (EKSTRAKCJA.md §2). Dopiski w tabelach
>    („(ze zdjęcia)”, „(zgaduję: zdjęcie)”, „(zgaduję: model)”) = `source` `photo` / `photo_guess` / `model_guess`.
>    Usunięte sekcje z formatem dopisków, regexem i przykładowym JSON-em w starym formacie.
> 2. Pola z danych platformy (cena, cena z opłatą, polubienia, „Dodane”, stan z formularza, firma, waluta/kraj,
>    tłumaczony opis) wypełnia baza, nie AI – oznaczone **[P]**. Pola, których nie zbieramy – **[–]** (RODO / brak
>    w danych). Sygnały niewidziane w danych platformy – **⚠**.
> 3. Parametry „z wiedzy o modelu” – **tabela `models` raz na model**, nie przy każdej ofercie (oznaczone w sekcji).
> 4. Segmenty do statystyk: wg `device_type`: `ipad`, `android_tablet`, `windows_2in1`, `e_reader`, `kids_tablet`, `graphics_tablet`, `pen_display`, `noname` – każdy osobno (tablet graficzny Wacom to inny rynek niż iPad); `for_parts`, `locked` osobno; zestaw z klawiaturą/rysikiem jako cecha (`accessories_bundle_value`). Klucz porównawczy bez zmian.
> 5. `condition_grade` – wspólna skala dla wszystkich kategorii (także laptopów); `summary_pl` tylko dla Snipera.
> 6. Laptopy 2 w 1 (Surface Pro itd.) mogą być w laptopach 3580 i w tabletach 3728 – osobne oferty mają
>    osobne ID; w statystykach `windows_2in1` porównujemy z segmentem „2 w 1” laptopów.

# Specyfikacja ekstrakcji: Tablety (rynek wtórny, PL)

## 0. Zasady ogólne dla AI

1. Źródła informacji, w kolejności ważności:
   - **T – tekst**: tytuł, opis, parametry z formularza platformy (stan, marka, model, pamięć, cena, polubienia itd.),
   - **Z – zdjęcia** ogłoszenia,
   - **M – model**: Twoja wiedza o specyfikacji danego modelu tabletu.
2. Każda wartość ma pochodzenie (`source`, EKSTRAKCJA.md §2); w tabelach zapisane dopiskami:
   - brak dopisku → podane wprost w tekście,
   - `(ze zdjęcia)` → widoczne jednoznacznie na zdjęciu (pudełko, zrzut ustawień, napis na obudowie),
   - `(zgaduję: zdjęcie)` → oszacowane na podstawie zdjęć,
   - `(zgaduję: model)` → wywnioskowane z wiedzy o modelu.
3. Kolumna **Źródła** mówi, skąd wolno wypełnić pole. Jeśli jest tylko `T`, **nie zgaduj** – brak informacji → `null`.
4. Tekst ma pierwszeństwo przed zdjęciem, zdjęcie przed wiedzą o modelu. Sprzeczność → wartość z mocniejszego dowodu + flaga `inconsistency` z opisem.
5. **Normalizuj oczywiste błędy formularza** platformy (np. „Pamięć wbudowana: 256 MB” w nowoczesnym tablecie = 256 GB). Zapisz wartość poprawioną z dopiskiem `(zgaduję: model)` i odnotuj błąd w `platform_field_errors`.
6. Przy polach krytycznych (sekcje 3, 4, 5, 6) dodaj `evidence` – fragment tekstu lub opis tego, co widać na zdjęciu.
7. `false` z tekstu tylko przy wyraźnym zaprzeczeniu (np. „wylogowany z kont” → `google_frp_lock: false`).
8. Opis może być automatycznie przetłumaczony („Przetłumaczone przez Google”) – interpretuj sens i zaznacz `translated_description: true`. Ceny podane w opisie w obcej walucie zapisz osobno (sekcja 11).

## 2. Identyfikacja (klucz porównawczy cen)

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `device_type` | enum | T Z M | `ipad`, `android_tablet`, `windows_2in1` (np. Surface, HP Elite x2), `chromebook_tablet`, `e_reader` (Kindle, PocketBook), `kids_tablet`, `graphics_tablet` (tablet graficzny bez ekranu, np. Wacom Intuos), `pen_display` (z ekranem, np. Wacom Cintiq, XP-Pen), `noname`, `accessory_only`, `other` |
| `brand` | string | T Z | Apple, Samsung, Lenovo, Xiaomi, Huawei, Microsoft, HP, Realme, Oppo, OnePlus, Amazon, Wacom itd. Wolno zgadywać ze zdjęcia |
| `model_family` | string | T Z M | np. „iPad Pro 11”, „Galaxy Tab S10 Ultra”, „Tab M10 FHD Plus”. **Wolno zgadywać** ze zdjęć (aparaty, ramki, port, przyciski, logo, pudełko) i z parametrów podanych w tekście (np. przekątna + marka) |
| `generation` | string/null | T Z M | np. „3. generacja (2021)”, „2. generacja”; przy iPadach kluczowe |
| `release_year` | int/null | T M | |
| `variant` | string/null | T Z M | `base`, `plus`, `pro`, `ultra`, `fe`, `lite`, `air`, `mini`, `kids` |
| `model_number` | string/null | T Z | np. A2377, SM-X920, TB-X606F; z pudełka/zrzutu → `(ze zdjęcia)` |
| `chip` | string/null | T M | np. M1, M2, A16, Snapdragon 8 Gen 3, Dimensity 9300+, Helio P22, i7-1185G7 |
| `storage_gb` | int/null | T Z M | z modelu tylko, gdy model ma jedną wersję pamięci; ze zdjęcia z pudełka lub ustawień |
| `ram_gb` | int/null | T Z M | z modelu tylko, gdy dana pamięć ma jedną wersję RAM |
| `cellular` | bool/null | T Z M | Wi-Fi vs LTE/5G. Ze zdjęcia: tacka SIM, pasek anteny, oznaczenia na pudełku. **Duży wpływ na cenę** |
| `cellular_type` | enum/null | T Z M | `lte`, `5g`, `none` |
| `color` | string/null | T Z | oficjalna nazwa koloru, jeśli rozpoznawalna |
| `region_version` | string/null | T Z M | z numeru modelu, języka pudełka, kraju sprzedawcy |
| `model_source_conflict` | string/null | T Z M | rozbieżność między tytułem, opisem, formularzem, specyfikacją i zdjęciami |

**Klucz porównawczy** = `brand + model_family + generation + variant + storage_gb + cellular`.

**Rozpoznawanie modelu – zasady:**
- Tytuł ogólny („Tablet Lenovo 10,3"”, „Samsung tablet”) → rozpoznaj model z parametrów, zdjęć, ikon systemowych, kształtu obudowy i aparatów.
- Zdjęcie/specyfikacja wskazuje na **lepszy** model, generację lub wariant niż tytuł → `model_underlabeled`.
- Wskazuje na **gorszy** → `model_overlabeled`.
- Rozróżniaj generacje o podobnym wyglądzie (np. kolejne generacje iPada Pro/Air) – jeśli nie da się ich odróżnić ze zdjęć, a tekst nie podaje generacji, wpisz `null` w `generation` i zaznacz to w `confidence_overall`.

---

## 3. Blokady i konta (KRYTYCZNE)

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `icloud_lock` | bool/null | T Z | „blokada aktywacji”, „Find My”; zrzut ekranu blokady → `(ze zdjęcia)` |
| `google_frp_lock` | bool/null | T | „wylogowany z kont”, „usunięte konto Google” → `false` |
| `samsung_account_lock` | bool/null | T | |
| `mdm_lock` | bool/null | T Z | tablet szkolny/firmowy, „zarządzany przez organizację”, naklejki inwentarzowe na obudowie |
| `microsoft_account_or_bios_password` | bool/null | T | Windows 2w1 |
| `factory_reset_screen_on_photo` | bool | Z | ekran powitalny („hello”, „Witaj”) – oznacza reset, ale **nie wyklucza blokady aktywacji**; nie ustawiaj na tej podstawie `icloud_lock: false` |
| `accounts_logged_out` | bool/null | T Z | |
| `simlock` | bool/null | T | tylko wersje cellular |
| `kids_mode_or_parental_controls` | bool/null | T Z | „tryb dla dzieci”, aplikacje kontroli rodzicielskiej na zrzucie – sygnał, że używało go dziecko |

---

## 4. Stan techniczny / sprawność

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `fully_functional` | bool/null | T | „wszystko działa idealnie”. **Nie zgaduj** |
| `screen_on_photo` | bool | Z | zdjęcie włączonego ekranu – słaby dowód sprawności, zapisz w `evidence` |
| `for_parts` | bool | T Z | |
| `faults` | array | T Z | enum poniżej |
| `display_defects` | array | T Z | `dead_pixels`, `pressure_marks`, `backlight_bleed`, `burn_in`, `lines`, `ghost_touch`, `discoloration`, `delamination`, `blooming` |
| `chassis_bent` | bool/null | T Z | wygięta obudowa (cienkie tablety); ze zdjęcia z boku → `(zgaduję: zdjęcie)` |
| `liquid_damage` | bool/null | T Z | |
| `stylus_works` | bool/null | T | |
| `keyboard_works` | bool/null | T | |

**Enum `faults`:** `screen_cracked`, `back_cracked`, `camera`, `speaker`, `microphone`, `charging_port`, `wifi_bluetooth`, `cellular`, `buttons`, `face_id`, `touch_id`, `fingerprint`, `stylus_charging`, `smart_connector`, `overheating`, `random_restarts`, `slow_performance`, `battery_drain`, `battery_swollen`, `other`.

---

## 5. Bateria

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `battery_health_pct` | int/null | T Z | „bateria ponad 85%” → `85` + odnotuj „ponad” w `evidence`. **Nie zgaduj z wieku** |
| `battery_health_is_lower_bound` | bool/null | T | „ponad X%” → `true` |
| `battery_cycles` | int/null | T Z | |
| `battery_replaced` | bool/null | T | |
| `battery_life_claim` | string/null | T | np. „trzyma 2 dni” |
| `battery_capacity_mah` | int/null | T M | pojemność fabryczna modelu |

Deklaracja 100% przy urządzeniu używanym ponad kilka miesięcy bez zrzutu ekranu → dodaj `evidence` z uwagą „brak potwierdzenia”, bez flagi.

---

## 6. Stan wizualny, naprawy

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `condition_platform` | string/null | T | np. „Nowy z metką”, „Nowy bez metki”, „Bardzo dobry”, „Dobry”, „Zadowalający” |
| `condition_grade` | enum | T Z | `new_sealed`, `new_open`, `A_plus`, `A`, `B`, `C`, `D`, `unknown` |
| `screen_condition` | enum/null | T Z | `perfect`, `micro_scratches`, `visible_scratches`, `deep_scratches`, `cracked` |
| `body_condition` | enum/null | T Z | `perfect`, `micro_scratches`, `scuffs`, `dents`, `bent`, `cracked` |
| `corners_condition` | enum/null | T Z | `perfect`, `scuffs`, `dents` – aluminiowe rogi często zdradzają upadki |
| `screen_protector` | bool/null | T Z | szkło/folia może ukrywać rysy |
| `used_in_case` | bool/null | T Z | |
| `repaired` | bool/null | T | |
| `replaced_parts` | array | T Z | `screen`, `battery`, `charging_port`, `back`, `other` |
| `replacement_quality` | enum/null | T | `original_service`, `original_part`, `aftermarket`, `unknown` |
| `photo_quality` | enum | Z | `good`, `poor`, `stock` |
| `device_visible_on_photos` | bool | Z | `false`, gdy na zdjęciach widać tylko pudełko lub akcesoria |

Zasady: zdjęcia stockowe lub samo pudełko → stan tylko z tekstu + odpowiednia flaga. Słabe zdjęcia nie dają oceny lepszej niż `A (zgaduję: zdjęcie)`.

---

## 7. Parametry (wolno uzupełniać z wiedzy o modelu)

> *(poprawka Claude 2026-10-12)* **Tabela `models`:** pola z `M` w kolumnie źródeł wypełniamy raz na model (po kluczu porównawczym),
> nie przy każdej ofercie. W ofercie AI zapisuje je tylko, gdy sprzedawca podał je w tekście albo widać je na
> zdjęciu (np. inny ekran po naprawie) – to informacja o egzemplarzu, ważniejsza niż wartość z tabeli modeli.

| Pole | Typ | Źródła |
|---|---|---|
| `screen_size_inch` | float/null | T M |
| `display_type` | enum/null | T M (`lcd`, `oled`, `amoled`, `mini_led`, `e_ink`) |
| `screen_resolution` | string/null | T M |
| `refresh_rate_hz` | int/null | T M |
| `charging_port` | enum/null | T Z M (`usb_c`, `lightning`, `micro_usb`) |
| `microsd_slot` | bool/null | T M |
| `headphone_jack` | bool/null | T M |
| `biometrics` | enum/null | T M (`face_id`, `touch_id`, `fingerprint`, `face_unlock`, `none`) |
| `speakers_count` | int/null | T M |
| `ip_rating` | string/null | T M |
| `cameras_rear` | int/null | T Z M |
| `stylus_support` | string/null | T M (np. „Apple Pencil 2”, „Apple Pencil USB-C”, „S Pen”, „brak”) |
| `stylus_in_box_by_default` | bool/null | M (np. S Pen dołączany fabrycznie do części Galaxy Tab) |
| `keyboard_connector` | enum/null | T M (`smart_connector`, `pogo_pins`, `bluetooth_only`, `none`) |
| `os` | enum | T Z M (`ipados`, `android`, `windows`, `chromeos`, `fire_os`, `harmonyos`, `other`) |
| `os_version` | string/null | T Z (nie zgaduj z modelu) |
| `updates_end_year` | int/null | M |
| `google_services` | bool/null | T M (Huawei – brak usług Google) |
| `desktop_mode` | bool/null | M (Samsung DeX, Stage Manager) |

Gdy wersje modelu się różnią (np. Wi-Fi vs 5G, różny RAM), a nie wiesz, którą masz – `null`.

---

## 8. Akcesoria i zestaw (duży wpływ na wartość tabletów)

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `original_box` | bool/null | T Z | |
| `charger_included` | bool/null | T Z | |
| `cable_included` | bool/null | T Z | |
| `stylus_included` | bool/null | T Z | |
| `stylus_model` | string/null | T Z M | oryginalny vs zamiennik |
| `stylus_original` | bool/null | T Z | |
| `keyboards` | array | T Z | każda klawiatura jako obiekt: `{ "brand": "", "model": "", "original": bool, "layout": "", "backlit": bool, "touchpad": bool }` |
| `keyboard_layout` | enum/null | T Z | `qwerty_pl`, `qwerty_us`, `qwerty_uk`, `qwertz_de`, `azerty_fr`, `nordic`, `other`. Ze zdjęcia: układ klawiszy Y/Z, A/Q, dodatkowe litery → `(ze zdjęcia)` lub `(zgaduję: zdjęcie)`. **Układ inny niż PL/US obniża wartość dla kupującego w Polsce** |
| `case_included` | bool/null | T Z | |
| `case_original` | bool/null | T Z | |
| `other_accessories` | array | T Z | |
| `accessories_claimed_value` | string/null | T | wartość akcesoriów podana przez sprzedawcę, z walutą |

---

## 9. Gwarancja i dokumenty

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `warranty_type` | enum/null | T | `manufacturer`, `seller`, `apple_care`, `samsung_care`, `none` |
| `warranty_until` | date/null | T Z | |
| `device_age` | string/null | T | „mam go nieco ponad rok” |
| `warranty_likely_active` | bool/null | T M | wiek urządzenia < okres gwarancji producenta w kraju zakupu → `(zgaduję: model)` |
| `purchase_place` | string/null | T Z | |
| `purchase_country` | string/null | T Z | gwarancja może być ograniczona do kraju zakupu |
| `proof_of_purchase` | enum/null | T Z | `invoice_vat`, `invoice_margin`, `receipt`, `none` |
| `refurbished` | bool | T | |

---

## 10. Klasa użytkowa (dla dopasowania do klienta)

> *(poprawka Claude 2026-10-12)* Całość z wiedzy o modelu → tabela `models`.

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `use_case_fit` | array | M | `media`, `kids`, `study_notes`, `drawing`, `office_laptop_replacement`, `gaming`, `reading`, `business` |
| `performance_tier` | enum | M | `budget`, `mid`, `high`, `flagship` |
| `laptop_replacement_ready` | bool/null | T M | klawiatura z touchpadem + tryb desktop/Windows |

---

## 11. Sprzedawca, transakcja i sygnały platformy

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `seller_type` **[P]** | enum/null | T | `private`, `business` |
| `seller_country` **[P]** | string/null | T | z lokalizacji w opisie (np. nazwa miasta), waluty, języka tytułu |
| `location_city` **[–]** | string/null | T | |
| `translated_description` **[P]** | bool | T | |
| `title_foreign_language` | bool | T | tytuł nieprzetłumaczony (np. rumuński, szwedzki) – mniej wyświetleń w PL |
| `price_pln` **[P]** | float | T | cena przedmiotu |
| `price_total_pln` **[P]** | float/null | T | z opłatą platformy |
| `price_currency_converted` **[P]** | bool | T | |
| `price_in_description` | string/null | T | np. „9990 SEK” |
| `price_description_vs_platform_mismatch` | bool/null | T | cena z opisu po przeliczeniu wyraźnie różna od ceny w platformie – opisz w `evidence` |
| `retail_price_claimed` | string/null | T | „cena nowego ok. 16 990 SEK” |
| `favorites_count` **[P]** | int/null | T | |
| `recent_offers_signal` ⚠ | int/null | T | np. „5 osób złożyło ostatnio ofertę” |
| `listing_age` **[P]** | string/null | T | |
| `promoted_listing` ⚠ | bool/null | T | „Podbity” |
| `buyer_protection` **[–]** | bool/null | T | |
| `electronics_verification_available` ⚠ | bool/null | T | |
| `pickup_possible` | bool/null | T | |
| `shipping_paid_by_buyer` | bool/null | T | |
| `negotiable` | bool/null | T | „cena do uzgodnienia”, „zaproponuj cenę” |
| `reason_for_sale` | string/null | T | „zmieniłam pracę”, „mało używany” |
| `urgency` | bool/null | T | „przy szybkim zakupie” |
| `platform_field_errors` | array | T | np. `["Pamięć wbudowana: 256 MB → 256 GB"]` |

---

## 12. Czerwone flagi (`red_flags`)

- `stock_photos`
- `box_only_photos` – na zdjęciach tylko pudełko, brak urządzenia
- `activation_lock_unverified` – iPad bez potwierdzenia wylogowania z iCloud
- `mdm_suspected` – tablet szkolny/firmowy
- `foreign_keyboard_layout` – QWERTZ, AZERTY itp.
- `fake_specs_noname` – tani noname z nierealną specyfikacją (np. „12 GB RAM, 5G, 10 rdzeni” za kilkaset zł)
- `kids_heavy_use` – tryb dziecięcy, ślady intensywnego użytkowania
- `third_party_accessories_as_original`
- `price_description_vs_platform_mismatch`
- `contact_outside_platform`
- `model_overlabeled`
- `inconsistency`

## 13. Sygnały okazji (`opportunity_signals`)

- `model_underlabeled` – lepszy model/generacja/wariant niż w tytule
- `vague_title` – tytuł bez modelu (mniej trafień w wyszukiwaniu)
- `title_foreign_language`
- `accessories_bundle_value` – oryginalne klawiatury, rysik, etui o dużej wartości
- `cellular_not_advertised` – wersja LTE/5G niewymieniona w tytule
- `warranty_likely_active`
- `high_battery_health`
- `full_set`
- `high_demand` – dużo polubień/ofert
- `negotiable`
- `urgent_sale`
- `wrong_category`

---

## 14. Format wyjściowy

*(poprawka Claude 2026-10-12)* JSON zgodny ze schematem z EKSTRAKCJA.md §2, grupy sekcji jak wyżej + rdzeń §3. Przykład w starym formacie usunięty.

## 15. Wagi do analizy (po Twojej stronie, nie dla AI)

1. **Blokady i konta** (iCloud, FRP, MDM) – dyskwalifikujące
2. **Model + generacja + wariant + pamięć + Wi-Fi/cellular** – wyznacza cenę rynkową
3. **Stan ekranu i obudowy** (w tym wygięcie)
4. **Sprawność i bateria**
5. **Akcesoria** (oryginalna klawiatura i rysik potrafią stanowić dużą część wartości) i **układ klawiatury**
6. **Gwarancja**
7. **Sygnały popytu** i kraj sprzedawcy (koszt i czas wysyłki)
