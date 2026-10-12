> **Kategoria Vinted 3661 (telefony komórkowe).** Wersja użytkownika z poprawkami Claude pod analizę rynku
> (2026-10-12). Zasady wspólne – **`EKSTRAKCJA.md`** (ma pierwszeństwo). Zmiany względem wersji użytkownika:
> 1. Format: każde pole to obiekt `{value, source, evidence}` (EKSTRAKCJA.md §2). Dopiski w tabelach
>    („(ze zdjęcia)”, „(zgaduję: zdjęcie)”, „(zgaduję: model)”) = `source` `photo` / `photo_guess` / `model_guess`.
>    Usunięte sekcje z formatem dopisków, regexem i przykładowym JSON-em w starym formacie.
> 2. Pola z danych platformy (cena, cena z opłatą, polubienia, „Dodane”, stan z formularza, firma, waluta/kraj,
>    tłumaczony opis) wypełnia baza, nie AI – oznaczone **[P]**. Pola, których nie zbieramy – **[–]** (RODO / brak
>    w danych). Sygnały niewidziane w danych platformy – **⚠**.
> 3. Parametry „z wiedzy o modelu” – **tabela `models` raz na model**, nie przy każdej ofercie (oznaczone w sekcji).
> 4. Segmenty do statystyk: `working` (sprawny, bez blokad), `for_parts`, `locked` (jakakolwiek blokada z §3) – ceny liczymy osobno; `refurbished` jako cecha. Klucz porównawczy bez zmian; `color` poza kluczem (do osobnej analizy wpływu koloru).
> 5. `condition_grade` – wspólna skala dla wszystkich kategorii (także laptopów); `summary_pl` tylko dla Snipera.
> 6. Usunięte z AI: `seller_rating`, `seller_reviews_count`, `seller_account_age`, `location_city` (RODO).

# Specyfikacja ekstrakcji: Telefony komórkowe (rynek wtórny, PL)

## 0. Zasady ogólne dla AI

1. Źródła informacji, w kolejności ważności:
   - **T – tekst**: tytuł, opis, parametry z formularza platformy,
   - **Z – zdjęcia** ogłoszenia,
   - **M – model**: Twoja wiedza o specyfikacji danego modelu.
2. Każda wartość ma pochodzenie (`source`, EKSTRAKCJA.md §2); w tabelach zapisane dopiskami:
   - brak dopisku → podane wprost w tekście,
   - `(ze zdjęcia)` → widoczne jednoznacznie na zdjęciu (np. zrzut ekranu ustawień, wyraźne pęknięcie),
   - `(zgaduję: zdjęcie)` → oszacowane na podstawie zdjęć, bez pewności,
   - `(zgaduję: model)` → wywnioskowane z wiedzy o modelu, nie potwierdzone w ogłoszeniu.
3. Kolumna **Źródła** w tabelach mówi, z jakich źródeł wolno wypełnić dane pole. Jeśli pole ma tylko `T`, **nie wolno go zgadywać** – brak informacji → `null`.
4. Tekst ma pierwszeństwo przed zdjęciem, a zdjęcie przed wiedzą o modelu. Jeśli źródła są sprzeczne (np. opis mówi „stan idealny”, a na zdjęciu widać rysę), wpisz wartość z mocniejszego dowodu i dodaj flagę `inconsistency` z opisem sprzeczności.
5. Przy polach krytycznych (sekcje 3, 4, 5, 7) dodaj `evidence` – krótki fragment tekstu albo opis tego, co widać na zdjęciu (np. „zdjęcie 3: pęknięcie w lewym górnym rogu ekranu”).
6. `false` z tekstu tylko gdy sprzedawca wprost zaprzecza (np. „bez blokad” → `icloud_lock: false`).
7. Język opisu jest potoczny – interpretuj synonimy (np. „bateria 87%”, „kondycja 87”, „BH 87” = `battery_health_pct: 87`).

---

