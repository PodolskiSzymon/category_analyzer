"""CLI analizatora: python -m analyzer <polecenie>  (z katalogu głównego repozytorium).

  probe  --catalog 3580 [--item ID ...]   etap 0: odpowiedzi Vinted do sprawdzenia założeń -> data/probe/
  crawl  --catalog 3580                   pełne przejście kategorii -> data/analyzer.db (wznawia przerwane)
  probe-show [folder]                     wyciąg z plików probe do wklejenia (bez sieci)
  status                                  podsumowanie bazy (oferty, stany, partycje, przejścia, transfer)
"""
import argparse
import asyncio
import logging
from pathlib import Path

from . import db
from .config import AnalyzerConfig, build_session

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


async def cmd_probe(cfg, catalog_id, items):
    from .probe import Probe

    session = build_session()
    try:
        await Probe(session, catalog_id).run(items)
    finally:
        await session.close()


def status_lines(conn):
    lines = []
    for row in conn.execute("SELECT catalog_id, state, COUNT(*) AS n FROM listings GROUP BY catalog_id, state "
                            "ORDER BY catalog_id, n DESC"):
        lines.append(f"kategoria {row['catalog_id']}: {row['state']:<13} {row['n']}")
    for row in conn.execute(
            "SELECT catalog_id, COUNT(*) AS n, SUM(last_total) AS total, SUM(last_items) AS items, "
            "SUM(oversize) AS oversize FROM partitions WHERE active=1 GROUP BY catalog_id"):
        lines.append(f"kategoria {row['catalog_id']}: partycji {row['n']}, suma total_entries "
                     f"{row['total'] if row['total'] is not None else '?'}, zebrano {row['items'] or 0}, "
                     f"oversize {row['oversize'] or 0}")
    for row in conn.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 5"):
        lines.append(f"przejście #{row['id']} kat. {row['catalog_id']}: start {row['started_at']}, koniec "
                     f"{row['finished_at'] or '(niedokończone)'}, zapytań {row['requests']}, "
                     f"{(row['bytes'] or 0) / 1024 / 1024:.2f} MB, widziane {row['seen']}, nowe {row['new_ids']}, "
                     f"zmienione {row['changed']}, zniknięte {row['gone']}, błędy {row['errors']}")
    return lines or ["Baza pusta - uruchom: python -m analyzer crawl"]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m analyzer", description="Category Analyzer (Vinted)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_crawl = sub.add_parser("crawl", help="pełne przejście kategorii")
    p_crawl.add_argument("--catalog", type=int, action="append", help="catalog_id (domyślnie ANALYZER_CATALOGS)")
    p_probe = sub.add_parser("probe", help="etap 0: zapis odpowiedzi Vinted do sprawdzenia założeń")
    p_probe.add_argument("--catalog", type=int, default=None)
    p_probe.add_argument("--item", type=int, action="append", default=[], help="ID oferty do details/sidebar")
    p_show = sub.add_parser("probe-show", help="wyciąg z zapisanych plików probe (bez sieci)")
    p_show.add_argument("folder", nargs="?", default=None, help="domyślnie najnowszy data/probe/*")
    sub.add_parser("status", help="podsumowanie bazy")
    args = parser.parse_args(argv)

    cfg = AnalyzerConfig()
    setup_logging(cfg.db_path)
    if args.command == "crawl":
        asyncio.run(cmd_crawl(cfg, args.catalog or list(cfg.catalogs)))
    elif args.command == "probe":
        asyncio.run(cmd_probe(cfg, args.catalog or cfg.catalogs[0], args.item))
    elif args.command == "probe-show":
        from .probe import show
        show(args.folder)
    elif args.command == "status":
        conn = db.connect(cfg.db_path)
        print("\n".join(status_lines(conn)))
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Przerwane ręcznie - `python -m analyzer crawl` wznowi przejście.")
