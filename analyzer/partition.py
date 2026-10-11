"""Planer partycji: podział zakresu cen kategorii na przedziały, z których każdy mieści się w limicie wyników.

Granice: ⚠ nie wiemy jeszcze, czy price_from/price_to Vinted są włącznie. Dlatego sąsiednie partycje DZIELĄ
granicę ([lo, mid] i [mid, hi]) - oferta dokładnie na granicy trafia do obu (albo do jednej), a duplikaty
usuwa klucz = ID oferty. Gubimy ją tylko wtedy, gdy oba końce są wyłączne - probe to sprawdza.

Ceny liczymy w groszach (int), żeby podział nie zależał od błędów zaokrągleń float.
"""
from dataclasses import dataclass


def to_grosze(zl):
    return None if zl is None else int(round(zl * 100))


def to_zl(grosze):
    return None if grosze is None else grosze / 100


@dataclass(frozen=True)
class Range:
    lo: int                 # grosze, włącznie (⚠)
    hi: int = None          # grosze; None = bez górnej granicy

    @property
    def price_from(self):
        return to_zl(self.lo)

    @property
    def price_to(self):
        return to_zl(self.hi)

    def width(self):
        return None if self.hi is None else self.hi - self.lo

    def __str__(self):
        hi = "∞" if self.hi is None else f"{self.hi / 100:g}"
        return f"{self.lo / 100:g}-{hi} zł"


def initial_ranges(price_min, price_max, parts):
    """Równe przedziały [min, max] + otwarty ogon [max, ∞). Ogon dzielimy dopiero, gdy okaże się za duży."""
    lo, hi = to_grosze(price_min), to_grosze(price_max)
    parts = max(1, int(parts))
    edges = [lo + (hi - lo) * i // parts for i in range(parts + 1)]
    ranges = [Range(a, b) for a, b in zip(edges, edges[1:]) if b > a]
    return ranges + [Range(hi, None)]


def can_split(rng, min_width_zl):
    width = rng.width()
    return width is None or width >= 2 * to_grosze(min_width_zl)


def split(rng, prices_zl=None):
    """Podział na dwie partycje o wspólnej granicy.

    prices_zl - ceny ofert widzianych w partycji (pierwsza strona): granica = ich mediana, jeśli leży wewnątrz
    przedziału (rynki są skupione - mediana dzieli ofert po połowie lepiej niż środek). Otwarty ogon bez cen
    dzielimy na [lo, 2*lo] + [2*lo, ∞).
    """
    inside = sorted(p for p in (to_grosze(x) for x in (prices_zl or [])) if p is not None and p > rng.lo
                    and (rng.hi is None or p < rng.hi))
    if rng.hi is None:
        mid = inside[len(inside) // 2] if inside else max(rng.lo * 2, rng.lo + 100)
        mid = max(mid, rng.lo + 100)
    else:
        mid = (rng.lo + rng.hi) // 2
        if inside:
            median = inside[len(inside) // 2]
            # Mediana tylko gdy nie daje skrajnie wąskiej części (min. 1/8 szerokości).
            if rng.lo + rng.width() // 8 <= median <= rng.hi - rng.width() // 8:
                mid = median
    return Range(rng.lo, mid), Range(mid, rng.hi)


def needs_split(total, split_above):
    return total is not None and total > split_above


def coverage_gaps(ranges, price_min, price_max=None):
    """Luki w pokryciu [price_min, ∞) - do testów i kontroli po planowaniu. Pusta lista = pełne pokrycie."""
    gaps, cursor = [], to_grosze(price_min)
    for rng in sorted(ranges, key=lambda r: r.lo):
        if rng.lo > cursor:
            gaps.append(Range(cursor, rng.lo))
        if rng.hi is None:
            return gaps
        cursor = max(cursor, rng.hi)
    gaps.append(Range(cursor, None))
    return gaps
