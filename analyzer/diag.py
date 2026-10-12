"""Diagnostyka bazy bez sieci (można uruchomić w drugim oknie, gdy działa watch).

Po przejściu #4 (2026-10-12): „zmienione 11810” (wcześniej 14 i 150) i braki w kontroli pokrycia (np. 798–831 zł:
Vinted 816, w bazie 563). Ten raport pokazuje, CO się zmieniło (cena / cena z opłatą / o ile %), i jakie ceny mają
oferty widziane w partycji z brakami - żeby poprawić przyczynę, a nie zgadywać.
"""
import json
from collections import Counter

from . import rawstore


def _pct(old, new):
    if old in (None, 0) or new is None:
        return None
    return (new - old) / old * 100


def changes_report(conn, run_id=None, examples=12):
    lines = []
    if run_id is None:
        row = conn.execute("SELECT MAX(id) FROM crawl_runs WHERE finished_at IS NOT NULL AND kind='crawl'").fetchone()
        run_id = row[0]
    run = conn.execute("SELECT * FROM crawl_runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        return ["Brak zakończonego przejścia."]
    # Obserwacje dopisane w tym przejściu dla ofert, które już miały wcześniejszą obserwację.
    rows = conn.execute(
        """SELECT o.listing_id, o.price, o.total_price, l.title, l.currency,
                  (SELECT p.price FROM observations p WHERE p.listing_id=o.listing_id AND p.seen_at < o.seen_at
                   ORDER BY p.seen_at DESC LIMIT 1) AS old_price,
                  (SELECT p.total_price FROM observations p WHERE p.listing_id=o.listing_id AND p.seen_at < o.seen_at
                   ORDER BY p.seen_at DESC LIMIT 1) AS old_total,
                  (SELECT seller_currency FROM details d WHERE d.listing_id=o.listing_id) AS seller_currency
           FROM observations o JOIN listings l ON l.id=o.listing_id
           WHERE o.seen_at BETWEEN ? AND ? AND l.first_seen < ?""",
        (run["started_at"], run["finished_at"], run["started_at"])).fetchall()
    kinds, sizes, curr = Counter(), Counter(), Counter()
    for r in rows:
        price_changed = r["price"] != r["old_price"]
        total_changed = r["total_price"] != r["old_total"]
        kinds["cena i cena z opłatą" if price_changed and total_changed else
              "tylko cena" if price_changed else "tylko cena z opłatą" if total_changed else "inne"] += 1
        pct = _pct(r["old_price"], r["price"])
        if pct is not None and price_changed:
            a = abs(pct)
            sizes["< 0,5%" if a < 0.5 else "0,5–2%" if a < 2 else "2–10%" if a < 10 else "≥ 10%"] += 1
        curr[r["seller_currency"] or "?(brak szczegółów)"] += 1
    lines.append(f"Przejście #{run_id}: obserwacji ze zmianą {len(rows)}")
    lines.append(f"  co się zmieniło: {dict(kinds)}")
    lines.append(f"  zmiana ceny o: {dict(sizes)}")
    lines.append(f"  waluta sprzedawcy (z details): {dict(curr.most_common(8))}")
    lines.append(f"  przykłady (id | waluta | cena stara -> nowa | z opłatą stara -> nowa | tytuł):")
    for r in rows[:examples]:
        lines.append(f"    {r['listing_id']} | {r['seller_currency'] or '?'} | {r['old_price']} -> {r['price']} | "
                     f"{r['old_total']} -> {r['total_price']} | {(r['title'] or '')[:40]}")
    return lines


def coverage_report(conn, examples=12):
    """Najgorsza partycja kontroli pokrycia: rozkład cen ofert widzianych w niej w ostatnim przejściu."""
    lines = []
    part = None
    worst = -1
    for p in conn.execute("SELECT * FROM partitions WHERE active=1 AND last_total IS NOT NULL"):
        hi = p["price_to"] + 1 if p["price_to"] is not None else 1e12
        have = conn.execute(
            "SELECT COUNT(*) FROM listings l WHERE l.last_run_id=? AND l.price_now BETWEEN ? AND ?",
            (p["done_run_id"], p["price_from"] - 1, hi)).fetchone()[0]
        if p["last_total"] - have > worst:
            worst, part = p["last_total"] - have, p
    if part is None:
        return ["Brak partycji."]
    lo, hi = part["price_from"], part["price_to"]
    lines.append(f"Najgorsza partycja {lo:g}-{hi:g} zł: Vinted {part['last_total']}, brak {worst}")
    # Surowe pozycje katalogu z ostatniego przejścia, których cena jest blisko partycji, ale poza nią.
    rows = conn.execute(
        """SELECT l.id, l.title, l.currency, l.price_now AS price,
                  (SELECT seller_currency FROM details d WHERE d.listing_id=l.id) AS sc
           FROM listings l WHERE l.last_run_id=? AND l.state IN ('active','reserved','unlisted')""",
        (part["done_run_id"],)).fetchall()
    near = [r for r in rows if r["price"] is not None and (lo * 0.85 <= r["price"] < lo - 1 or
                                                          hi + 1 < r["price"] <= hi * 1.15)]
    lines.append(f"  ofert z ceną do ±15% obok partycji: {len(near)}; waluta sprzedawcy: "
                 f"{dict(Counter(r['sc'] or '?' for r in near).most_common(6))}")
    for r in near[:examples]:
        raw = conn.execute("SELECT body FROM raw WHERE listing_id=? AND kind='catalog' ORDER BY fetched_at DESC "
                           "LIMIT 1", (r["id"],)).fetchone()
        item = rawstore.decompress(raw["body"]) if raw else {}
        lines.append(f"    {r['id']} | {r['sc'] or '?'} | cena {r['price']} | price {json.dumps(item.get('price'))} "
                     f"| total {json.dumps(item.get('total_item_price'))} | {(r['title'] or '')[:35]}")
    return lines


def country_report(conn):
    rows = conn.execute("SELECT COALESCE(seller_country, '?') AS c, COUNT(*) AS n FROM listings "
                        "WHERE state IN ('active','reserved','unlisted') GROUP BY c ORDER BY n DESC LIMIT 10").fetchall()
    return ["Kraj sprzedawcy (z katalogu; '?' = Vinted nie podał albo oferta sprzed migracji v6): "
            + ", ".join(f"{r['c']} {r['n']}" for r in rows)]


def report(conn):
    return changes_report(conn) + [""] + coverage_report(conn) + [""] + country_report(conn)
