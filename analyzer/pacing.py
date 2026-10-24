"""„Ludzkie” tempo zapytań (recheck): nierówne odstępy zamiast stałego rytmu.

Ustawienia użytkownika (2026-10-24): bez częstych „chwil namysłu” i długich przerw - tylko:
* zwykły odstęp: losowy z zakresu `base` (np. 2-6 s), częściej bliżej dolnej granicy (rozkład beta),
* mniej więcej raz na pół godziny (losowo 25-35 min) trochę dłuższa chwila: 1-3 min.
Przy kilkunastu tysiącach ofert przerwy wydłużają całość tylko o ~5%.
"""
import random
import time


class HumanPacer:
    def __init__(self, base=(2.0, 6.0), rng=None, break_every_min=(25.0, 35.0), break_len=(60.0, 180.0),
                 clock=time.monotonic):
        self.base, self.rng, self.clock = base, rng or random.Random(), clock
        self.break_every_min, self.break_len = break_every_min, break_len
        self.next_break = self.clock() + self._interval()

    def _interval(self):
        return self.rng.uniform(*self.break_every_min) * 60

    def next(self):
        """(sekundy, opis) przerwy przed kolejną ofertą; opis None = zwykły odstęp."""
        now = self.clock()
        if now >= self.next_break:
            pause = self.rng.uniform(*self.break_len)
            self.next_break = now + pause + self._interval()
            return pause, "chwila przerwy"
        lo, hi = self.base
        return lo + (hi - lo) * self.rng.betavariate(2, 3), None
