"""CLI analizatora: python -m analyzer <polecenie>  (z katalogu głównego repozytorium).

  probe  --catalog 3580 [--item ID ...]   etap 0: odpowiedzi Vinted do sprawdzenia założeń -> data/probe/
  crawl  --catalog 3580                   pełne przejście kategorii -> data/analyzer.db (wznawia przerwane)
  probe-show [folder]                     wyciąg z plików probe do wklejenia (bez sieci)
  watch  [--catalog 3580]                 bez końca: crawl + resolve, między przejściami details (10-14 h)
  details [--limit N]                     szczegóły ofert (opis, atrybuty, „Dodane”) raz na ofertę
  resolve [--limit N]                     zniknięte z katalogu -> sold / deleted / unlisted (1 zapytanie/ofertę)
  classify-report / reclassify            klasyfikacja ofert z kategorii mieszanych (bez sieci)
  classify-ai [--limit N]                 RAM + inna kategoria w tytule -> AI ocenia zdjęcie główne (bez proxy)
  sample [--per-category N]               próbka ofert z opisami (bez danych sprzedawcy) -> data/sample_*.jsonl
  diag                                    zmiany cen i braki pokrycia w ostatnim przejściu (bez sieci)
  status                                  podsumowanie bazy (oferty, stany, partycje, przejścia, transfer)
"""
import argparse
import asyncio
import logging
import sqlite3
from pathlib import Path

from . import db
from .config import AnalyzerConfig, build_session, catalog_label

log = logging.getLogger("analyzer")


def setup_logging(db_path):
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    handlers = [console]
    if str(db_path) != ":memory:":
        path = Path(db_path).parent / "analyzer.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        to_file = logging.FileHandler(path, encoding="utf-8")
        to_file.setFormatter(fmt)
        handlers.append(to_file)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    for noisy in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def cmd_crawl(cfg, catalogs):
    from .crawler import Crawler

    conn = db.connect(cfg.db_path)
    session = build_session()
    try:
        crawler = Crawler(cfg, session, conn)
        for catalog_id in catalogs:
            await crawler.run(catalog_id)
        log.info("[TRANSFER] %s", session.traffic.window_report()[0])
    finally:
        await session.close()
        conn.close()


async def cmd_watch(cfg, catalogs, resolve_limit, with_details=True):
    """Bez końca: pełne przejście każdej kategorii + resolve, potem do następnego przejścia (ANALYZER_WATCH_HOURS,
    losowo) spokojne pobieranie szczegółów ofert, które ich jeszcze nie mają."""
    import random
    from datetime import datetime, timedelta, timezone

    from .crawler import Crawler
    from .details import fetch_details
    from .resolver import resolve

    while True:
        next_start = datetime.now(timezone.utc) + timedelta(hours=random.uniform(*cfg.watch_hours))
        conn = db.connect(cfg.db_path)
        session = build_session()
        try:
            crawler = Crawler(cfg, session, conn)
            for catalog_id in catalogs:
                await crawler.run(catalog_id)
            await run_ai_classify(cfg, conn)
            await resolve(cfg, session, conn, resolve_limit)
            for line in status_lines(conn):
                log.info("[STATUS] %s", line)
            if with_details:
                log.info("[WATCH] Do następnego przejścia (%s UTC) pobieram szczegóły ofert.",
                         next_start.strftime("%H:%M"))
                await fetch_details(cfg, session, conn, deadline=next_start)
            log.info("[TRANSFER] %s", session.traffic.window_report()[0])
        except Exception:
            log.exception("[WATCH] Cykl przerwany błędem - spróbuję przy następnym.")
        finally:
            await session.close()
            conn.close()
        wait = (next_start - datetime.now(timezone.utc)).total_seconds()
        log.info("[WATCH] Następne przejście za %.1f h (Ctrl+C = koniec; przerwane przejście zostanie wznowione).",
                 max(wait, 0) / 3600)
        if wait > 0:
            await asyncio.sleep(wait)


