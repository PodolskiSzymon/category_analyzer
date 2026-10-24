"""„Ludzkie” tempo zapytań (recheck): nierówne odstępy zamiast stałego rytmu.

Ustawienia użytkownika (2026-10-24):
* zwykły odstęp: losowo 0,6-1,5 s (równomiernie),
* mniej więcej raz na pół godziny (losowo 25-35 min) przerwa 10-120 s,
* po 12 h pracy odpoczynek 8 h (potem znów 12 h pracy).
"""
import random
import time


class HumanPacer:
    def __init__(self, base=(0.6, 1.5), rng=None, break_every_min=(25.0, 35.0), break_len=(10.0, 120.0),
                 work_hours=12.0, rest_hours=8.0, clock=time.monotonic):
        self.base, self.rng, self.clock = base, rng or random.Random(), clock
        self.break_every_min, self.break_len = break_every_min, break_len
        self.work_s, self.rest_s = work_hours * 3600, rest_hours * 3600
        start = self.clock()
        self.next_break = start + self._interval()
        self.next_rest = start + self.work_s if self.work_s > 0 else float("inf")

    def _interval(self):
        return self.rng.uniform(*self.break_every_min) * 60

    def next(self):
        """(sekundy, opis) przerwy przed kolejną ofertą; opis None = zwykły odstęp."""
        now = self.clock()
        if now >= self.next_rest:
            self.next_rest = now + self.rest_s + self.work_s
            self.next_break = now + self.rest_s + self._interval()
            return self.rest_s, f"odpoczynek po {self.work_s / 3600:g} h pracy"
        if now >= self.next_break:
            pause = self.rng.uniform(*self.break_len)
            self.next_break = now + pause + self._interval()
            return pause, "chwila przerwy"
        return self.rng.uniform(*self.base), None
