> **Kategoria Vinted 3025 (konsole i gry).** Wersja użytkownika z poprawkami Claude pod analizę rynku
> (2026-10-12). Zasady wspólne – **`EKSTRAKCJA.md`** (ma pierwszeństwo). Zmiany względem wersji użytkownika:
> 1. Format: każde pole to obiekt `{value, source, evidence}` (EKSTRAKCJA.md §2). Dopiski w tabelach
>    („(ze zdjęcia)”, „(zgaduję: zdjęcie)”, „(zgaduję: model)”) = `source` `photo` / `photo_guess` / `model_guess`.
>    Usunięte sekcje z formatem dopisków, regexem i przykładowym JSON-em w starym formacie.
> 2. Pola z danych platformy (cena, cena z opłatą, polubienia, „Dodane”, stan z formularza, firma, waluta/kraj,
>    tłumaczony opis) wypełnia baza, nie AI – oznaczone **[P]**. Pola, których nie zbieramy – **[–]** (RODO / brak
>    w danych). Sygnały niewidziane w danych platformy – **⚠**.
> 3. Parametry „z wiedzy o modelu” – **tabela `models` raz na model**, nie przy każdej ofercie (oznaczone w sekcji).
> 4. Segmenty do statystyk: `home_console`, `hybrid`, `handheld_pc`, `handheld_console`, `retro_original`, `mini_classic` (wg `device_type`), osobno `retro_clone` / `clone_type` (klony nie mieszają się z oryginałami), `accessory_only` (poza statystykami konsol), `for_parts`; bundle z grami/padami jako cecha (`bundle_value`). Klucz porównawczy bez zmian; `edition` w kluczu tylko dla edycji limitowanych (zwykłe = `standard`).
> 5. `condition_grade` – wspólna skala dla wszystkich kategorii (także laptopów); `summary_pl` tylko dla Snipera.
> 6. Kategoria 3025 obejmuje pewnie też gry i akcesoria – `device_type: accessory_only` / gry poza
>    statystykami konsol (do sprawdzenia po pierwszym przejściu, ile ich jest).

# Specyfikacja ekstrakcji: Konsole do gier (rynek wtórny, PL)

## 0. Zasady ogólne dla AI

1. Źródła informacji, w kolejności ważności:
   - **T – tekst**: tytuł, opis, parametry z formularza platformy (stan, marka, platforma, cena, liczba polubień itd.),
   - **Z – zdjęcia** ogłoszenia,
   - **M – model**: Twoja wiedza o specyfikacji danego modelu konsoli.
2. Każda wartość ma pochodzenie (`source`, EKSTRAKCJA.md §2); w tabelach zapisane dopiskami:
   - brak dopisku → podane wprost w tekście,
   - `(ze zdjęcia)` → widoczne jednoznacznie na zdjęciu (naklejka z numerem modelu, ekran ustawień, pudełko),
   - `(zgaduję: zdjęcie)` → oszacowane na podstawie zdjęć,
   - `(zgaduję: model)` → wywnioskowane z wiedzy o modelu.
3. Kolumna **Źródła** mówi, skąd wolno wypełnić pole. Jeśli jest tylko `T`, **nie zgaduj** – brak informacji → `null`.
4. Tekst ma pierwszeństwo przed zdjęciem, zdjęcie przed wiedzą o modelu. Sprzeczność → wartość z mocniejszego dowodu + flaga `inconsistency` z opisem.
5. **Sprawdzaj spójność tytułu, opisu i specyfikacji z wiedzą o modelu.** Jeśli podane parametry pasują do innego modelu niż nazwa w tytule (np. procesor z innej generacji urządzenia), opisz to w `model_source_conflict`.
6. Przy polach krytycznych (sekcje 3, 4, 5, 6) dodaj `evidence` – fragment tekstu lub opis tego, co widać na zdjęciu.
7. `false` z tekstu tylko przy wyraźnym zaprzeczeniu (np. „bez dryfu” → `stick_drift: false`).
8. Opis może być automatycznie przetłumaczony (np. dopisek „Przetłumaczone przez Google”) – interpretuj sens, nie dosłowne sformułowania, i zaznacz `translated_description: true`.

