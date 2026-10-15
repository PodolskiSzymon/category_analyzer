# Sesja Vinted: skąd program bierze ciastka (Playwright)

Dotyczy Snipera i analizatora – oba korzystają z `sniper/session.py` (`VintedSession`) i `sniper/proxy_relay.py`.
Analizator buduje sesję w `analyzer/config.py: build_session()`.

## 1. Po co ciastka

API Vinted (`api.vinted.pl/svc-catalogue/items`, `www.vinted.pl/api/v2/items/<id>/details/sidebar`) odpowiada
tylko „przeglądarce”, która ma ciastka sesji anonimowej (m.in. `anon_id`, `access_token_web`, ciastka zabezpieczeń
typu Datadome/Cloudflare) i nagłówki `x-csrf-token` / `x-anon-id`. Bez nich → **401/403**.
Nie logujemy się na konto – to sesja anonimowego gościa, taka sama jak przy otwarciu vinted.pl w przeglądarce.

## 2. Przebieg krok po kroku

```
start programu
  └─ load_state(): jest <log_dir>/session.json młodszy niż SNIPER_SESSION_MAX_AGE (360 min)?
        ├─ tak → ciastka + tokeny wczytane do httpx, przeglądarka NIE startuje
        └─ nie → nic; pierwsze zapytanie dostanie 401/403 i wywoła odświeżenie

zapytanie get_json()
  └─ 401/403 → refresh():
        1. wstrzymuje WSZYSTKIE zapytania (asyncio.Event), odświeża tylko jedno zadanie (licznik generacji)
        2. fetch_fresh_tokens() → headless Chromium (Playwright) przez proxy:
             a. lokalny przekaźnik proxy 127.0.0.1:<losowy port> (proxy_relay.py)
             b. nowy kontekst przeglądarki z user-agentem BROWSER_USER_AGENT (sniper/config.py)
             c. tryb lekki (SNIPER_BROWSER_LIGHT=true): blokowane obrazki, wideo, fonty i skrypty
                reklamowo-analityczne (lista hostów w session.py) – wizyta zamiast ~9 MB to ułamek
             d. wejście na https://www.vinted.pl/catalog, czekanie na DOMContentLoaded, potem do 2×wait_ms
                na "load" (przez proxy bywa >30 s – wtedy idziemy dalej), plus 4 s
             e. podsłuch żądań strony do /api/v2/ i api.vinted.pl → z ich nagłówków zabieramy
                x-csrf-token i x-anon-id
             f. brak tokenu w żądaniach → odczyt z <meta name="csrf-token"> na stronie
             g. context.cookies() → wszystkie ciastka; brak x-anon-id → bierzemy wartość ciastka anon_id
             h. przeglądarka zamknięta
        3. _apply(): ciastka i nagłówki wstawione do klienta httpx (stare usunięte)
        4. _save_state(): zapis do <log_dir>/session.json (tylko name/value/domain/path + tokeny)
        5. zapytanie ponowione raz; drugie 401/403 → SessionExpired
```

W logu wygląda to tak:

```
[AUTH] 403 dla https://api.vinted.pl/... - wstrzymuję HTTP i odświeżam sesję.
[AUTH] Playwright (headless) wchodzi na Vinted po świeże tokeny (proxy: TAK)...
[AUTH] Zdobyto N ciastek, nagłówki: x-anon-id, x-csrf-token
[AUTH] Ciastka: ...
[AUTH] Sesja httpx zaktualizowana (generacja 1).
```

## 3. Dlaczego przekaźnik proxy (`proxy_relay.py`)

Chromium nie umie wysłać loginu i hasła do proxy przy tunelowaniu HTTPS (`net::ERR_PROXY_AUTH_UNSUPPORTED`).
Dlatego:

```
Chromium ──(bez hasła)──> 127.0.0.1:<port>  ProxyRelay ──(+ Proxy-Authorization: Basic login:hasło)──> proxy (IPRoyal / Evomi) ──> vinted.pl
```

