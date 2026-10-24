"""„Ludzkie” tempo zapytań (recheck): nierówne odstępy zamiast stałego rytmu.

Ustawienia użytkownika (2026-10-24):
* zwykły odstęp: losowo 1-2,5 s (równomiernie),
* mniej więcej raz na pół godziny (losowo 25-35 min) przerwa 10-120 s.
"""
import random
import time


class HumanPacer:
    def __init__(self, base=(1.0, 2.5), rng=None, break_every_min=(25.0, 35.0), break_len=(10.0, 120.0),
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
        return self.rng.uniform(*self.base), None