## 2. Identyfikacja modelu (klucz porównawczy cen)

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `brand` | string | T Z | logo na zdjęciu; wolno zgadywać po wyglądzie → `(zgaduję: zdjęcie)` |
| `model_family` | string | T Z | np. „iPhone 13”, „Galaxy S23”. **Wolno zgadywać ze zdjęć** → `(zgaduję: zdjęcie)`. Wskazówki: układ i liczba aparatów, kształt wyspy aparatów, wycięcie/notch/Dynamic Island, ramki ekranu, przyciski, port (Lightning vs USB-C), materiał ramki, kolor dostępny tylko dla danej generacji. Pudełko lub zrzut „Informacje” → `(ze zdjęcia)` |
| `variant` | enum | T Z | `base`, `mini`, `plus`, `pro`, `pro_max`, `ultra`, `fe`, `lite`, `edge`, `5g`, `other`. **Wolno zgadywać ze zdjęć** → `(zgaduję: zdjęcie)`. Wskazówki: liczba obiektywów, teleobiektyw, LiDAR, rozmiar względem dłoni/przedmiotów w kadrze, slot na rysik, kolory dostępne tylko w danym wariancie |
| `model_source_conflict` | string/null | T Z | gdy model/wariant z tekstu różni się od rozpoznanego na zdjęciu: opisz różnicę, np. „opis: iPhone 13, zdjęcie: 3 obiektywy + LiDAR → 13 Pro” |
| `model_raw` | string | T | dokładnie tak, jak w ogłoszeniu |
| `model_number` | string/null | T Z | np. A2633, SM-S911B; często widoczny na pudełku lub zrzucie ustawień |
| `storage_gb` | int | T Z | ze zdjęcia: pudełko, zrzut ustawień. **Nie zgaduj z modelu** (modele mają kilka wersji pamięci) |
| `ram_gb` | int/null | T Z M | z modelu tylko, gdy dany wariant pamięci ma jedną wersję RAM |
| `color` | string/null | T Z | wolno zgadywać ze zdjęć; używaj oficjalnej nazwy koloru producenta, np. „Sierra Blue (zgaduję: zdjęcie)” |
| `region_version` | enum/null | T Z M | `eu`, `us`, `asia`, `china`, `global`, `unknown`; z numeru modelu, brak tacki SIM na zdjęciu, chińskie napisy |
| `chipset` | string/null | T M | np. Exynos vs Snapdragon wg numeru modelu i regionu |
| `release_year` | int/null | M | rok premiery modelu – tabela `models` |

**Klucz porównawczy** = `brand + model_family + variant + storage_gb`. Błąd w wariancie (Pro vs Pro Max) lub pamięci psuje analizę cen – przy każdej niepewności zaznacz to w `confidence_overall`.

**Rozpoznawanie modelu ze zdjęć – zasady:**
- Jeśli tekst nie podaje modelu albo jest ogólny („iPhone”, „Samsung Galaxy”, „telefon”), rozpoznaj model i wariant ze zdjęć.
- Jeśli tekst i zdjęcie się różnią, wpisz wartość ze zdjęcia z dopiskiem `(zgaduję: zdjęcie)`, wypełnij `model_source_conflict` i dodaj flagę `inconsistency`.
- Jeśli zdjęcie wskazuje na **lepszy** model niż w opisie (np. opis „13”, zdjęcie „13 Pro”), dodaj sygnał okazji `model_underlabeled`.
- Jeśli zdjęcie wskazuje na **gorszy** model niż w opisie, dodaj czerwoną flagę `model_overlabeled`.
- Parametry z wiedzy o modelu (sekcja 8) wyliczaj na podstawie modelu rozpoznanego, także zgadywanego.
- `storage_gb` i `ram_gb` nie są widoczne z zewnątrz – ze zdjęcia tylko z pudełka lub zrzutu ekranu.

---

## 3. Blokady i legalność (KRYTYCZNE – NIE ZGADYWAĆ)

Te pola wolno wypełnić tylko z tekstu lub z jednoznacznego zrzutu ekranu. **Nigdy z wiedzy o modelu ani z domysłów.**

| Pole | Typ | Źródła | Synonimy / uwagi |
|---|---|---|---|
| `icloud_lock` | bool/null | T Z | „blokada aktywacji”, „Find My”, „Znajdź mój iPhone”, „zablokowany na koncie”; zdjęcie ekranu „iPhone zablokowany dla właściciela” |
| `google_frp_lock` | bool/null | T Z | „blokada konta Google”, „FRP” |
| `simlock` | bool/null | T | „tylko Play/Orange/T-Mobile/Plus”; `false` przy „bez simlocka” |
| `simlock_operator` | string/null | T Z | logo operatora na obudowie/ekranie startowym to tylko poszlaka – dodaj do `evidence`, ale nie ustawiaj `simlock` |
| `mdm_lock` | bool/null | T Z | telefon firmowy, „zarządzany przez organizację”, „Remote Management” |
| `imei_blacklisted` | bool/null | T | „zastrzeżony”, „zablokowany IMEI” |
| `imei_provided` | bool | T Z | IMEI w opisie lub widoczny na zdjęciu |
| `bootloader_unlocked_or_root` | bool/null | T Z | „root”, „custom ROM”; ekran ostrzeżenia przy starcie |
| `knox_tripped` | bool/null | T | Samsung |