## 2. Identyfikacja (klucz porównawczy cen)

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `device_type` | enum | T Z M | `home_console`, `hybrid` (Switch), `handheld_console` (PS Vita, 3DS), `handheld_pc` (Steam Deck, ROG Ally, Legion Go, MSI Claw), `retro_original`, `retro_clone`, `mini_classic` (SNES Classic, PS Classic), `accessory_only`, `other` |
| `manufacturer` | string | T Z | Sony, Microsoft, Nintendo, Valve, Asus, Lenovo, MSI, Sega, Atari, Anbernic, Miyoo, Powkiddy itd. Wolno zgadywać ze zdjęcia |
| `model_family` | string | T Z | np. „PlayStation 5”, „Xbox One”, „Switch”, „Game Boy Advance”, „ROG Ally X”. Wolno zgadywać ze zdjęcia |
| `revision` | string/null | T Z M | wersja sprzętowa: `fat`, `slim`, `pro`, `S`, `X`, `oled`, `lite`, `v1`, `v2`, `sp`, `micro`, `digital`, `disc` itd. Wolno zgadywać ze zdjęcia (kształt obudowy, porty, przyciski, logo) |
| `model_number` | string/null | T Z | np. 1540, 1681, CFI-1216A, CUH-2216B, HAC-001, AGB-001. Z naklejki/pudełka → `(ze zdjęcia)` |
| `serial_number_visible` | bool | Z | numer seryjny widoczny na zdjęciu (istotne np. dla rozpoznania wczesnych partii Switcha) |
| `edition` | string/null | T Z | edycja limitowana / bundle, np. „Minecraft Limited Edition”, „Spider-Man”. Wolno zgadywać ze zdjęcia po malowaniu fabrycznym |
| `is_limited_edition` | bool/null | T Z M | |
| `color` | string/null | T Z | oficjalna nazwa koloru, jeśli rozpoznawalna |
| `storage_gb` | int/null | T Z M | z modelu tylko, gdy dany model/rewizja ma jedną wersję pamięci (np. Series S biała 512); inaczej `null` |
| `storage_upgraded` | bool/null | T Z | wymieniony/dołożony dysk |
| `region` | enum/null | T Z M | `pal`, `ntsc_u`, `ntsc_j`, `region_free`, `unknown`; dla retro z naklejek i pudełek |
| `model_source_conflict` | string/null | T Z M | opis rozbieżności między tytułem, opisem, specyfikacją i zdjęciami |

**Klucz porównawczy** = `manufacturer + model_family + revision + storage_gb + edition`.

Uwaga dla AI: tytuł bywa mylący (słowa-klucze dodawane dla wyszukiwania, np. nazwa marki popularnej konsoli w tytule urządzenia innej marki). Zawsze ustal, **czym urządzenie faktycznie jest**, na podstawie specyfikacji i zdjęć.

**Rozpoznawanie ze zdjęć – zasady:**
- Tekst ogólny („konsola”, „Xbox”, „gameboy”) → rozpoznaj model i rewizję ze zdjęć.
- Zdjęcie wskazuje na **lepszy/rzadszy** model lub edycję niż opis → sygnał okazji `model_underlabeled`.
- Zdjęcie wskazuje na **gorszy** model → flaga `model_overlabeled`.
- Zdjęcie pokazuje klona zamiast oryginału → flaga `clone_marketed_as_original`.
- Pojemności dysku nie da się zobaczyć na obudowie – tylko naklejka, pudełko, ekran ustawień lub wiedza o modelu (gdy jest jedna wersja).

---

