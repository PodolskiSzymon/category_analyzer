# Ekstrakcja parametrów – zasady wspólne dla wszystkich kategorii

Kategorie (catalog_id z cURL użytkownika 2026-10-12): **laptopy 3580** (`ATRYBUTY.md`), **telefony 3661**
(`ATRYBUTY_TELEFONY.md`), **konsole 3025** (`ATRYBUTY_KONSOLE.md`), **tablety 3728** (`ATRYBUTY_TABLETY.md`).
Specyfikacje kategorii to wersje użytkownika z poprawkami Claude pod analizę rynku; ten plik ma pierwszeństwo,
gdy coś się różni (format, źródła, podział platforma/AI).

## 1. Trzy źródła danych – kto co wypełnia

| Źródło | Co daje | Kto wypełnia |
|---|---|---|
| **Platforma (baza)** | cena, cena z opłatą, polubienia, wyświetlenia, stan Vinted, marka/model z formularza (`item_box`, atrybuty), „Dodane”, firma, waluta i kraj sprzedawcy, tłumaczony opis (`is_localized`), historia cen i sprzedaż | crawler / details / resolver – **nigdy AI** |
| **Oferta (tekst + zdjęcia)** | fakty o tym konkretnym egzemplarzu: model jeśli podany, pamięć, stan, usterki, blokady, bateria, zestaw, gwarancja, naprawy, flagi | reguły (`extract`), potem AI dla braków |
| **Model (wiedza o modelu)** | specyfikacja wspólna dla wszystkich egzemplarzy modelu: ekran, chip, 5G, NFC, IP, TGP, rok premiery, koniec aktualizacji | **tabela `models` – raz na model**, nie przy każdej ofercie |

Dlaczego: pola „wolno uzupełniać z wiedzy o modelu” (np. 18 pól sekcji 8 telefonów) są takie same dla tysięcy
ofert tego samego modelu. Pytanie AI o nie przy każdej ofercie mnoży koszt i daje niespójne odpowiedzi (raz
120 Hz, raz 60 Hz dla tego samego modelu). W ofercie AI zapisuje je tylko wtedy, gdy sprzedawca podał je w tekście
albo są widoczne na zdjęciu (np. inny ekran po naprawie) – to są informacje o egzemplarzu.

## 2. Format odpowiedzi AI

Każde pole to obiekt `value` + `source` (+ `evidence` przy polach krytycznych), wymuszany schematem JSON
(jak ocena AI w Sniperze):

```json
"storage_gb":         {"value": 256, "source": "description"},
"battery_health_pct": {"value": 86, "source": "photo", "evidence": "zdjęcie 4: zrzut ustawień, kondycja 86%"},
"variant":            {"value": "pro", "source": "photo_guess", "evidence": "3 obiektywy + LiDAR"},
"icloud_lock":        {"value": null, "source": "none"}
```

| `source` | Znaczenie | Dopisek w specyfikacjach kategorii / dla człowieka | Waga w medianie |
|---|---|---|---|
| `title`, `description`, `attribute` | podane wprost | brak dopisku | 1.0 |
| `photo` | **odczytane** ze zdjęcia: naklejka znamionowa, zrzut ustawień / Menedżera urządzeń / „Informacje o systemie”, pudełko – `evidence` obowiązkowe | „(ze zdjęcia)” | 1.0 |
| `model_guess` | wywnioskowane z modelu (numer modelu → GPU, panel) | „(zgaduję: model)” | 0.9 |
| `photo_guess` | **rozpoznane** ze zdjęcia bez napisu (wygląd obudowy, układ portów, stan wizualny) – `evidence` obowiązkowe | „(zgaduję: zdjęcie)” | 0.85 |
| `none` | szukano, nie ma | – | – |

**Decyzja użytkownika 2026-10-24:** zgadnięte wartości tylko niewiele mniej ważne od pewnych (0.9 / 0.85), a odczytane
ze zdjęcia tak samo pewne jak tekst. Przykład: opis nie podaje GPU, ale na zdjęciu jest naklejka „GeForce RTX 3060”
albo zrzut Menedżera urządzeń → `{"value": "RTX 3060", "source": "photo", "evidence": "zdjęcie 3: naklejka na
obudowie"}`; jeśli widać tylko obudowę Legiona 5 i AI wnioskuje GPU z modelu → `model_guess`. Wagi startowe – do
kalibracji: gdy później ta sama wartość wyjdzie pewnie (z opisu innej oferty tego modelu, ze sprzedaży), liczymy,
jak często zgadywanie trafiało, i obniżamy wagę tylko wtedy, gdy trafia rzadko.