---

## 4. Stan techniczny / sprawność

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `fully_functional` | bool/null | T | **nie zgaduj** – ze zdjęcia nie da się ocenić sprawności |
| `for_parts` | bool | T Z | „na części”, „uszkodzony”; zdjęcie roztrzaskanego telefonu |
| `faults` | array | T Z | enum poniżej; ze zdjęć tylko usterki widoczne (pęknięcia, defekty ekranu) |
| `face_id_works` | bool/null | T | |
| `fingerprint_works` | bool/null | T | |
| `true_tone_works` | bool/null | T Z | |
| `liquid_damage` | bool/null | T Z | ze zdjęcia: zaparowany obiektyw, korozja w porcie – zawsze jako `(zgaduję: zdjęcie)` |
| `display_defects` | array | T Z | `burn_in`, `green_line`, `dead_pixels`, `ghost_touch`, `discoloration`, `spots`, `backlight_bleed`; burn-in najlepiej widać na zdjęciu białego/szarego ekranu |

**Enum `faults`:** `screen_cracked`, `back_glass_cracked`, `camera_lens_cracked`, `camera_not_working`, `camera_blurry_or_vibrating`, `speaker`, `earpiece`, `microphone`, `charging_port`, `wireless_charging`, `wifi_bluetooth`, `no_service`, `nfc`, `buttons`, `vibration`, `proximity_sensor`, `overheating`, `random_restarts`, `bootloop`, `battery_swollen`, `other`.

`battery_swollen` ze zdjęcia: odstający ekran lub tył, szczelina przy ramce.

---

## 5. Bateria

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `battery_health_pct` | int/null | T Z | ze zrzutu ekranu ustawień → `(ze zdjęcia)`. **Nie zgaduj z wieku telefonu** |
| `battery_cycles` | int/null | T Z | iPhone 15+ pokazuje cykle w ustawieniach |
| `battery_service_message` | bool/null | T Z | „Serwis”, „wymagany serwis baterii” |
| `battery_replaced` | bool/null | T Z | zrzut „Nieznana część” przy baterii |
| `battery_replacement_original` | bool/null | T Z | |
| `battery_capacity_mah` | int/null | T M | pojemność fabryczna modelu |

**Progi interpretacji (iPhone):** ≥90% bardzo dobra, 85–89% dobra, 80–84% przeciętna, <80% do wymiany.

---

## 6. Stan wizualny (główne pole do oceny ze zdjęć)

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `condition_platform` | string/null | T | wartość z formularza platformy |
| `condition_grade` | enum | T Z | skala poniżej |
| `screen_condition` | enum | T Z | `perfect`, `micro_scratches`, `visible_scratches`, `deep_scratches`, `cracked` |
| `body_condition` | enum | T Z | `perfect`, `micro_scratches`, `scuffs`, `dents`, `cracked_back` |
| `frame_condition` | enum/null | T Z | `perfect`, `scuffs`, `dents`, `paint_chips` |
| `camera_lens_condition` | enum/null | T Z | `perfect`, `scratched`, `cracked` |
| `screen_protector_on_photo` | bool/null | Z | szkło ochronne może ukrywać rysy – dodaj do `evidence` |
| `had_screen_protector` | bool/null | T | „od nowości w szkle i etui” |
| `had_case` | bool/null | T Z | |
| `photo_quality` | enum | Z | `good` (ostre, różne kąty, włączony ekran), `poor` (rozmyte, ciemne, jeden kąt), `stock` (zdjęcia producenta) |

**Skala `condition_grade`:**
- `new_sealed` – nowy, zafoliowany
- `new_open` – nowy, otwarty, nieużywany
- `A_plus` – jak nowy, brak śladów
- `A` – minimalne mikrorysy widoczne pod światło
- `B` – widoczne rysy/otarcia, bez pęknięć
- `C` – mocne ślady, wgniecenia, głębokie rysy
- `D` – pęknięcia / uszkodzenia
- `unknown`