## 3. Oryginalność i legalność (KRYTYCZNE)

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `is_original` | bool/null | T Z M | oryginalny sprzęt producenta vs klon/podróbka |
| `clone_type` | enum/null | T Z | `emulator_handheld` („21000 gier w jednej konsoli”), `famiclone`, `fake_brand`, `reproduction_shell`, `other` |
| `preloaded_games_count` | int/null | T | duża liczba wgranych gier (setki/tysiące) prawie zawsze oznacza nielicencjonowane kopie |
| `cartridges_original` | bool/null | T Z | retro: oryginalne kartridże vs bootlegi (etykieta, czcionka, płytka widoczna na zdjęciu) |
| `console_banned` | bool/null | T | ban z usług online (Nintendo, Xbox Live, PSN) |
| `account_included` | bool/null | T | sprzedaż razem z kontem (ryzyko odzyskania konta przez poprzedniego właściciela) |
| `account_logout_confirmed` | bool/null | T | „wylogowane konto”, „przywrócona do ustawień fabrycznych” |
| `modded_cfw_jailbreak` | bool/null | T Z | „przerobiona”, „chip”, „jailbreak”, „CFW”, „odblokowana” |
| `firmware_version` | string/null | T Z | wersja oprogramowania systemowego (dla części kupujących ma znaczenie) |
| `bios_or_windows_password` | bool/null | T | handheld PC: hasło BIOS/konta Microsoft |
| `windows_activated` | bool/null | T Z M | handheld PC |
| `proof_of_purchase` | enum/null | T Z | `invoice_vat`, `invoice_margin`, `receipt`, `none` |
| `origin_story` | string/null | T | np. „dostałem w prezencie”, „wygrana w konkursie” |

---

## 4. Stan techniczny / sprawność

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `fully_functional` | bool/null | T | „w pełni sprawna”, „wszystko działa”. **Nie zgaduj** |
| `tested_on_photo` | bool | Z | zdjęcie włączonej konsoli/ekranu z grą lub menu – słaby dowód sprawności, zapisz w `evidence` |
| `for_parts` | bool | T Z | „na części”, „uszkodzona”, „nie włącza się” |
| `faults` | array | T Z | enum poniżej |
| `disc_drive_works` | bool/null | T | „czyta płyty” → `true` |
| `overheating` | bool/null | T | „nie przegrzewa się” → `false` |
| `fan_noise` | enum/null | T | `quiet`, `normal`, `loud` |
| `hdmi_port_ok` | bool/null | T Z | częsta usterka PS4/PS5/Xbox |
| `display_defects` | array | T Z | handheldy: `dead_pixels`, `scratches`, `cracked`, `burn_in`, `backlight_bleed`, `yellowing`, `dust_under_screen` |
| `screen_type` | enum/null | T Z M | `original`, `ips_mod`, `backlit_mod`, `oled`, `lcd` (retro: IPS mod widać po jasnym, nasyconym obrazie) |
| `battery_health` | string/null | T Z | handheldy i handheld PC: %, godziny pracy, „trzyma X h” |
| `battery_swollen` | bool/null | T Z | wybrzuszona obudowa, odstający ekran/tył |
| `battery_compartment_corrosion` | bool/null | T Z | retro na baterie AA – korozja styków |
| `save_battery` | enum/null | T | retro kartridże: `works`, `dead`, `replaced` |

**Enum `faults`:** `no_power`, `no_video`, `hdmi_port`, `disc_drive`, `disc_eject`, `overheating`, `loud_fan`, `random_shutdowns`, `blue_light`, `red_ring`, `error_codes`, `wifi_bluetooth`, `usb_ports`, `power_supply`, `cartridge_slot`, `game_card_reader`, `buttons`, `speaker`, `headphone_jack`, `charging_port`, `screen`, `touchscreen`, `stick_drift`, `joycon_rail`, `dock`, `coil_whine`, `other`.

---

## 5. Naprawy, modyfikacje i otwieranie

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `opened_before` | bool/null | T Z | wymiana pasty, czyszczenie, naprawy → `true`; zerwana plomba gwarancyjna na zdjęciu |
| `maintenance_done` | array | T | `thermal_paste` (podaj markę, jeśli jest), `cleaning`, `fan_replaced`, `liquid_metal`, `other` |
| `repaired` | bool/null | T | |
| `replaced_parts` | array | T Z | `power_supply`, `hdmi_port`, `disc_drive`, `hdd_ssd`, `fan`, `shell`, `screen`, `battery`, `buttons`, `sticks`, `other` |
| `cosmetic_mods` | array | T Z | `custom_paint` („lakier w sprayu”), `reshell`, `skin_sticker`, `custom_buttons`, `led_mod`, `other` |
| `mods_affect_value` | enum/null | T Z M | `positive` (np. IPS w retro handheldzie, większa bateria), `neutral`, `negative` (np. malowanie sprayem, amatorska naprawa) |

