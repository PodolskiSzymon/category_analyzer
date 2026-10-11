# Category Analyzer

Pełny research rynku jednej kategorii Vinted (start: laptopy): zebranie wszystkich ofert (podział wyszukiwania
po cenie, żeby ominąć limit wyników), zapis lokalny w SQLite, śledzenie zmian cen i sprzedaży (po jakiej cenie
i po jakim czasie), wyciąganie parametrów (CPU/GPU/RAM…) i raporty cen rynkowych. Docelowo zasila ocenę AI
w Vinted Sniperze prawdziwymi cenami sprzedaży.

**Stan: planowanie – kod analizatora jeszcze nie istnieje.**

* Kontekst dla Claude i kolejność prac: [`CLAUDE.md`](CLAUDE.md)
* Architektura, schemat bazy, etapy: [`ARCHITEKTURA.md`](ARCHITEKTURA.md)
* Repo zawiera kopię Vinted Snipera (`sniper/`) – reużywane moduły: sesja przez proxy, ekstrakcja ofert, AI.
  Jego opis: [`SNIPER_README.md`](SNIPER_README.md), kontekst: [`sniper/CONTEXT.md`](sniper/CONTEXT.md).