**Zasady oceny ze zdjęć:**
- Słabe zdjęcia nie mogą dawać oceny lepszej niż `A (zgaduję: zdjęcie)`.
- Zdjęcia stockowe → stan wyłącznie z tekstu, a `photo_quality: stock` i flaga `stock_photos`.
- Brak zdjęcia którejś strony (np. tyłu) → odnotuj w `evidence`.

---

## 7. Naprawy i części

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `repaired` | bool/null | T Z | |
| `replaced_parts` | array | T Z | `screen`, `battery`, `back_glass`, `camera`, `charging_port`, `housing`, `other` |
| `replacement_quality` | enum/null | T Z | `original_service`, `original_part`, `aftermarket`, `unknown` |
| `unknown_part_message` | bool/null | T Z | zrzut iOS „nieznana część” / „nieoryginalny wyświetlacz” |
| `aftermarket_screen_signs` | bool/null | Z | grubsze ramki, inny odcień bieli, szara czerń zamiast idealnej (LCD zamiast OLED) – zawsze `(zgaduję: zdjęcie)` |
| `opened_before` | bool/null | T | „nie był rozkręcany” → `false` |

---

## 8. Parametry i funkcje (wolno uzupełniać z wiedzy o modelu)

> *(poprawka Claude 2026-10-12)* **Tabela `models`:** pola z `M` w kolumnie źródeł wypełniamy raz na model (po kluczu porównawczym),
> nie przy każdej ofercie. W ofercie AI zapisuje je tylko, gdy sprzedawca podał je w tekście albo widać je na
> zdjęciu (np. inny ekran po naprawie) – to informacja o egzemplarzu, ważniejsza niż wartość z tabeli modeli.

| Pole | Typ | Źródła |
|---|---|---|
| `display_type` | enum | T M → `OLED`, `LCD`, `other` |
| `screen_size_inch` | float/null | T M |
| `refresh_rate_hz` | int/null | T M |
| `has_5g` | bool/null | T M |
| `has_esim` | bool/null | T M |
| `esim_only` | bool/null | T Z M (iPhone 14+ US bez tacki SIM; ze zdjęcia: brak tacki na boku) |
| `dual_sim` | enum/null | T M → `physical_dual`, `sim_plus_esim`, `single` |
| `has_nfc` | bool/null | T M |
| `microsd_slot` | bool/null | T M |
| `headphone_jack` | bool/null | T Z M |
| `ip_rating` | string/null | T M |
| `wireless_charging` | bool/null | T M |
| `fast_charging_w` | int/null | T M |
| `camera_main_mp` | int/null | T M |
| `camera_count_rear` | int/null | T Z M |
| `has_telephoto` | bool/null | T M |
| `stylus_support` | bool/null | T M |
| `stylus_included` | bool/null | T Z |

Przy wartościach z modelu uwzględnij wariant i region (np. ta sama nazwa modelu może mieć różne chipsety lub brak 5G w części wersji). Jeśli wersje się różnią, a nie wiesz, którą masz – `null`.

---

## 9. Oprogramowanie

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `os` | enum | T Z M | `ios`, `android`, `harmonyos`, `other` |
| `os_version` | string/null | T Z | ze zrzutu ekranu; **nie zgaduj z modelu** (zależy od aktualizacji) |
| `max_supported_os` | string/null | M | ostatnia wersja systemu, jaką model dostanie |
| `updates_end_year` | int/null | M | szacowany koniec wsparcia aktualizacji |
| `google_services` | bool/null | T M | Huawei po 2019 – brak usług Google |
| `rom_type` | enum/null | T Z M | `global`, `eu`, `china`, `custom`; ze zdjęcia: chińskie aplikacje/napisy |
| `factory_reset_done` | bool/null | T Z | zdjęcie ekranu powitalnego „Witaj” |
| `polish_language` | bool/null | T Z | |

---

