"""Pełne przejście kategorii: partycje cenowe -> strony katalogu -> zapis do SQLite -> migawka (diff).

Planowanie jest połączone z crawlowaniem (zero osobnych zapytań „ile ofert”): pierwsza strona partycji podaje
total_entries (⚠); jeśli partycja jest za duża, zapisujemy oferty z tej strony (i tak już pobrane) i dzielimy ją.
Gdy API nie poda total_entries, przepełnienie wykrywamy empirycznie: pełna ostatnia dozwolona strona.
Podział zostaje w tabeli `partitions`, więc kolejne przejścia zaczynają od gotowego planu.
"""
import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone

import httpx

from sniper.session import RateLimited, SessionExpired

from . import db
from .catalog import fetch_page
from .classify import classify_item, needs_photo_check
from .config import catalog_label
from .diff import finish_snapshot
from .partition import Range, can_split, initial_ranges, needs_split, split, to_grosze, to_zl

log = logging.getLogger("analyzer.crawler")

RETRIES = 3


class Crawler:
    def __init__(self, cfg, session, conn, sleep=asyncio.sleep, fetch=fetch_page):
        self.cfg = cfg
        self.session = session
        self.conn = conn
        self.sleep = sleep
        self.fetch = fetch
        self.stats = {}
        self._first_request = True

    # ------------------------------------------------------------------ partycje w bazie
    def _ensure_partitions(self, catalog_id):
        count = self.conn.execute("SELECT COUNT(*) FROM partitions WHERE catalog_id=? AND active=1",
                                  (catalog_id,)).fetchone()[0]
        if count:
            self._apply_price_min(catalog_id)
            return
        with self.conn:
            for rng in initial_ranges(self.cfg.price_min_for(catalog_id), self.cfg.price_max, self.cfg.initial_partitions):
                self.conn.execute("INSERT INTO partitions (catalog_id, price_from, price_to) VALUES (?, ?, ?)",
                                  (catalog_id, rng.price_from, rng.price_to))
        log.info("[PLAN] Kategoria %s: %d partycji startowych.", catalog_label(catalog_id), self.cfg.initial_partitions + 1)

    def _apply_price_min(self, catalog_id):
        """Plan z bazy dopasowany do ANALYZER_PRICE_MIN: partycje poniżej wyłączone, przecinające próg - przycięte,
        a gdy próg obniżono - nowa partycja [price_min, najniższa istniejąca)."""
        low = self.cfg.price_min_for(catalog_id)
        with self.conn:
            off = self.conn.execute("UPDATE partitions SET active=0 WHERE catalog_id=? AND active=1 AND price_to IS NOT "
                                    "NULL AND price_to < ?", (catalog_id, low)).rowcount
            cut = self.conn.execute("UPDATE partitions SET price_from=?, done_run_id=NULL, last_total=NULL WHERE "
                                    "catalog_id=? AND active=1 AND price_from < ?", (low, catalog_id, low)).rowcount
            lowest = self.conn.execute("SELECT MIN(price_from) FROM partitions WHERE catalog_id=? AND active=1",
                                       (catalog_id,)).fetchone()[0]
            added = 0
            if lowest is not None and lowest > low:
                self.conn.execute("INSERT INTO partitions (catalog_id, price_from, price_to) VALUES (?, ?, ?)",
                                  (catalog_id, low, lowest))
                added = 1
        if off or cut or added:
            log.info("[PLAN] %s: cena minimalna %g zł: wyłączone partycje %d, przycięte %d, dodane %d.", catalog_label(catalog_id), low,
                     off, cut, added)

    def _pending_partitions(self, catalog_id, run_id):
        return self.conn.execute(
            """SELECT * FROM partitions WHERE catalog_id=? AND active=1 AND (done_run_id IS NULL OR done_run_id != ?)
               ORDER BY price_from""", (catalog_id, run_id)).fetchall()

    def _split_partition(self, row, prices):
        rng = Range(to_grosze(row["price_from"]), to_grosze(row["price_to"]))
        children = split(rng, prices)
        ids = []
        with self.conn:
            self.conn.execute("UPDATE partitions SET active=0 WHERE id=?", (row["id"],))
            for child in children:
                cur = self.conn.execute(
                    "INSERT INTO partitions (catalog_id, price_from, price_to, extra_json) VALUES (?, ?, ?, ?)",
                    (row["catalog_id"], child.price_from, child.price_to, row["extra_json"]))
                ids.append(cur.lastrowid)
        log.info("[PLAN] Partycja %s za duża (%s ofert) -> %s + %s", rng, row["last_total"] or "?",
                 children[0], children[1])
        return [self.conn.execute("SELECT * FROM partitions WHERE id=?", (i,)).fetchone() for i in ids]

    # ------------------------------------------------------------------ przebieg
    def _start_run(self, catalog_id):
        since = (datetime.now(timezone.utc) - timedelta(hours=self.cfg.resume_hours)).replace(microsecond=0)
        row = self.conn.execute(
            """SELECT id FROM crawl_runs WHERE catalog_id=? AND kind='crawl' AND finished_at IS NULL
               AND started_at >= ? ORDER BY id DESC LIMIT 1""", (catalog_id, since.isoformat())).fetchone()
        if row:
            log.info("[CRAWL] Wznawiam niedokończone przejście #%d.", row["id"])
            return row["id"]
        with self.conn:
            cur = self.conn.execute("INSERT INTO crawl_runs (started_at, kind, catalog_id) VALUES (?, 'crawl', ?)",
                                    (db.utcnow(), catalog_id))
        return cur.lastrowid

    def _bump(self, run_id, **values):
        sets = ", ".join(f"{k}={k}+?" for k in values)
        with self.conn:
            self.conn.execute(f"UPDATE crawl_runs SET {sets} WHERE id=?", (*values.values(), run_id))
        for k, v in values.items():
            self.stats[k] = self.stats.get(k, 0) + v

    def _traffic_bytes(self):
        traffic = getattr(self.session, "traffic", None)
        if traffic is None:
            return 0
        bucket = traffic.total["catalog"]
        return bucket["sent"] + bucket["received"]

    async def _get_page(self, run_id, row, page):
        for attempt in range(1, RETRIES + 1):
            if not self._first_request:
                await self.sleep(self.cfg.pick_delay())
            self._first_request = False
            before = self._traffic_bytes()
            try:
                result = await self.fetch(self.session, row["catalog_id"], page, self.cfg.per_page,
                                          row["price_from"], row["price_to"], self.cfg.order, self.cfg.seller_salt,
                                          self.cfg.price_margin)
                self._bump(run_id, requests=1, bytes=self._traffic_bytes() - before)
                return result
            except RateLimited:
                self._bump(run_id, requests=1, errors=1, bytes=self._traffic_bytes() - before)
                pause = 60.0 * attempt
                log.warning("[CRAWL] 429 (za szybko) - przerwa %.0f s.", pause)
                await self.sleep(pause)
                continue
            except (httpx.HTTPError, SessionExpired, ValueError, OSError) as exc:
                self._bump(run_id, requests=1, errors=1, bytes=self._traffic_bytes() - before)
                log.warning("[CRAWL] Błąd strony %d partycji %s-%s (próba %d/%d): %r", page, row["price_from"],
                            row["price_to"] if row["price_to"] is not None else "∞", attempt, RETRIES, exc)
                await self.sleep(min(60.0, 5.0 * 2 ** attempt))
        return None

    def _save(self, run_id, items):
        now = db.utcnow()
        counts = {"new": 0, "changed": 0, "same": 0, "ignored": 0}
        min_for = getattr(self.cfg, "category_min", None)
        with self.conn:
            for item in items:
                item.category, item.category_src, item.category_rule = classify_item(item, item.catalog_id)
                if item.category_src == "rule":
                    label = " ".join(x for x in (item.brand, item.model) if x)
                    if needs_photo_check(item.title, label):
                        item.category_check = "pending"
                counts[db.upsert_item(self.conn, item, run_id, now, min_for)] += 1
        self._bump(run_id, new_ids=counts["new"], changed=counts["changed"], seen=len(items))

    async def crawl_partition(self, run_id, row):
        """Zwraca listę partycji-dzieci do przejścia (gdy podzielono) albo [] (gotowe / błąd)."""
        max_pages = max(1, math.ceil(self.cfg.max_results / self.cfg.per_page))
        label = f"{row['price_from']:g}-{'∞' if row['price_to'] is None else format(row['price_to'], 'g')} zł"
        page, collected, total, prices = 1, 0, None, []
        while True:
            result = await self._get_page(run_id, row, page)
            if result is None:
                log.error("[CRAWL] Partycja %s niedokończona (błędy) - dokończę przy wznowieniu.", label)
                return []
            if page == 1:
                total = result.total_entries
                prices = [it.price for it in result.items]
            self._save(run_id, result.items)
            collected += len(result.items)

            if page == 1 and needs_split(total, self.cfg.split_above):
                with self.conn:
                    self.conn.execute("UPDATE partitions SET last_total=? WHERE id=?", (total, row["id"]))
                row = self.conn.execute("SELECT * FROM partitions WHERE id=?", (row["id"],)).fetchone()
                if can_split(Range(to_grosze(row["price_from"]), to_grosze(row["price_to"])), self.cfg.min_width):
                    return self._split_partition(row, prices)
                log.warning("[PLAN] Partycja %s ma %s ofert, a jest już najwęższa (%g zł) - zbieram, co się da "
                            "(potrzebna druga oś: marka/stan).", label, total, self.cfg.min_width)
                with self.conn:
                    self.conn.execute("UPDATE partitions SET oversize=1 WHERE id=?", (row["id"],))

            full = len(result.items) >= self.cfg.per_page
            last_known = (result.total_pages is not None and page >= result.total_pages) or \
                         (total is not None and collected >= total)
            if not full or last_known:
                break
            if page >= max_pages:
                # Pełna ostatnia dozwolona strona = prawdopodobnie limit wyników, a nie koniec partycji.
                log.warning("[CRAWL] Partycja %s: limit %d stron osiągnięty przy pełnych stronach.", label, max_pages)
                if total is None and can_split(Range(to_grosze(row["price_from"]), to_grosze(row["price_to"])),
                                               self.cfg.min_width):
                    return self._split_partition(row, prices)
                with self.conn:
                    self.conn.execute("UPDATE partitions SET oversize=1 WHERE id=?", (row["id"],))
                break
            page += 1

        with self.conn:
            self.conn.execute(
                "UPDATE partitions SET last_total=?, last_items=?, last_crawled_at=?, done_run_id=? WHERE id=?",
                (total, collected, db.utcnow(), run_id, row["id"]))
        log.info("[CRAWL] Partycja %s: %d ofert (total_entries: %s), stron: %d.", label, collected,
                 "?" if total is None else total, page)
        return []

    async def run(self, catalog_id):
        self.stats = {}
        self._first_request = True
        self._ensure_partitions(catalog_id)
        run_id = self._start_run(catalog_id)
        queue = list(self._pending_partitions(catalog_id, run_id))
        log.info("[CRAWL] Przejście #%d kategorii %s: %d partycji do zrobienia.", run_id, catalog_label(catalog_id), len(queue))
        while queue:
            row = queue.pop(0)
            queue[0:0] = await self.crawl_partition(run_id, row)

        if self._pending_partitions(catalog_id, run_id):
            log.warning("[CRAWL] Przejście #%d niepełne - uruchom crawl ponownie, żeby je dokończyć.", run_id)
            return run_id, False
        gone = finish_snapshot(self.conn, catalog_id, run_id, self.cfg.gone_after_runs, self.cfg.category_min)
        with self.conn:
            self.conn.execute("UPDATE crawl_runs SET finished_at=?, gone=? WHERE id=?", (db.utcnow(), gone, run_id))
        self.stats["gone"] = gone
        summary = self.conn.execute(
            "SELECT COUNT(*) AS n, SUM(last_total) AS total, SUM(oversize) AS oversize FROM partitions "
            "WHERE catalog_id=? AND active=1", (catalog_id,)).fetchone()
        unique = self.conn.execute("SELECT COUNT(*) FROM listings WHERE catalog_id=? AND last_run_id=?",
                                   (catalog_id, run_id)).fetchone()[0]
        log.info("[CRAWL] Przejście #%d gotowe: unikalnych ID %d, suma total_entries partycji %s, partycji %d "
                 "(oversize: %d), nowe %d, zmienione %d, zniknięte -> gone_pending %d.", run_id, unique,
                 summary["total"] if summary["total"] is not None else "?", summary["n"], summary["oversize"] or 0,
                 self.stats.get("new_ids", 0), self.stats.get("changed", 0), gone)
        return run_id, True