async def run_ai_classify(cfg, conn, limit=None, retry_failed=False):
    """Kategoria ze zdjęcia (AI) dla ofert „RAM + inna kategoria w tytule”. Błąd AI nie przerywa cyklu watch."""
    if not cfg.ai_classify:
        return None
    from .ai_classify import classify_photos
    try:
        return await classify_photos(cfg, conn, limit=limit, retry_failed=retry_failed)
    except Exception:
        log.exception("[AI] Sprawdzanie zdjęć przerwane błędem - kategorie z reguł zostają, ponowię w kolejnym cyklu.")
        return None


async def cmd_classify_ai(cfg, limit, retry_failed):
    conn = db.connect(cfg.db_path)
    try:
        stats = await run_ai_classify(cfg, conn, limit, retry_failed)
        if stats is None:
            print("Wyłączone (ANALYZER_AI_CLASSIFY=false) albo błąd - patrz log.")
        left = conn.execute("SELECT category_check, COUNT(*) FROM listings WHERE category_check IS NOT NULL "
                            "GROUP BY category_check").fetchall()
        print("Stan sprawdzania zdjęć: " + (", ".join(f"{r[0]} {r[1]}" for r in left) or "nic do sprawdzenia"))
    finally:
        conn.close()


async def cmd_details(cfg, limit):
    from .details import fetch_details

    conn = db.connect(cfg.db_path)
    session = build_session()
    try:
        await fetch_details(cfg, session, conn, limit)
        log.info("[TRANSFER] %s", session.traffic.window_report()[0])
    finally:
        await session.close()
        conn.close()


async def cmd_resolve(cfg, limit):
    from .resolver import resolve

    conn = db.connect(cfg.db_path)
    session = build_session()
    try:
        await resolve(cfg, session, conn, limit)
        log.info("[TRANSFER] %s", session.traffic.window_report()[0])
    finally:
        await session.close()
        conn.close()


async def cmd_probe(cfg, catalog_id, items):
    from .probe import Probe

    session = build_session()
    try:
        await Probe(session, catalog_id).run(items)
    finally:
        await session.close()


def coverage_lines(conn, tolerance=1.0, tolerance_pct=1.5):
    """Kontrola kompletności: dla każdej partycji ile ofert z bazy (bieżąca cena ± max(tolerance zł, tolerance_pct %))
    vs total_entries z Vinted. Tolerancja procentowa - filtr Vinted liczy oferty zagraniczne po swoim kursie
    (diag 2026-10-12), więc ich cena w zł bywa poza przedziałem o ułamek procenta."""
    lines = []
    rows = conn.execute("SELECT * FROM partitions WHERE active=1 AND last_total IS NOT NULL ORDER BY catalog_id, "
                        "price_from").fetchall()
    by_catalog = {}
    for row in rows:
        lo = row["price_from"] - max(tolerance, row["price_from"] * tolerance_pct / 100)
        hi = (row["price_to"] + max(tolerance, row["price_to"] * tolerance_pct / 100)
              if row["price_to"] is not None else 1e12)
        have = conn.execute("SELECT COUNT(*) FROM listings WHERE catalog_id=? AND last_run_id=? AND "
                            "price_now BETWEEN ? AND ?", (row["catalog_id"], row["done_run_id"], lo, hi)).fetchone()[0]
        stats = by_catalog.setdefault(row["catalog_id"], {"parts": 0, "short": 0, "missing": 0, "worst": []})
        stats["parts"] += 1
        if have < row["last_total"]:
            stats["short"] += 1
            stats["missing"] += row["last_total"] - have
            stats["worst"].append((row["last_total"] - have, row["price_from"], row["price_to"], row["last_total"], have))
    for catalog_id, st in by_catalog.items():
        tol = f"±max({tolerance:g} zł, {tolerance_pct:g}%)" if tolerance_pct else f"±{tolerance:g} zł"
        lines.append(f"kategoria {catalog_label(catalog_id)}: kontrola pokrycia - partycji z brakami {st['short']}/{st['parts']}, "
                     f"brakuje łącznie ~{st['missing']} ofert (tolerancja ceny {tol})")
        for miss, lo, hi, total, have in sorted(st["worst"], reverse=True)[:5]:
            lines.append(f"    {lo:g}-{'∞' if hi is None else format(hi, 'g')} zł: Vinted {total}, w bazie {have} "
                         f"(brak {miss})")
    return lines


