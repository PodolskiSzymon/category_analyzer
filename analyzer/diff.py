"""Migawki: po PEŁNYM przejściu kategorii oferty niewidziane w tym przejściu dostają missed_runs += 1,
a po ANALYZER_GONE_AFTER_RUNS przejściach z rzędu - stan gone_pending (kolejka dla resolvera, etap 2).

Oferta widziana ponownie wraca do active/reserved w db.upsert_item (missed_runs = 0).
Oferty z ceną w partycji „oversize” (nie dało się jej przejść w całości) nie są oznaczane - ich brak
w migawce nie znaczy, że zniknęły.
"""
from .db import utcnow
from .partition import to_grosze

LIVE_STATES = ("active", "reserved")


def _in_ranges(price, ranges):
    if price is None:
        return False
    p = to_grosze(price)
    return any(lo <= p and (hi is None or p <= hi) for lo, hi in ranges)


def finish_snapshot(conn, catalog_id, run_id, gone_after, price_min=0.0):
    """Zwraca liczbę ofert przeniesionych do gone_pending w tym przejściu.

    Oferty z ostatnią ceną poniżej progu (poza zakresem crawla) dostają stan below_min - nie sprawdzamy ich.
    price_min: liczba albo funkcja kategoria → próg (AnalyzerConfig.category_min).
    """
    min_for = price_min if callable(price_min) else (lambda _category: price_min)
    oversize = [(to_grosze(r["price_from"]), to_grosze(r["price_to"])) for r in conn.execute(
        "SELECT price_from, price_to FROM partitions WHERE catalog_id=? AND active=1 AND oversize=1", (catalog_id,))]
    rows = conn.execute(
        f"""SELECT l.id, l.missed_runs, l.price_now AS price, l.category
            FROM listings l
            WHERE l.catalog_id=? AND l.state IN {LIVE_STATES} AND (l.last_run_id IS NULL OR l.last_run_id != ?)""",
        (catalog_id, run_id)).fetchall()
    now, gone = utcnow(), 0
    with conn:
        for row in rows:
            low = min_for(row["category"])
            if low and row["price"] is not None and row["price"] < low:
                conn.execute("UPDATE listings SET state='below_min', state_at=? WHERE id=?", (now, row["id"]))
                continue
            if oversize and _in_ranges(row["price"], oversize):
                continue
            missed = row["missed_runs"] + 1
            if missed >= gone_after:
                conn.execute("UPDATE listings SET missed_runs=?, state='gone_pending', state_at=? WHERE id=?",
                             (missed, now, row["id"]))
                gone += 1
            else:
                conn.execute("UPDATE listings SET missed_runs=? WHERE id=?", (missed, row["id"]))
    return gone