---

## 6. Kontrolery

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `controllers_count` | int/null | T Z | wolno policzyć ze zdjęcia → `(ze zdjęcia)` |
| `controllers_original` | bool/null | T Z | oryginalne vs zamienniki (logo, kształt, wykończenie) |
| `controllers_model` | string/null | T Z | np. DualSense, DualShock 4 v2, Xbox Series, Joy-Con, Pro Controller |
| `controller_edition` | string/null | T Z | np. edycja limitowana pasująca do konsoli |
| `stick_drift` | bool/null | T | „bez dryfu” → `false`; joysticki Halla → zapisz w `evidence` |
| `controller_batteries` | string/null | T Z | akumulatory, stacje ładujące, „trzymają 2 dni” |

---

## 7. Specyfikacja (głównie handheld PC i nowsze konsole)

> *(poprawka Claude 2026-10-12)* **Tabela `models`:** pola z `M` w kolumnie źródeł wypełniamy raz na model (po kluczu porównawczym),
> nie przy każdej ofercie. W ofercie AI zapisuje je tylko, gdy sprzedawca podał je w tekście albo widać je na
> zdjęciu (np. inny ekran po naprawie) – to informacja o egzemplarzu, ważniejsza niż wartość z tabeli modeli.

| Pole | Typ | Źródła |
|---|---|---|
| `cpu_apu` | string/null | T M |
| `gpu` | string/null | T M |
| `ram_gb` | int/null | T M |
| `storage_type` | string/null | T M (HDD, SSD NVMe, eMMC) |
| `microsd_slot` | bool/null | T M |
| `screen_size_inch` | float/null | T M |
| `screen_resolution` | string/null | T M |
| `refresh_rate_hz` | int/null | T M |
| `touchscreen` | bool/null | T M |
| `os` | string/null | T Z M (Windows 11, SteamOS, Android, Linux, fabryczny system konsoli) |
| `has_disc_drive` | bool/null | T Z M |
| `max_resolution_output` | string/null | M (np. 1080p, 1440p, 4K) |
| `wifi_standard` | string/null | T M |
| `ports` | array | T M (np. Thunderbolt 4, USB-C, HDMI) |
| `backward_compatibility` | string/null | M |
| `still_supported_online` | bool/null | M (czy działają oficjalne usługi online/sklep) |

Przy wartościach z modelu uwzględnij rewizję. Gdy rewizje się różnią, a nie wiesz, którą masz – `null`.

---

## 8. Stan wizualny

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `condition_platform` | string/null | T | wartość z formularza (np. „Nowy z metką”, „Nowy bez metki”, „Bardzo dobry”, „Dobry”, „Zadowalający”) |
| `condition_grade` | enum | T Z | `new_sealed`, `new_open`, `A_plus`, `A`, `B`, `C`, `D`, `unknown` (definicje jak w specyfikacji telefonów) |
| `body_condition` | enum/null | T Z | `perfect`, `micro_scratches`, `scuffs`, `scratches`, `dents`, `cracked` |
| `plastic_yellowing` | bool/null | Z | retro: zażółcenie plastiku (`(zgaduję: zdjęcie)` – zależy od oświetlenia) |
| `dirt_or_dust` | bool/null | Z | brud w kratkach, kurz, ślady naklejek |
| `sealed_packaging_visible` | bool/null | Z | folia fabryczna widoczna na zdjęciu |
| `photo_quality` | enum | Z | `good`, `poor`, `stock` |
| `photos_are_own` | bool/null | Z | zdjęcia z własnego otoczenia (blat, podłoga, dywan) vs katalogowe/promocyjne |