Zasady wspólne (szczegóły w plikach kategorii):
1. Tekst > zdjęcie > model. Sprzeczność → wartość z mocniejszego dowodu + flaga `inconsistency`.
2. Pola oznaczone „tylko T” (blokady, sprawność, kondycja baterii, gwarancja) – **nie zgadywać**; brak → `none`.
3. `false` tylko przy wyraźnym zaprzeczeniu w tekście („bez blokad”).
4. Oczywiste błędy formularza (256 MB → 256 GB) – poprawić ze źródłem `model_guess`, oryginał w
   `platform_field_errors`.
5. Opisy przetłumaczone automatycznie – interpretować sens (to, że opis jest tłumaczony, wiemy z platformy).
6. `summary_pl` – tylko dla Snipera (pojedyncze oferty), nie w masowej ekstrakcji (koszt tokenów).

## 3. Wspólny rdzeń (każda kategoria) – do statystyk przekrojowych

| Pole | Wartości | Po co |
|---|---|---|
| `category` | `laptop` / `phone` / `console` / `tablet` | |
| `segment` | per kategoria (np. `gaming`, `macbook`; telefony: `working` / `for_parts` / `locked`) | ceny liczymy w segmencie |
| `config_key` | klucz porównawczy kategorii (np. `apple|iphone 13|pro|256`) | grupowanie cen |
| `config_key_confidence` | najniższa waga źródła wśród pól klucza | waga oferty w medianie |
| `condition_grade` | `new_sealed`, `new_open`, `A_plus`, `A`, `B`, `C`, `D`, `unknown` (jedna skala dla wszystkich kategorii, także laptopów) | wpływ stanu na cenę |
| `for_parts` | bool | osobny segment |
| `locked` | bool/null – jakakolwiek blokada (iCloud, FRP, MDM, BIOS, konto, ban, simlock) | osobny segment / dyskwalifikacja |
| `faults` | lista (enum kategorii) | |
| `battery_health_pct` | int/null (laptopy, telefony, tablety, handheldy) | |
| `warranty_until` / `proof_of_purchase` | | |
| `bundle_complete` | bool/null – komplet wg kategorii (ładowarka; pudełko; pady; klawiatura/rysik) | |
| `red_flags`, `opportunity_signals` | listy (wspólne nazwy, gdzie się da) | |
| `confidence_overall` | `high` / `medium` / `low` | |

Skala `condition_grade`: `new_sealed` nowy zafoliowany · `new_open` nowy otwarty, nieużywany · `A_plus` jak nowy,
brak śladów · `A` mikrorysy widoczne pod światło · `B` widoczne rysy/otarcia, bez pęknięć · `C` mocne ślady,
wgniecenia, głębokie rysy · `D` pęknięcia/uszkodzenia · `unknown`. Słabe zdjęcia nie dają oceny lepszej niż `A`
(`photo_guess`).

## 4. Czego nie zbieramy

* Nazwa, login, miasto, oceny, wiek konta sprzedawcy – RODO, a do analizy cen niepotrzebne (zostaje: firma tak/nie,
  kraj, waluta, opcjonalnie hash sprzedawcy do liczenia „ofert na sprzedawcę”).
* Sygnały, których nie widzieliśmy w danych platformy (⚠ do potwierdzenia, może tylko w aplikacji): „X osób
  złożyło ofertę”, cena przekreślona, „weryfikacja elektroniki”, „Podbity” – obniżki liczymy z własnej historii
  `observations`.

## 5. Kolejność wdrożenia

1. Reguły (`extract`) – rdzeń + identyfikacja modelu + najczęstsze pola tekstowe, z raportem pokrycia per pole.
2. Tabela `models` – lista modeli z bazy (po `config_key`), specyfikacja raz na model (AI wsadowo + ręczne poprawki).
3. AI wsadowo dla ofert, w których reguły nie ustaliły pól klucza lub pól krytycznych (cache po `content_hash`).
4. Zdjęcia – gdy tekst (reguły + AI na tekście) nie ustalił pól klucza (model, CPU, GPU, RAM, dysk) albo stanu:
   AI dostaje do 4 zdjęć (URL-e – pobiera je dostawca AI, bez proxy) i dla każdego pola mówi, czy je **odczytało**
   (`photo`), czy **zgaduje** (`photo_guess` / `model_guess`), z `evidence`. Póki oferta jest aktywna (zdjęcia
   usuniętych ofert znikają).
