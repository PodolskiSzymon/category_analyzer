# Category Analyzer

Pełny research rynku jednej kategorii Vinted (start: laptopy): zebranie wszystkich ofert (podział wyszukiwania
po cenie, żeby ominąć limit wyników), zapis lokalny w SQLite, śledzenie zmian cen i sprzedaży (po jakiej cenie
i po jakim czasie), wyciąganie parametrów (CPU/GPU/RAM…) i raporty cen rynkowych. Docelowo zasila ocenę AI
w Vinted Sniperze prawdziwymi cenami sprzedaży.

**Stan: etap 1 (baza SQLite, planer partycji cen, crawler katalogu, migawki) gotowy i przetestowany na atrapie;
czeka na etap 0 – `python -m analyzer probe` u użytkownika (potwierdzenie limitu wyników i pól katalogu).**

```bash
python -m analyzer probe --catalog 3580     # etap 0: odpowiedzi Vinted -> data/probe/
python -m analyzer crawl --catalog 3580     # pełne przejście kategorii -> data/analyzer.db
python -m analyzer resolve                  # zniknięte oferty: sprzedana / usunięta
python -m analyzer status
```

* Kontekst dla Claude i kolejność prac: [`CLAUDE.md`](CLAUDE.md)
* Architektura, schemat bazy, etapy: [`ARCHITEKTURA.md`](ARCHITEKTURA.md)
* Repo zawiera kopię Vinted Snipera (`sniper/`) – reużywane moduły: sesja przez proxy, ekstrakcja ofert, AI.
  Jego opis: [`SNIPER_README.md`](SNIPER_README.md), kontekst: [`sniper/CONTEXT.md`](sniper/CONTEXT.md).