Zasady: zdjęcia stockowe → stan tylko z tekstu + flaga `stock_photos`. Słabe zdjęcia nie dają oceny lepszej niż `A (zgaduję: zdjęcie)`. Rozbieżność „nowa/nieużywana” w opisie vs używany stan w formularzu → `inconsistency`.

---

## 9. Zestaw

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `original_box` | bool/null | T Z | |
| `box_condition` | enum/null | T Z | `mint`, `good`, `damaged` – ważne przy edycjach limitowanych i retro |
| `complete_in_box` | bool/null | T Z | retro: CIB (pudełko + instrukcja + wkładki) |
| `manuals` | bool/null | T Z | |
| `power_supply_included` | bool/null | T Z M | zewnętrzny zasilacz (np. Xbox One fat) – bez niego konsola bezużyteczna |
| `hdmi_cable_included` | bool/null | T Z | |
| `dock_included` | bool/null | T Z | Switch, handheld PC |
| `charger_included` | bool/null | T Z | handheldy; zapisz moc, jeśli podana |
| `case_included` | bool/null | T Z | |
| `games_included` | array | T Z | tytuły; ze zdjęcia po okładkach/kartridżach (`(ze zdjęcia)` gdy czytelne) |
| `games_count` | int/null | T Z | |
| `games_format` | enum/null | T Z | `physical`, `digital_on_account`, `preinstalled`, `mixed` |
| `other_accessories` | array | T Z | stacje ładujące, akumulatory, podstawki, słuchawki, kamera, karty pamięci |

---

## 10. Gwarancja

| Pole | Typ | Źródła |
|---|---|---|
| `warranty_type` | enum/null | T (`manufacturer`, `seller`, `none`) |
| `warranty_until` | date/null | T Z |
| `purchase_date` / `device_age` | string/null | T („konsola ma 3 lata”) |
| `purchase_place` | string/null | T Z |
| `warranty_void_risk` | bool/null | T Z (otwierana, zerwana plomba, modyfikacje) |

---

## 11. Sprzedawca, transakcja i sygnały platformy

| Pole | Typ | Źródła | Uwagi |
|---|---|---|---|
| `seller_type` **[P]** | enum/null | T | `private`, `business` |
| `seller_country` **[P]** | string/null | T | wnioskuj z opisu („dostawa w Danii”), przeliczenia waluty, tłumaczenia |
| `translated_description` **[P]** | bool | T | |
| `price_currency_converted` **[P]** | bool | T | „przeliczone na twoją walutę” → sprzedawca zagraniczny (dłuższa wysyłka, inny rynek cenowy) |
| `price_pln` **[P]** | float | T | cena przedmiotu |
| `price_total_pln` **[P]** | float/null | T | z opłatą platformy |
| `favorites_count` **[P]** | int/null | T | liczba polubień – popyt i łatwość odsprzedaży |
| `recent_offers_signal` ⚠ | int/null | T | np. „8 osób złożyło ostatnio ofertę” |
| `listing_age` **[P]** | string/null | T | np. „Dodane 20 godz.” |
| `buyer_protection` **[–]** | bool/null | T | ochrona kupującego platformy |
| `electronics_verification_available` ⚠ | bool/null | T | płatna weryfikacja elektroniki oferowana przez platformę |
| `pickup_possible` | bool/null | T | |
| `negotiable` | bool/null | T | „zaproponuj cenę” dostępne, „do negocjacji” |
| `reason_for_sale` | string/null | T | |
| `urgency` | bool/null | T | |
| `listing_style` | enum/null | T Z | `private_casual`, `commercial_ad` (emotki, ✔️, hasła marketingowe, „idealny prezent”) |

---

## 12. Czerwone flagi (`red_flags`)

