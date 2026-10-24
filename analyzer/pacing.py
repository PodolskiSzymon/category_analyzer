"""„Ludzkie” tempo zapytań (prośba użytkownika 2026-10-24, recheck): nierówne odstępy zamiast stałego rytmu.

* zwykły odstęp: losowy z zakresu `base` (np. 2-6 s), częściej bliżej dolnej granicy (rozkład beta), czasem
  „zamyślenie” o kilka sekund dłużej,
* co 25-60 ofert krótka przerwa 30-120 s,
* co 300-600 ofert dłuższa przerwa 5-15 min.
Odstępy liczone od końca poprzedniego zapytania. Przy kilkunastu tysiącach ofert przerwy wydłużają całość o ~20-25%.
"""
import random


class HumanPacer:
    def __init__(self, base=(2.0, 6.0), rng=None, short_every=(25, 60), short_pause=(30.0, 120.0),
                 long_every=(300, 600), long_pause=(300.0, 900.0), think_chance=0.08, think=(3.0, 10.0)):
        self.base, self.rng = base, rng or random.Random()
        self.short_every, self.short_pause = short_every, short_pause
        self.long_every, self.long_pause = long_every, long_pause
        self.think_chance, self.think = think_chance, think
        self.count = 0
        self.next_short = self.rng.randint(*short_every)
        self.next_long = self.rng.randint(*long_every)

    def next(self):
        """(sekundy, opis) przerwy przed kolejną ofertą; opis None = zwykły odstęp."""
        self.count += 1
        if self.count >= self.next_long:
            self.next_long = self.count + self.rng.randint(*self.long_every)
            self.next_short = self.count + self.rng.randint(*self.short_every)
            return self.rng.uniform(*self.long_pause), "dłuższa przerwa"
        if self.count >= self.next_short:
            self.next_short = self.count + self.rng.randint(*self.short_every)
            return self.rng.uniform(*self.short_pause), "krótka przerwa"
        lo, hi = self.base
        delay = lo + (hi - lo) * self.rng.betavariate(2, 3)
        if self.rng.random() < self.think_chance:
            return delay + self.rng.uniform(*self.think), "chwila namysłu"
        return delay, None