## 10. Gwarancja i dokumenty

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `warranty_type` | enum/null | T | `manufacturer`, `seller`, `apple_care`, `none` |
| `warranty_until` | date/null | T Z | zrzut ekranu sprawdzenia gwarancji |
| `warranty_months_left` | int/null | T Z | |
| `purchase_date` | date/null | T Z | ze zdjęcia paragonu/faktury |
| `purchase_place` | string/null | T Z | |
| `proof_of_purchase` | enum/null | T Z | `invoice_vat`, `invoice_margin`, `receipt`, `none` |
| `refurbished` | bool | T | „odnowiony”, „refurbished” |
| `refurbished_grade` | string/null | T | |
| `statutory_warranty_rekojmia` | bool/null | T | sprzedaż firmowa |
| `return_possible` | bool/null | T | |

---

## 11. Zestaw

| Pole | Typ | Źródła |
|---|---|---|
| `original_box` | bool/null | T Z |
| `box_imei_matches` | bool/null | T |
| `charger_included` | bool/null | T Z |
| `cable_included` | bool/null | T Z |
| `case_included` | bool/null | T Z |
| `screen_protector_included` | bool/null | T Z |
| `other_accessories` | array | T Z |

Ze zdjęcia: tylko to, co faktycznie widać w kadrze; pudełko na zdjęciu nie oznacza, że jest w nim ładowarka.

---

## 12. Sprzedawca i transakcja (tylko z tekstu i danych platformy)

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `seller_type` **[P]** | enum | T | `private`, `business` |
| `seller_rating` **[–]** | float/null | T | |
| `seller_reviews_count` **[–]** | int/null | T | |
| `seller_account_age` **[–]** | string/null | T | |
| `location_city` **[–]** | string/null | T | |
| `pickup_possible` | bool/null | T | |
| `shipping_available` | bool/null | T | |
| `buyer_protection` **[–]** | bool/null | T | na Vinted zawsze przy zakupie przez platformę |
| `negotiable` | bool/null | T | „do negocjacji”, „cena do dogadania” |
| `trade_possible` | bool/null | T | „zamiana” |
| `reason_for_sale` | string/null | T | |
| `urgency` | bool/null | T | „pilne”, „szybka sprzedaż” |
| `price_pln` **[P]** | int | T | |
| `price_original_pln` ⚠ | int/null | T | cena przekreślona – niewidziana w danych; obniżki z historii `observations` |

---

## 13. Czerwone flagi (`red_flags`, array)

- `stock_photos` – zdjęcia producenta zamiast prawdziwych
- `no_photos_of_screen_on`
- `photos_hide_parts` – brak zdjęcia tyłu, ramki lub ekranu
- `photos_mismatch` – kolor/model na zdjęciu inny niż w opisie
- `contact_outside_platform` – „pisz na WhatsApp”, numer/e-mail w opisie
- `shipping_only_no_pickup` przy bardzo niskiej cenie
- `new_seller_account`
- `vague_description`
- `lock_mentioned`
- `parts_listed_as_working`
- `unknown_origin`
- `imei_refused`
- `inconsistency` – sprzeczność między tytułem, opisem, parametrami i zdjęciami
- `model_overlabeled` – na zdjęciu słabszy model/wariant niż w opisie

## 14. Sygnały okazji (`opportunity_signals`, array)

- `urgent_sale`
- `negotiable`
- `price_dropped`
- `poor_listing_good_device` – słaby tytuł/zdjęcia, ale dobry stan
- `misspelled_model`
- `model_underlabeled` – na zdjęciu lepszy model/wariant niż w opisie (sprzedawca może nie znać wartości telefonu)
- `wrong_category`
- `active_warranty`
- `high_battery_health`
- `full_set`
- `always_in_case_and_glass`
- `undervalued_by_seller` – sprzedawca nie wymienia atutów, które wynikają z modelu (np. 5G, OLED, teleobiektyw)

---

## 15. Format wyjściowy

*(poprawka Claude 2026-10-12)* JSON zgodny ze schematem z EKSTRAKCJA.md §2 (obiekty `value/source/evidence`), grupy sekcji jak wyżej + rdzeń §3. Przykład w starym formacie usunięty.

## 17. Wagi do analizy (po Twojej stronie, nie dla AI)

1. **Blokady / legalność** – dyskwalifikujące
2. **Model + wariant + pamięć** – wyznacza cenę rynkową
3. **Sprawność i usterki**
4. **Bateria** (szczególnie iPhone)
5. **Oryginalność części**, zwłaszcza ekranu
6. **Stan wizualny**
7. **Gwarancja i dowód zakupu**
8. **Zestaw**
9. **Funkcje** (5G, eSIM, NFC, dual SIM) – głównie do filtrowania pod konkretnego klienta