Przekaźnik czyta pierwszą odpowiedź proxy: **407** = złe dane logowania albo brak transferu na koncie →
`[RELAY] ... odrzucił dane logowania (407 ...)` i od razu `SessionExpired` (kolejne próby nic by nie dały).
Komunikat jest wspólny dla każdego dostawcy wpisanego w `SNIPER_PROXY_HOST` (IPRoyal, Evomi …).
Przekaźnik liczy też bajty przeglądarki (`[TRANSFER]`, pozycja `browser`).

Dane logowania: `SNIPER_PROXY_HOST=host:port` + `SNIPER_PROXY_AUTH=login:hasło` (koniecznie z dwukropkiem)
albo `SNIPER_PROXY_URL=http://login:hasło@host:port` → `sniper/config.py: build_proxy_url()`.

## 4. Ponowienia i limity czasu

| Zmienna (`sniper/.env`) | Domyślnie | Znaczenie |
|---|---|---|
| `SNIPER_REFRESH_ATTEMPTS` | 6 | prób w jednej serii odświeżania (rotacyjne proxy → każda próba = nowe IP) |
| `SNIPER_REFRESH_RETRY_DELAY` | 5 s | przerwa między próbami |
| `SNIPER_REFRESH_TIMEOUT` | 90 s | limit na jedną wizytę przeglądarki |
| `SNIPER_BROWSER_WAIT_MS` | 15000 | bazowy czas oczekiwania na stronę / żądanie z tokenem |
| `SNIPER_BROWSER_LIGHT` | true | blokowanie obrazków, fontów, reklam |
| `SNIPER_SESSION_MAX_AGE` | 360 min | do jakiego wieku `session.json` jest używany po restarcie (0 = zawsze przeglądarka) |
| `SNIPER_LOG_DIR` | `sniper/logs` | tam leży `session.json` |

Wszystkie próby nieudane → `SessionExpired("Odświeżenie sesji nie powiodło się po N próbach: ...")`.

## 5. Co jest zapisywane i bezpieczeństwo

* `session.json` = ciastka sesji anonimowej + `x-csrf-token` / `x-anon-id`. Nie zawiera hasła proxy ani danych konta.
  Mimo to traktować jak sekret (ktoś z tym plikiem „jest” naszą sesją do czasu jej wygaśnięcia) – leży w `logs/`,
  który nie trafia do repo.
* Ciastka są związane z IP, z którego je zdobyto. **Po zmianie dostawcy proxy** (np. IPRoyal → Evomi) pierwsze
  zapytanie zwykle dostaje jedno 403 i program sam odświeża sesję – to normalne. Można też po prostu usunąć
  `session.json` przed startem.
* Częste `[AUTH] 403` (np. kilka na godzinę) = Vinted nie lubi danych IP albo tempa – to sygnał do sprawdzenia
  jakości IP proxy, a nie błąd w ciastkach (`find /c "[AUTH] 403" data\analyzer.log` w analizatorze).

## 6. Koszt transferu

Jedna wizyta lekkiej przeglądarki jest dużo droższa niż zapytanie API (pełna wizyta bez blokowania ~9 MB; lekka – ułamek, dokładnie widać w `[TRANSFER]`, pozycja `browser`; zależy od tego, ile skryptów Vinted i
zabezpieczeń się pobierze). Dlatego sesja jest zapisywana na dysk i używana ponownie: restart programu nie kosztuje
wizyty, a przeglądarka startuje tylko wtedy, gdy Vinted naprawdę odrzuci ciastka.

## 7. Gdzie w kodzie

| Co | Plik / funkcja |
|---|---|
| wizyta przeglądarki, przechwytywanie tokenów | `sniper/session.py: _browse_vinted()` |
| przeglądarka przez przekaźnik, rozpoznanie 407 | `sniper/session.py: _browse_via_proxy()`, `sniper/proxy_relay.py: ProxyRelay` |
| całość jednej wizyty + log `[AUTH] Zdobyto ...` | `sniper/session.py: fetch_fresh_tokens()` |
| ponowienia | `VintedSession._fetch_with_retries()` |
| reakcja na 401/403 | `VintedSession.get_json()` → `refresh()` |
| zapis / odczyt z dysku | `VintedSession._save_state()` / `load_state()` |
| budowa sesji w analizatorze | `analyzer/config.py: build_session()` |
| budowa sesji w Sniperze | `sniper/__main__.py` |