def status_lines(conn):
    lines = []
    for row in conn.execute("SELECT COALESCE(category, '?') AS category, state, COUNT(*) AS n FROM listings "
                            "GROUP BY category, state ORDER BY category, n DESC"):
        lines.append(f"przedmiot {row['category']:<8}: {row['state']:<13} {row['n']}")
    for row in conn.execute("SELECT COALESCE(category, '?') AS category, COUNT(*) AS n, SUM(details_at IS NOT NULL) AS d "
                            "FROM listings WHERE state IN ('active', 'reserved', 'unlisted') GROUP BY category"):
        lines.append(f"przedmiot {row['category']:<8}: szczegóły pobrane dla {row['d']}/{row['n']} śledzonych ofert")
    for row in conn.execute(
            "SELECT catalog_id, COUNT(*) AS n, SUM(last_total) AS total, SUM(last_items) AS items, "
            "SUM(oversize) AS oversize FROM partitions WHERE active=1 GROUP BY catalog_id"):
        lines.append(f"kategoria {catalog_label(row['catalog_id'])}: partycji {row['n']}, suma total_entries "
                     f"{row['total'] if row['total'] is not None else '?'}, zebrano {row['items'] or 0}, "
                     f"oversize {row['oversize'] or 0}")
    for row in conn.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 5"):
        lines.append(f"przejście #{row['id']} kat. {row['catalog_id']}: start {row['started_at']}, koniec "
                     f"{row['finished_at'] or '(niedokończone)'}, zapytań {row['requests']}, "
                     f"{(row['bytes'] or 0) / 1024 / 1024:.2f} MB, widziane {row['seen']}, nowe {row['new_ids']}, "
                     f"zmienione {row['changed']}, zniknięte {row['gone']}, błędy {row['errors']}")
    if not lines:
        return ["Baza pusta - uruchom: python -m analyzer crawl"]
    return lines + coverage_lines(conn)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m analyzer", description="Category Analyzer (Vinted)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_crawl = sub.add_parser("crawl", help="pełne przejście kategorii")
    p_crawl.add_argument("--catalog", type=int, action="append", help="catalog_id (domyślnie ANALYZER_CATALOGS)")
    p_watch = sub.add_parser("watch", help="bez końca: crawl + resolve co ANALYZER_WATCH_HOURS (domyślnie 10-14 h)")
    p_watch.add_argument("--catalog", type=int, action="append")
    p_watch.add_argument("--resolve-limit", type=int, default=None)
    p_watch.add_argument("--no-details", action="store_true", help="bez pobierania szczegółów między przejściami")
    p_details = sub.add_parser("details", help="szczegóły ofert (opis, atrybuty) - raz na ofertę")
    p_details.add_argument("--limit", type=int, default=None)
    p_resolve = sub.add_parser("resolve", help="etap 2: zniknięte oferty -> sprzedana / usunięta / niewidoczna")
    p_resolve.add_argument("--limit", type=int, default=None, help="najwyżej tyle ofert w jednym uruchomieniu")
    p_probe = sub.add_parser("probe", help="etap 0: zapis odpowiedzi Vinted do sprawdzenia założeń")
    p_probe.add_argument("--catalog", type=int, default=None)
    p_probe.add_argument("--item", type=int, action="append", default=[], help="ID oferty do details/sidebar")
    p_show = sub.add_parser("probe-show", help="wyciąg z zapisanych plików probe (bez sieci)")
    p_show.add_argument("folder", nargs="?", default=None, help="domyślnie najnowszy data/probe/*")
    sub.add_parser("status", help="podsumowanie bazy")
    sub.add_parser("diag", help="diagnostyka bazy (zmiany cen, braki pokrycia) - bez sieci")
    p_sample = sub.add_parser("sample", help="próbka ofert z opisami do projektu ekstrakcji -> data/sample_*.jsonl")
    p_sample.add_argument("--per-category", type=int, default=150)
    sub.add_parser("classify-report", help="klasyfikacja ofert z kategorii mieszanych - bez sieci")
    sub.add_parser("reclassify", help="ponowna klasyfikacja zapisanych ofert po poprawce reguł - bez sieci")
    p_ai = sub.add_parser("classify-ai", help="kategoria ze zdjęcia głównego (AI) dla ofert 'RAM + coś innego' w tytule")
    p_ai.add_argument("--limit", type=int, default=None, help="najwyżej tyle ofert (domyślnie ANALYZER_AI_CLASSIFY_LIMIT)")
    p_ai.add_argument("--retry-failed", action="store_true", help="ponów też oferty z błędem AI")
    args = parser.parse_args(argv)

    cfg = AnalyzerConfig()
    setup_logging(cfg.db_path)
    if args.command == "crawl":
        asyncio.run(cmd_crawl(cfg, args.catalog or list(cfg.catalogs)))
    elif args.command == "watch":
        asyncio.run(cmd_watch(cfg, args.catalog or list(cfg.catalogs), args.resolve_limit, not args.no_details))
    elif args.command == "classify-ai":
        asyncio.run(cmd_classify_ai(cfg, args.limit, args.retry_failed))
    elif args.command == "details":
        asyncio.run(cmd_details(cfg, args.limit))
    elif args.command == "resolve":
        asyncio.run(cmd_resolve(cfg, args.limit))
    elif args.command == "probe":
        asyncio.run(cmd_probe(cfg, args.catalog or cfg.catalogs[0], args.item))
    elif args.command == "probe-show":
        from .probe import show
        show(args.folder)
    elif args.command in ("classify-report", "reclassify"):
        from . import classify
        print(f"Otwieram bazę {cfg.db_path} ...", flush=True)
        try:
            conn = db.connect(cfg.db_path)
            if args.command == "reclassify":
                changes = classify.reclassify(conn, cfg.category_min, progress=lambda t: print(t, flush=True))
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            raise SystemExit("Baza zajęta przez inny proces (pewnie watch w trakcie zapisu) - spróbuj za chwilę "
                             "albo zatrzymaj watch (Ctrl+C) i uruchom ponownie.")
        if args.command == "reclassify":
            print("Zmiany kategorii: " + (", ".join(f"{a} → {b}: {n}" for (a, b), n in sorted(changes.items()))
                                          or "brak"))
        print("\n".join(classify.report(conn)))
        conn.close()
    elif args.command == "sample":
        from .sample import export
        conn = db.connect(cfg.db_path)
        path, counts = export(conn, Path(cfg.db_path).parent, args.per_category)
        conn.close()
        print(f"Zapisano {sum(counts.values())} ofert ({', '.join(f'{k} {v}' for k, v in counts.items())}) -> {path}")
        print(f"Rozmiar: {path.stat().st_size / 1e6:.1f} MB")
    elif args.command == "diag":
        from .diag import report
        conn = db.connect(cfg.db_path)
        print("\n".join(report(conn)))
        conn.close()
    elif args.command == "status":
        conn = db.connect(cfg.db_path)
        print("\n".join(status_lines(conn)))
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Przerwane ręcznie - `python -m analyzer crawl` wznowi przejście.")