- `stock_photos` – zdjęcia promocyjne/katalogowe zamiast własnych
- `clone_marketed_as_original` – klon sprzedawany pod nazwą oryginalnej konsoli/marki
- `preloaded_pirated_games` – setki/tysiące wgranych gier
- `dropshipping_or_reseller` – styl reklamowy, „nowa, zapakowana” klony, wysyłka z zagranicy
- `title_spec_mismatch` – nazwa w tytule nie pasuje do podanej specyfikacji
- `sealed_high_value_no_receipt` – drogi, nowy sprzęt bez dowodu zakupu
- `new_vs_used_inconsistency` – opis „nowa/nieużywana”, formularz „używany”
- `account_included` – sprzedaż z kontem
- `console_banned`
- `no_power_supply` – brak niezbędnego zasilacza
- `amateur_mods` – malowanie sprayem, amatorskie lutowanie
- `no_working_proof` – brak zdjęcia włączonej konsoli przy sprzęcie używanym
- `contact_outside_platform`
- `model_overlabeled`
- `inconsistency`

## 13. Sygnały okazji (`opportunity_signals`)

- `model_underlabeled` – rzadsza rewizja/edycja niż w opisie
- `rare_or_limited_edition`
- `bundle_value` – dodatkowe pady, gry, akcesoria warte więcej niż różnica w cenie
- `high_demand` – dużo polubień/ofert w krótkim czasie (szybka odsprzedaż)
- `maintained` – wymieniona pasta, czyszczenie (dbałość)
- `complete_in_box`
- `positive_mods` – np. ekran IPS w retro handheldzie
- `firmware_of_interest` – wersja oprogramowania poszukiwana przez część kupujących
- `misspelled_or_vague_title` – słaby tytuł, mniej wyświetleń
- `wrong_category`
- `negotiable`
- `urgent_sale`
- `active_warranty`

---

## 14. Format wyjściowy

*(poprawka Claude 2026-10-12)* JSON zgodny ze schematem z EKSTRAKCJA.md §2, grupy sekcji jak wyżej + rdzeń §3. Przykład w starym formacie usunięty.

## 15. Wagi do analizy (po Twojej stronie, nie dla AI)

1. **Oryginalność** (klon vs oryginał, zgodność tytułu ze specyfikacją) – dyskwalifikujące
2. **Model + rewizja + pamięć + edycja** – wyznacza cenę rynkową
3. **Sprawność** (napęd, HDMI, przegrzewanie, bateria w handheldach)
4. **Blokady kont, bany, modyfikacje systemu**
5. **Kompletność** (zasilacz, pady, dock, gry)
6. **Stan wizualny i modyfikacje kosmetyczne**
7. **Dowód zakupu i gwarancja** (szczególnie handheld PC i nowe generacje)
8. **Sygnały popytu** (polubienia, oferty) – do oceny szybkości odsprzedaży

## 16. Rozbiórka – co da się wyjąć i sprzedać osobno *(Claude 2026-10-14, do strategii z ATRYBUTY.md §6)*

| Konsola | RAM | Dysk wbudowany | Do wyjęcia |
|---|---|---|---|
| PS5 / Slim / Pro | lutowany | lutowany | dodatkowy dysk M.2 NVMe w slocie rozszerzeń (1–2 TB, z radiatorem) |
| PS4 / Slim / Pro | lutowany | 2,5" SATA, wymienny | dysk (HDD mało wart, SSD więcej) |
| Xbox Series X / S | lutowany | lutowany | karta rozszerzeń Seagate / WD (1–2 TB) |
| Xbox One / S / X | lutowany | 2,5" SATA, wymienny | dysk |
| Switch / Lite / OLED / Switch 2 | lutowany | lutowany | karta microSD (Switch 2: microSD Express) |
| Steam Deck / ROG Ally / Legion Go | lutowany | M.2 2230 NVMe, wymienny | dysk 2230 (drogi, rzadki format) |

Kart SIM w konsolach nie ma. Największa wartość do wydzielenia zwykle w zestawie: gry fizyczne, dodatkowe pady
(DualSense Edge, Pro Controller, Joy-Cony), akcesoria (PS VR2, stacje ładujące) – pola `games_included`,
`controllers_*`, `other_accessories`, sygnał `bundle_value`. Dodatkowe pola: `expansion_storage`
(typ + pojemność: m2_nvme / xbox_expansion_card / microsd / sata_2_5), `internal_storage_replaced`.
