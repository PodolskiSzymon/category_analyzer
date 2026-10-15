import asyncio
import json

import httpx
import pytest

from analyzer import db, rawstore
from analyzer.catalog import fetch_page, parse_item, parse_page
from analyzer.config import AnalyzerConfig, parse_range
from analyzer.crawler import Crawler
from analyzer.partition import Range, coverage_gaps, initial_ranges, split, to_grosze
from analyzer.probe import redact
from analyzer.tests.fakes import FakeMarket, market_prices, no_sleep


def make_cfg(**kw):
    cfg = AnalyzerConfig(db_path=":memory:")
    cfg.per_page, cfg.max_results, cfg.partition_fill = 96, 960, 0.9
    cfg.price_min, cfg.price_max, cfg.initial_partitions = 0.0, 20000.0, 4
    cfg.page_delay, cfg.gone_after_runs, cfg.seller_salt = (0.0, 0.0), 2, ""
    cfg.details_catalogs = None
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def crawl(cfg, market, conn=None, catalog_id=3580):
    conn = conn or db.connect(":memory:")
    crawler = Crawler(cfg, session=None, conn=conn, sleep=no_sleep, fetch=market.fetch)
    run_id, complete = asyncio.run(crawler.run(catalog_id))
    return conn, crawler, run_id, complete


def active_ranges(conn):
    return [Range(to_grosze(r["price_from"]), to_grosze(r["price_to"]))
            for r in conn.execute("SELECT * FROM partitions WHERE active=1")]


# ------------------------------------------------------------------ partycje

def test_initial_ranges_cover_everything():
    ranges = initial_ranges(0, 20000, 8)
    assert len(ranges) == 9 and ranges[-1].hi is None
    assert coverage_gaps(ranges, 0) == []


def test_split_shares_border_and_uses_median():
    left, right = split(Range(0, 100000), prices_zl=[400, 450, 500, 520, 600])
    assert left.hi == right.lo == to_grosze(500)
    assert (left.lo, right.hi) == (0, 100000)
    tail_left, tail_right = split(Range(2000000, None))
    assert tail_left.hi == tail_right.lo == 4000000 and tail_right.hi is None


@pytest.mark.parametrize("with_pagination", [True, False])
@pytest.mark.parametrize("upper_inclusive", [True, False])
def test_full_crawl_collects_whole_category(with_pagination, upper_inclusive):
    prices = market_prices(12000)
    market = FakeMarket(prices, with_pagination=with_pagination, upper_inclusive=upper_inclusive)
    conn, crawler, run_id, complete = crawl(make_cfg(), market)
    assert complete
    unique = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    assert unique == len(prices)                       # bez dziur na granicach partycji
    assert coverage_gaps(active_ranges(conn), 0) == []
    if with_pagination:
        totals = [r[0] for r in conn.execute("SELECT last_total FROM partitions WHERE active=1")]
        assert max(totals) <= 864                      # 0.9 * 960
        assert sum(totals) >= unique                   # granice wspólne -> sumy mogą liczyć ofertę dwa razy
    run = conn.execute("SELECT * FROM crawl_runs WHERE id=?", (run_id,)).fetchone()
    assert run["finished_at"] and run["new_ids"] == unique and run["errors"] == 0


def test_second_run_reuses_plan_and_tracks_changes():
    prices = market_prices(5000, seed=2)
    market = FakeMarket(prices)
    conn, _, _, _ = crawl(make_cfg(), market)
    first_requests = len(market.requests)

    sold = [1000, 1001]
    for i in sold:
        del market.items[i]
    market.items[1002] -= 100                    # obniżka ceny
    market.reserved.add(1003)
    market.items[999999] = 1234.0                # nowa oferta
    market.requests.clear()
    _, crawler, _, _ = crawl(make_cfg(), market, conn)
    assert len(market.requests) < first_requests          # bez ponownego dzielenia od zera
    assert crawler.stats["new_ids"] == 1
    assert crawler.stats["changed"] == 2
    states = dict(conn.execute("SELECT id, state FROM listings WHERE id IN (1000, 1001, 1003)").fetchall())
    assert states == {1000: "active", 1001: "active", 1003: "reserved"}   # 1 przejście bez oferty to za mało
    prices_1002 = [r[0] for r in conn.execute("SELECT price FROM observations WHERE listing_id=1002 ORDER BY seen_at,"
                                              " rowid")]
    assert len(prices_1002) == 2 and prices_1002[1] == prices_1002[0] - 100

    _, crawler, _, _ = crawl(make_cfg(), market, conn)
    assert crawler.stats["gone"] == 2
    states = dict(conn.execute("SELECT id, state FROM listings WHERE id IN (1000, 1001)").fetchall())
    assert states == {1000: "gone_pending", 1001: "gone_pending"}

    market.items[1000] = 500.0                   # wróciła (np. ukryta i przywrócona)
    crawl(make_cfg(), market, conn)
    row = conn.execute("SELECT state, missed_runs FROM listings WHERE id=1000").fetchone()
    assert tuple(row) == ("active", 0)


def test_single_price_over_limit_is_marked_oversize():
    prices = [999.0] * 1500 + market_prices(2000, seed=3)
    market = FakeMarket(prices)
    conn, _, _, complete = crawl(make_cfg(), market)
    assert complete
    oversize = conn.execute("SELECT price_from, price_to FROM partitions WHERE active=1 AND oversize=1").fetchall()
    # zapytania są szersze o ANALYZER_PRICE_MARGIN (1 zł), więc sąsiednie wąskie partycje też widzą 999 zł
    assert oversize and all(r[0] - 1 <= 999 <= r[1] + 1 for r in oversize)
    # Oferty spoza oversize - wszystkie; przy 999 zł najwyżej limit wyników.
    others = sum(1 for p in prices if p != 999.0)
    at_999 = conn.execute("SELECT COUNT(*) FROM listings l JOIN observations o ON o.listing_id=l.id "
                          "WHERE o.price=999").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    assert total - at_999 == others and 0 < at_999 <= 1500


def test_interrupted_run_resumes():
    prices = market_prices(4000, seed=4)
    broken = {"on": True}
    market = FakeMarket(prices, fail=lambda lo, hi, page: broken["on"] and lo is not None and lo >= 5000)
    conn, _, run_id, complete = crawl(make_cfg(), market)
    assert not complete
    assert conn.execute("SELECT finished_at FROM crawl_runs WHERE id=?", (run_id,)).fetchone()[0] is None
    broken["on"] = False
    market.requests.clear()
    _, _, run_id2, complete = crawl(make_cfg(), market, conn)
    assert complete and run_id2 == run_id
    assert all(lo is not None and lo >= 5000 for lo, _, _ in market.requests)   # tylko niedokończone partycje
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == len(prices)


# ------------------------------------------------------------------ baza / parsowanie

def test_raw_roundtrip_and_no_personal_data():
    conn = db.connect(":memory:")
    item = parse_item({"id": 5, "title": "ThinkPad", "price": {"amount": "1200.0", "currency_code": "PLN"},
                       "user": {"id": 77, "login": "jan"}}, 3580)
    assert db.upsert_item(conn, item, 1, "2026-10-11T10:00:00+00:00") == "new"
    assert db.upsert_item(conn, item, 2, "2026-10-11T11:00:00+00:00") == "same"
    (fetched_at, raw), = db.get_raw(conn, 5, "catalog")
    assert raw["user"] == {"redacted": True} and raw["title"] == "ThinkPad"
    row = conn.execute("SELECT * FROM listings WHERE id=5").fetchone()
    assert row["seller_hash"] is None and row["last_run_id"] == 2
    assert rawstore.decompress(rawstore.compress({"a": "ż"})) == {"a": "ż"}


def test_seller_hash_only_with_salt():
    item = parse_item({"id": 1, "user": {"id": 77}}, 3580, seller_salt="sol")
    other = parse_item({"id": 2, "user": {"id": 77}}, 3580, seller_salt="sol")
    assert item.seller_hash and item.seller_hash == other.seller_hash and "77" not in item.seller_hash


def test_parse_item_missing_fields_are_none():
    item = parse_item({"id": "9"}, 3580)
    assert item.id == 9 and item.catalog_id == 3580
    assert (item.price, item.brand, item.is_reserved, item.photo_ts, item.favourite_count) == (None,) * 5


def test_parse_page_pagination():
    page = parse_page({"items": [{"id": 1}], "pagination": {"total_entries": 1234, "total_pages": 13,
                                                            "per_page": 96}}, 3580, 1, 96)
    assert (page.total_entries, page.total_pages, len(page.items)) == (1234, 13, 1)
    assert parse_page({"items": []}, 3580, 1, 96).total_entries is None


def test_fetch_page_sends_sniper_params():
    from sniper.session import VintedSession

    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        seen["host"] = request.url.host
        return httpx.Response(200, json={"items": [{"id": 1, "price": {"amount": "10", "currency_code": "PLN"}}],
                                         "pagination": {"total_entries": 1}})

    async def go():
        session = VintedSession(proxy_url=None)
        await session.client.aclose()
        session.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await fetch_page(session, 3580, 2, 96, 100.0, None)
        finally:
            await session.client.aclose()

    page = asyncio.run(go())
    assert page.items[0].price == 10.0
    assert seen["host"] == "api.vinted.pl"
    assert seen["attribute_ids[catalog]"] == "3580" and seen["price_from"] == "100" and "price_to" not in seen
    assert seen["page"] == "2" and seen["per_page"] == "96" and seen["order"] == "newest_first"


def test_probe_redacts_personal_data():
    data = {"items": [{"id": 1, "user": {"id": 5, "login": "x"}, "title": "t"}], "seller_id": 3}
    clean = redact(data)
    assert clean["items"][0]["user"] == "<redacted>" and clean["seller_id"] == "<redacted>"
    assert clean["items"][0]["title"] == "t"
    assert "login" not in json.dumps(clean)


def test_parse_range():
    assert parse_range("2-6", None) == (2.0, 6.0)
    assert parse_range("3", None) == (3.0, 3.0)
    assert parse_range("", (1.0, 2.0)) == (1.0, 2.0)


def test_probe_end_to_end(tmp_path, monkeypatch):
    from sniper.session import VintedSession
    from analyzer import probe as probe_mod

    market = FakeMarket([100.0, 100.0, 150.0, 200.0] * 300, limit=960)

    def handler(request):
        params = dict(request.url.params)
        if "/details/sidebar" in request.url.path:
            return httpx.Response(404, json={"code": 404, "message": "not found"})
        page = int(params["page"])
        lo = float(params["price_from"]) if "price_from" in params else None
        hi = float(params["price_to"]) if "price_to" in params else None
        data = market.response(page, int(params["per_page"]), lo, hi)
        return httpx.Response(200, json=data)

    async def fast_sleep(_s):
        return None

    monkeypatch.setattr(probe_mod.asyncio, "sleep", fast_sleep)

    async def go():
        session = VintedSession(proxy_url=None)
        await session.client.aclose()
        session.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await probe_mod.Probe(session, 3580, out_dir=tmp_path).run([123])
        finally:
            await session.client.aclose()

    out = asyncio.run(go())
    summary = (out / "summary.txt").read_text(encoding="utf-8")
    assert "total_entries" in summary and "page=20: HTTP 200, pozycji 0" in summary
    assert "[100; 100]: HTTP 200, pozycji 96, z ceną dokładnie 100: 96" in summary
    assert "sidebar 123: HTTP 404" in summary
    saved = json.loads((out / "01_page1.json").read_text(encoding="utf-8"))
    assert saved["body"]["items"][0]["user"] == "<redacted>"


def test_probe_show_reads_saved_files(tmp_path, capsys):
    from analyzer.probe import show

    (tmp_path / "01_page1.json").write_text(json.dumps({"_status": 200, "body": {"items": [
        {"id": 1, "photos": [{"a": 1}, {"b": 2}], "item_box": {"first_line": "Lenovo"}},
        {"id": 2, "item_box": {"first_line": "Dell"}}]}}), encoding="utf-8")
    (tmp_path / "03_from.json").write_text(json.dumps({"_params": {"price_from": "10", "price_to": "11"}, "body": {
        "items": [{"id": 3, "price": {"amount": "10.5"}}, {"id": 4, "price": {"amount": "12.0"},
                                                          "total_item_price": {"amount": "13.1"}}]}}),
        encoding="utf-8")
    show(tmp_path)
    out = (tmp_path / "show.txt").read_text(encoding="utf-8")
    assert '"Dell"' in out and "(+1)" in out
    assert "pozycji spoza zakresu 1" in out and '"12.0"' in out


def test_counts_update_listing_without_new_observation():
    conn = db.connect(":memory:")
    base = {"id": 5, "price": {"amount": "100", "currency_code": "PLN"}, "favourite_count": 1, "view_count": 10}
    db.upsert_item(conn, parse_item(base, 3580), 1, "2026-10-11T10:00:00.000+00:00")
    assert db.upsert_item(conn, parse_item({**base, "favourite_count": 4, "view_count": 50}, 3580), 2,
                          "2026-10-11T11:00:00.000+00:00") == "same"
    row = conn.execute("SELECT favourite_count, view_count FROM listings WHERE id=5").fetchone()
    assert tuple(row) == (4, 50)
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1


def test_item_box_parsing_real_labels():
    from analyzer.catalog import parse_item_box

    def box(label, second):
        return parse_item_box({"item_box": {"accessibility_label": label, "second_line": second}})

    assert box('ThinkPad X1 Carbon 10th, 14" WUXGA, i5-1245U, 16Gb RAM, 256Gb NVMe, Marka: Lenovo, Model: ThinkPad X1 '
               'Carbon, Stan: Dobry, 1371.44 zł, 1442.91 zł', "Dobry") == {
        "brand": "Lenovo", "model": "ThinkPad X1 Carbon", "status": "Dobry"}
    assert box("Laptop Lenovo, Marka: Lenovo, Stan: Bardzo dobry, 270.00 zł, 286.40 zł", "Bardzo dobry") == {
        "brand": "Lenovo", "model": None, "status": "Bardzo dobry"}
    assert box("Laptop, Stan: Nowy z metką, 100.00 zł", "") == {"brand": None, "model": None, "status": "Nowy z metką"}
    assert parse_item_box({}) == {"brand": None, "model": None, "status": None}


def test_parse_real_catalog_item():
    raw = {"id": 10327381899, "title": "Laptop Dell Latitude 3410", "favourite_count": 1, "view_count": 0,
           "item_box": {"accessibility_label": "Laptop Dell Latitude 3410, Marka: DELL, Model: Latitude 3410, "
                                               "Stan: Dobry, 510.00 zł, 538.40 zł",
                        "first_line": "DELL Latitude 3410", "second_line": "Dobry"},
           "photo": {"url": "https://images1.vinted.net/t/x/f800/dcb8a807.webp", "high_resolution": {"id": "x"}},
           "price": {"amount": "510.00", "currency_code": "PLN"},
           "service_fee": {"amount": "28.40", "currency_code": "PLN"},
           "total_item_price": {"amount": "538.40", "currency_code": "PLN"},
           "url": "/items/10327381899-laptop-dell-latitude-3410", "user": {"id": 1, "login": "x"}}
    item = parse_item(raw, 3580)
    assert (item.brand, item.model, item.status_label) == ("DELL", "Latitude 3410", "Dobry")
    assert (item.price, item.total_price, item.currency) == (510.0, 538.4, "PLN")
    assert (item.favourite_count, item.view_count, item.is_reserved, item.photo_ts) == (1, 0, None, None)
    assert item.state == "active"


def test_query_is_widened_by_margin():
    from analyzer.catalog import widen
    assert widen(100.0, 200.0, 1.0) == (99.0, 201.0)
    assert widen(0.0, 50.0, 1.0) == (0.0, 51.0)
    assert widen(20000.0, None, 1.0) == (19999.0, None)


# ------------------------------------------------------------------ resolver (etap 2)

SNIPER_FIXTURES = json.load(open(__import__("pathlib").Path(__file__).resolve().parents[2] / "sniper" / "tests" /
                                 "fixtures.json", encoding="utf-8"))
# Prawdziwa odpowiedź dla usuniętej oferty (10327664119, probe 2026-10-11): HTTP 404, klucze code/message/message_code.
DELETED_BODY = {"code": 104, "message": "Not found", "message_code": "not_found"}


def test_classify_real_responses():
    from analyzer.resolver import classify

    assert classify(200, SNIPER_FIXTURES["sidebar_sold"])[0] == "sold"
    assert classify(200, SNIPER_FIXTURES["sidebar_active"])[0] == "unlisted"
    assert classify(404, DELETED_BODY)[0] == "deleted"
    assert classify(404, {"code": 999})[0] is None          # nieznane - zostaje gone_pending
    assert classify(500, {})[0] is None
    reserved = json.loads(json.dumps(SNIPER_FIXTURES["sidebar_active"]))
    reserved["is_reserved"] = True
    assert classify(200, reserved)[0] == "reserved"


def test_resolve_flow_sold_deleted_unlisted():
    from sniper.session import VintedSession
    from analyzer.resolver import resolve

    market = FakeMarket(market_prices(3000, seed=5))
    conn, _, _, _ = crawl(make_cfg(), market)
    sold = dict(SNIPER_FIXTURES["sidebar_sold"], price={"amount": "777.0", "currency_code": "PLN"})
    responses = {1000: (200, sold), 1001: (404, DELETED_BODY), 1002: (200, SNIPER_FIXTURES["sidebar_active"]),
                 1003: (404, {"code": 1})}
    for item_id in responses:
        del market.items[item_id]
    crawl(make_cfg(), market, conn)
    crawl(make_cfg(), market, conn)
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE state='gone_pending'").fetchone()[0] == 4

    def handler(request):
        item_id = int(request.url.path.split("/")[4])
        status, body = responses[item_id]
        return httpx.Response(status, json=body)

    async def go():
        session = VintedSession(proxy_url=None)
        await session.client.aclose()
        session.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await resolve(make_cfg(), session, conn, sleep=no_sleep)
        finally:
            await session.client.aclose()

    counts = asyncio.run(go())
    assert counts == {"sold": 1, "deleted": 1, "unlisted": 1, "nieznany": 1}
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM listings WHERE id IN (1000, 1001, 1002, 1003)")}
    assert rows[1000]["state"] == "sold" and rows[1000]["sold_price"] == 777.0
    assert rows[1000]["days_to_sell"] is not None and rows[1000]["days_to_sell"] >= 0
    assert rows[1001]["state"] == "deleted" and rows[1002]["state"] == "unlisted"
    assert rows[1003]["state"] == "gone_pending"
    raw = db.get_raw(conn, 1000, "resolve")[0][1]
    assert "seller_id" not in json.dumps(raw).replace('"seller_id": "<redacted>"', "")   # RODO

    market.items[1002] = 900.0                     # niewidoczna wróciła do katalogu
    crawl(make_cfg(), market, conn)
    assert conn.execute("SELECT state FROM listings WHERE id=1002").fetchone()[0] == "active"


def test_coverage_check_reports_missing():
    from analyzer.__main__ import coverage_lines

    market = FakeMarket(market_prices(3000, seed=6))
    conn, _, _, _ = crawl(make_cfg(), market)
    assert "brakuje łącznie ~0 ofert" in coverage_lines(conn)[0]
    with conn:   # symulacja zgubionych ofert: usuwamy 5 z bazy
        conn.execute("DELETE FROM observations WHERE listing_id IN (SELECT id FROM listings LIMIT 5)")
        conn.execute("DELETE FROM raw")
        conn.execute("DELETE FROM listings WHERE id NOT IN (SELECT listing_id FROM observations)")
    assert "brakuje łącznie ~5 ofert" in coverage_lines(conn, tolerance=0.0, tolerance_pct=0.0)[0]


def test_price_min_applied_to_existing_plan():
    market = FakeMarket(market_prices(6000, seed=7))
    conn, _, _, _ = crawl(make_cfg(), market)                       # stara baza: plan od 0 zł
    below = {i for i, p in market.items.items() if p < 700}
    assert below
    market.requests.clear()
    crawl(make_cfg(price_min=700.0), market, conn)
    assert all(lo is not None and lo >= 700 for lo, _, _ in market.requests)   # nic poniżej progu
    assert coverage_gaps(active_ranges(conn), 700) == []
    states = dict(conn.execute("SELECT state, COUNT(*) FROM listings GROUP BY state").fetchall())
    assert states.get("below_min") == len(below) and "gone_pending" not in states
    expected = sum(1 for p in market.items.values() if p >= 700)
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE state='active'").fetchone()[0] == expected

    market.items[1000] = 800.0 if market.items[1000] < 700 else market.items[1000]   # podrożała -> znów śledzona
    crawl(make_cfg(price_min=700.0), market, conn)
    assert conn.execute("SELECT state FROM listings WHERE id=1000").fetchone()[0] == "active"

    market.requests.clear()                                          # próg obniżony -> dochodzi partycja [500, 700)
    crawl(make_cfg(price_min=500.0), market, conn)
    assert coverage_gaps(active_ranges(conn), 500) == []
    assert any(lo == 500 for lo, _, _ in market.requests)


def test_fresh_plan_starts_at_price_min():
    market = FakeMarket(market_prices(3000, seed=8))
    conn, _, _, _ = crawl(make_cfg(price_min=700.0), market)
    assert min(lo for lo, _, _ in market.requests) == 700
    assert conn.execute("SELECT MIN(o.price) FROM observations o").fetchone()[0] >= 700


# ------------------------------------------------------------------ details

def test_parse_upload_age():
    from datetime import timedelta
    from analyzer.details import parse_upload_age

    assert parse_upload_age("3 min.") == timedelta(minutes=3)
    assert parse_upload_age("5 godz.") == timedelta(hours=5)
    assert parse_upload_age("2 dni") == timedelta(days=2)
    assert parse_upload_age("dnia") == timedelta(days=1)
    assert parse_upload_age("tygodnia") == timedelta(weeks=1)       # prawdziwa wartość z sidebar_active
    assert parse_upload_age("3 mies.") == timedelta(days=90)         # zrzut użytkownika (Razer Blade)
    assert parse_upload_age("2 lata") == timedelta(days=730)
    assert parse_upload_age("przed chwilą") == timedelta(0)
    assert parse_upload_age("") is None and parse_upload_age("???") is None


async def _mock_session(handler):
    from sniper.session import VintedSession

    session = VintedSession(proxy_url=None)
    await session.client.aclose()
    session.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return session


def test_fetch_details_flow():
    from analyzer.details import fetch_details

    market = FakeMarket(market_prices(300, seed=9))
    conn, _, _, _ = crawl(make_cfg(), market)
    newest = sorted(market.items, reverse=True)
    sold_id, deleted_id = newest[1], newest[2]
    active = json.loads(json.dumps(SNIPER_FIXTURES["sidebar_active"]))

    def handler(request):
        item_id = int(request.url.path.split("/")[4])
        if item_id == sold_id:
            return httpx.Response(200, json=SNIPER_FIXTURES["sidebar_sold"])
        if item_id == deleted_id:
            return httpx.Response(404, json=DELETED_BODY)
        return httpx.Response(200, json=active)

    async def go(limit):
        session = await _mock_session(handler)
        try:
            return await fetch_details(make_cfg(), session, conn, limit=limit, sleep=no_sleep)
        finally:
            await session.client.aclose()

    counts = asyncio.run(go(5))
    assert counts == {"ok": 3, "sold": 1, "deleted": 1}
    row = conn.execute("SELECT * FROM details WHERE listing_id=?", (newest[0],)).fetchone()
    assert row["description"] == "Naujas, nenaudotas." and row["upload_age"] == "tygodnia"
    assert json.loads(row["attributes_json"])["brand"] == "Samsung"
    assert row["seller_currency"] == "EUR" and row["photo_count"] == 3 and row["business"] == 0
    listing = conn.execute("SELECT * FROM listings WHERE id=?", (newest[0],)).fetchone()
    assert listing["details_at"] and listing["content_hash"] and listing["created_at"] < listing["first_seen"]
    states = dict(conn.execute("SELECT id, state FROM listings WHERE id IN (?, ?)", (sold_id, deleted_id)).fetchall())
    assert states == {sold_id: "sold", deleted_id: "deleted"}
    assert conn.execute("SELECT description FROM details WHERE listing_id=?", (sold_id,)).fetchone()[0]
    raw = json.dumps(db.get_raw(conn, newest[0], "sidebar")[0][1])
    assert "148344250" not in raw                                       # seller_id wycięty (RODO)

    assert asyncio.run(go(None))["ok"] == len(market.items) - 5       # druga runda: tylko brakujące
    assert asyncio.run(go(None)) == {}


def test_fetch_details_respects_deadline():
    from datetime import datetime, timedelta, timezone
    from analyzer.details import fetch_details

    market = FakeMarket(market_prices(50, seed=10))
    conn, _, _, _ = crawl(make_cfg(), market)
    ticks = iter(range(100))
    start = datetime(2026, 10, 11, tzinfo=timezone.utc)

    def clock():
        return start + timedelta(minutes=next(ticks))

    async def go():
        session = await _mock_session(lambda r: httpx.Response(200, json=SNIPER_FIXTURES["sidebar_active"]))
        try:
            return await fetch_details(make_cfg(), session, conn, deadline=start + timedelta(minutes=7),
                                       sleep=no_sleep, clock=clock)
        finally:
            await session.client.aclose()

    assert asyncio.run(go()) == {"ok": 7}


def test_diag_report_runs():
    from analyzer.diag import report

    market = FakeMarket(market_prices(2000, seed=11))
    conn, _, _, _ = crawl(make_cfg(), market)
    for i in list(market.items)[:50]:
        market.items[i] = round(market.items[i] * 0.9, 2)        # prawdziwe obniżki o 10%
    crawl(make_cfg(), market, conn)
    text = "\n".join(report(conn))
    assert "obserwacji ze zmianą 50" in text and "≥ 10%" in text and "Najgorsza partycja" in text


def test_fx_drift_is_not_a_change():
    from analyzer.db import real_change

    def obs(price, reserved=None):
        return {"price": price, "is_reserved": reserved}

    # prawdziwe przykłady z diag 2026-10-12 (RON, EUR)
    assert not real_change(obs(706.5), obs(707.7))                  # przed details: ułamkowa cena = zagraniczna
    assert not real_change(obs(710.38), obs(710.63), "EUR")
    assert real_change(obs(710.38), obs(650.0), "EUR")              # obniżka sprzedawcy
    assert real_change(obs(700.0), obs(699.0))                      # PLN (pełne złote) - każda zmiana
    assert real_change(obs(700.5), obs(700.0), "PLN")
    assert real_change(obs(700.0, 0), obs(700.0, 1))                # rezerwacja
    assert not real_change(obs(700.0), obs(700.0))
    assert real_change(None, obs(700.0))


def test_fx_drift_updates_price_now_without_observation():
    conn = db.connect(":memory:")
    base = {"id": 7, "price": {"amount": "706.50", "currency_code": "PLN"},
            "total_item_price": {"amount": "744.73", "currency_code": "PLN"}}
    db.upsert_item(conn, parse_item(base, 3580), 1, "2026-10-11T10:00:00.000+00:00")
    drift = dict(base, price={"amount": "707.70", "currency_code": "PLN"},
                 total_item_price={"amount": "745.99", "currency_code": "PLN"})
    assert db.upsert_item(conn, parse_item(drift, 3580), 2, "2026-10-12T10:00:00.000+00:00") == "same"
    row = conn.execute("SELECT price_now, total_now FROM listings WHERE id=7").fetchone()
    assert tuple(row) == (707.7, 745.99)
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    cut = dict(base, price={"amount": "600.00", "currency_code": "PLN"})
    assert db.upsert_item(conn, parse_item(cut, 3580), 3, "2026-10-13T10:00:00.000+00:00") == "changed"


def test_seller_country_kept_personal_data_removed():
    conn = db.connect(":memory:")
    raw = {"id": 11, "price": {"amount": "900.00", "currency_code": "PLN"},
           "user": {"id": 5, "login": "jan", "profile_url": "x", "country_iso_code": "pl", "country_title": "Polska"}}
    item = parse_item(raw, 3580)
    assert item.seller_country == "PL"
    assert item.raw["user"] == {"redacted": True, "country_iso_code": "pl", "country_title": "Polska"}
    db.upsert_item(conn, item, 1, "2026-10-12T10:00:00.000+00:00")
    assert conn.execute("SELECT seller_country FROM listings WHERE id=11").fetchone()[0] == "PL"
    assert parse_item({"id": 12, "user": {"id": 1}}, 3580).seller_country is None
    assert redact({"user": {"login": "x", "country_code": "LT"}})["user"] == {"redacted": True, "country_code": "LT"}
    assert redact({"user": {"login": "x"}})["user"] == "<redacted>"


def test_price_min_per_catalog(monkeypatch):
    cfg = AnalyzerConfig(db_path=":memory:")
    cfg.price_min = None
    monkeypatch.delenv("ANALYZER_PRICE_MIN_3025", raising=False)
    assert cfg.price_min_for(3580) == 700 and cfg.price_min_for(3661) == 300 and cfg.price_min_for(9999) == 700
    monkeypatch.setenv("ANALYZER_PRICE_MIN_3025", "150")
    assert cfg.price_min_for(3025) == 150
    cfg.price_min = 500.0
    assert cfg.price_min_for(3661) == 500 and cfg.price_min_for(3025) == 150


def test_two_catalogs_in_one_db():
    phones = FakeMarket(market_prices(2000, seed=12))
    laptops = FakeMarket(market_prices(2000, seed=13))
    for i in list(phones.items):                      # inne ID niż laptopy
        phones.items[i + 10_000_000] = phones.items.pop(i)
    conn, _, _, _ = crawl(make_cfg(price_min=None), laptops, catalog_id=3580)
    crawl(make_cfg(price_min=None), phones, conn, catalog_id=3661)
    mins = dict(conn.execute("SELECT catalog_id, MIN(price_from) FROM partitions WHERE active=1 GROUP BY catalog_id"))
    assert mins == {3580: 700, 3661: 300}
    counts = dict(conn.execute("SELECT catalog_id, COUNT(*) FROM listings GROUP BY catalog_id"))
    assert counts[3580] == sum(1 for p in laptops.items.values() if p >= 700)
    assert counts[3661] == sum(1 for p in phones.items.values() if p >= 300)


def test_details_only_for_selected_catalogs(monkeypatch):
    from analyzer.config import _details_catalogs
    from analyzer.details import candidates

    monkeypatch.delenv("ANALYZER_DETAILS_CATALOGS", raising=False)
    monkeypatch.delenv("ANALYZER_DETAILS_CATEGORIES", raising=False)
    assert {"laptop", "phone", "console", "tablet", "ram", "gpu", "storage"} == set(_details_catalogs())
    monkeypatch.setenv("ANALYZER_DETAILS_CATALOGS", "all")
    assert _details_catalogs() is None
    monkeypatch.setenv("ANALYZER_DETAILS_CATALOGS", "3580,3661")         # dawny zapis numerami katalogów
    assert _details_catalogs() == ("laptop", "phone")
    monkeypatch.setenv("ANALYZER_DETAILS_CATEGORIES", "laptop,ram")
    assert _details_catalogs() == ("laptop", "ram")

    laptops, phones = FakeMarket(market_prices(300, seed=14)), FakeMarket(market_prices(300, seed=15))
    for i in list(phones.items):
        phones.items[i + 10_000_000] = phones.items.pop(i)
    conn, _, _, _ = crawl(make_cfg(), laptops, catalog_id=3580)
    crawl(make_cfg(), phones, conn, catalog_id=3661)
    assert {r["catalog_id"] for r in candidates(conn, categories=("laptop",))} == {3580}
    assert {r["catalog_id"] for r in candidates(conn)} == {3580, 3661}


# ------------------------------------------------------------------ kategorie mieszane (classify)

@pytest.mark.parametrize("title,expected", [
    # prawdziwe tytuły ze zrzutów użytkownika 2026-10-14
    ("pamięć RAM Kingston Fury Beast RGB 64GB [2×32GB] 5600MHz DDR5 CL36 DIMM", "ram"),
    ("Pamięć RAM DDR5 Patriot Viper Venom 32Gb 2×16GB 6000Mhz CL36 RGB XMP 3.0 EXPO Nowa Gwarancja", "ram"),
    ("ASUS Scar 17 Ryzen 9 5900HX 3080 1TB SSD 32GB", "laptop"),
    ("RAM do laptopa 16GB DDR4 SO-DIMM", "ram"),
    ("Pamięć Corsair Vengeance 2x8", "ram"),
    ("Karta graficzna MSI RTX 3070 Ventus", "gpu"),
    ("Gigabyte RTX 4060 Ti 8GB", "gpu"),
    ("Radeon RX 6700 XT", "gpu"),
    ("nVidia Quadro P2000", "gpu"),
    ("Samsung 990 PRO 2TB NVMe", "storage"),
    ("Dysk SSD do PS5 2TB z radiatorem", "storage"),
    ("Seagate Expansion Card Xbox Series 1TB", "storage"),
    ("Crucial P3 Plus 1TB", "storage"),
    ("Dysk zewnętrzny SSD Samsung T7 1TB", "storage"),
    ("Laptop Lenovo Legion 5 RTX 3060", "laptop"),
    ("Komputer przenośny Lenovo", "laptop"),
    ("Macbook Air M1", "laptop"),
    ("PS5 Slim 1TB + 2 pady", "console"),
    ("Xbox One S 1TB", "console"),
    ("Steam Deck 512GB OLED", "console"),
    ("Gra FIFA 23 PS4", "ignored"),          # gry odpuszczone 2026-10-14
    ("FIFA 23 Xbox One", "ignored"),
    ("Spider-Man 2 PS5", "ignored"),
    ("iPhone 13 128GB", "phone"),
    ("iPad Air 5", "tablet"),
    ("Dysk twardy WD Blue 1TB HDD", "ignored"),
    ("Dysk zewnętrzny 1TB Toshiba", "ignored"),
    ("Podstawka chłodząca pod laptopa", "ignored"),
    ("Torba na laptopa 15,6", "ignored"),
    ("Ładowarka do laptopa Dell 90W", "ignored"),
    ("Komputer stacjonarny i7 RTX 3060", "ignored"),
    ("Komputer Dell Optiplex", "ignored"),
    ("Procesor Ryzen 5 5600X", "ignored"),
    ("Płyta główna B550", "ignored"),
    ("Zasilacz 750W Corsair", "ignored"),
    ("Klawiatura mechaniczna Logitech", "ignored"),
    ("Gamepad Xbox", "ignored"),
    ("Pendrive 64GB", "ignored"),
    ("Karta pamięci microSD 128GB", "ignored"),
    ("Wentylator Arctic P12", "ignored"),
    ("Kingston 16gb", "unknown"),
    # nierozpoznane z classify-report użytkownika 2026-10-15 (oferty zagraniczne, numery modeli)
    ("Vaizdo plokštė Eagle S76X", "gpu"),
    ("Diamond Monster 3D II 8MB - 3dfx Voodoo 2", "gpu"),
    ("Operatyvi atmintis 4gb", "ram"),
    ("Adata Legend 720 2tb", "storage"),
    ("Samsung MZ7L37T6HBLA-00A07 7681 GB", "storage"),
    ("Seagate FireCuda 530 2TB", "storage"),
    ("ASRock B250M pro alaplap", "ignored"),
    ("Zakladna doska A520M-A PRO", "ignored"),
    ("Intel Core i3-10100F", "ignored"),
    ("Ryzen 5 7500F", "ignored"),
    ("2x I5 9500T", "ignored"),
    ("Corsair TX650M 650W tápegység – 80 PLUS Gold", "ignored"),
    ("Sursă de alimentare pentru calculator", "ignored"),
    ("Arctic Liquid Freezer II 420 AIO", "ignored"),
    ("Pevný disk Seagate hhd 1 tb (1000 gb) 3.5\" sata III", "ignored"),
    ("Vanjski tvrdi disk Seagate Expansion od 4 TB", "ignored"),
    ("Synology DS225+ Serwer plików", "ignored"),
    ("retro karta dźwiękowa creative sound blaster pro 2", "ignored"),
    ("Nvidia Shield TV", "ignored"),
    # wygrywa słowo, które pada wcześniej
    ("Laptop Dell Latitude 5490 i5-8350U + zasilacz", "laptop"),
    ("Lenovo ThinkPad T480 i5 8GB zasilacz torba", "laptop"),
    ("Asus TUF Ryzen 7 4800H RTX 3050", "laptop"),
    ("Zasilacz Dell Latitude 90W", "ignored"),
    ("Bateria MacBook Pro 13 A2171", "ignored"),
    ("Kontroler Xbox Series X", "ignored"),
    ("Karta graficzna GTX 1060 6GB + zasilacz 500W", "gpu"),
    ("Fan Edition Galaxy S20 FE", "phone"),
    ("RTX A2000 12GB", "gpu"),
    ("Kingston A2000 1TB NVMe", "storage"),
    # classify-report po reclassify (2026-10-15)
    ("WD Red 500 SA500", "storage"),
    ("asus strix 1050 Ti 4gb", "gpu"),
    ("Saphire r9 280x", "gpu"),
    ("Amd ATI Radeon HD5770 Mac Edition", "gpu"),
    ("2 placi video pe slot AGP", "gpu"),
    ("Vând hard-disk Seagate 3 TB", "ignored"),
    ("Hard extern 500GB", "ignored"),
    ("WD elements AE 4tb", "ignored"),
    ("Corsair Tx 650 m source", "ignored"),
    ("Ventilatoare Lian Li Uni Fan wireless LCD 120 ,3 pack", "ignored"),
    ("Corsair iCUE 220T tower case", "ignored"),
    ("Datorchassi ATX", "ignored"),
    ("PC zdroj", "ignored"),
    ("Elgato Stream Deck", "ignored"),
    ("Steam Deck 64GB", "console"),
])
def test_classify_titles(title, expected):
    from analyzer.classify import classify_text
    assert classify_text(title)[0] == expected


def test_mixed_catalog_routes_items_to_our_categories():
    market = FakeMarket([400, 150, 900, 300, 120, 250, 500])
    ids = sorted(market.items)
    market.titles = {ids[0]: "Pamięć RAM DDR5 32GB 2x16 6000MHz", ids[1]: "Klawiatura mechaniczna RGB",
                     ids[2]: "Laptop Dell Latitude 7420 i7 16GB", ids[3]: "Laptop HP 250 G7",
                     ids[4]: "Karta graficzna GTX 1050 Ti", ids[5]: "Kingston 16gb", ids[6]: "Samsung 990 PRO 2TB NVMe"}
    cfg = make_cfg(price_min=None)
    conn, _, _, _ = crawl(cfg, market, catalog_id=3582)
    rows = {r["id"]: (r["category"], r["state"]) for r in conn.execute("SELECT * FROM listings")}
    assert rows[ids[0]] == ("ram", "active")
    assert rows[ids[1]] == ("ignored", "ignored")
    assert rows[ids[2]] == ("laptop", "active")              # laptop z „podzespołów” → istniejąca kategoria laptop
    assert rows[ids[3]] == ("laptop", "below_min")           # 300 zł < próg laptopów 700 zł
    assert rows[ids[4]] == ("gpu", "below_min")              # 120 zł < próg kart 150 zł
    assert rows[ids[5]] == ("unknown", "unclassified")
    assert rows[ids[6]] == ("storage", "active")
    # odrzucone: bez obserwacji i surowego JSON-a (oszczędność miejsca)
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE listing_id=?", (ids[1],)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM raw WHERE listing_id=?", (ids[1],)).fetchone()[0] == 0

    # wszystkie znikają: do sprawdzania (gone_pending) idą tylko nasze śledzone przedmioty
    market.items.clear()
    crawl(cfg, market, conn, catalog_id=3582)
    crawl(cfg, market, conn, catalog_id=3582)
    gone = {r[0] for r in conn.execute("SELECT id FROM listings WHERE state='gone_pending'")}
    assert gone == {ids[0], ids[2], ids[6]}

    from analyzer.classify import report
    text = "\n".join(report(conn))
    assert "Katalog 3582: 7 ofert" in text and "Kingston 16gb" in text


def test_reclassify_after_rule_change():
    from analyzer.classify import reclassify

    market = FakeMarket([400, 150])
    a, b = sorted(market.items)
    market.titles = {a: "Pamięć RAM DDR4 16GB", b: "Klawiatura"}
    cfg = make_cfg(price_min=None)
    conn, _, _, _ = crawl(cfg, market, catalog_id=3582)
    with conn:   # symulacja starej (błędnej) reguły
        conn.execute("UPDATE listings SET category='ignored', state='ignored' WHERE id=?", (a,))
    changes = reclassify(conn, cfg.category_min)
    assert changes == {("ignored", "ram"): 1}
    assert tuple(conn.execute("SELECT category, state FROM listings WHERE id=?", (a,)).fetchone()) == ("ram", "active")


def test_migration_v7_sets_category_from_catalog():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for number, script in enumerate(db.MIGRATIONS[:6], start=1):
        conn.executescript(script)
        conn.execute(f"PRAGMA user_version={number}")
    conn.execute("INSERT INTO listings (id, catalog_id, first_seen, last_seen) VALUES (1, 3580, 'x', 'x'), "
                 "(2, 3661, 'x', 'x')")
    db.migrate(conn)
    cats = dict(conn.execute("SELECT id, category FROM listings").fetchall())
    assert cats == {1: "laptop", 2: "phone"}


# ------------------------------------------------------------------ RAM: kategoria ze zdjęcia (ai_classify)

@pytest.mark.parametrize("title,expected", [
    ("Laptop Dell Latitude 16GB RAM", True),
    ("Płyta główna + procesor + RAM 16GB", True),
    ("RAM DDR4 8GB z laptopa", False),           # „z laptopa” usuwane - sam RAM
    ("Pamięć RAM DDR5 32GB 2x16", False),
    ("Karta graficzna GTX 1060", False),
    ("Pamięć RAM DDR4 8GB laptop", True),
])
def test_needs_photo_check(title, expected):
    from analyzer.classify import needs_photo_check
    assert needs_photo_check(title) is expected


class FakeAiBackend:
    model = "fake-model"

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def ask(self, text, photo_url):
        self.calls.append((text, photo_url))
        answer = self.answers[len(self.calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        return json.dumps(answer), (300, 20)

    async def close(self):
        pass


def test_ai_photo_decides_ram_conflicts():
    from analyzer.ai_classify import classify_photos

    market = FakeMarket([400, 1500, 300, 250])
    ids = sorted(market.items)
    market.titles = {ids[0]: "Pamięć RAM DDR4 8GB laptop", ids[1]: "Laptop Dell Latitude 16GB RAM",
                     ids[2]: "Płyta główna + procesor + RAM", ids[3]: "Pamięć RAM DDR5 32GB 2x16"}
    cfg = make_cfg(price_min=None)
    conn, _, _, _ = crawl(cfg, market, catalog_id=3582)
    pending = {r[0] for r in conn.execute("SELECT id FROM listings WHERE category_check='pending'")}
    assert pending == {ids[0], ids[1], ids[2]}                       # sam RAM bez konfliktu - bez AI

    # kolejność kandydatów: najnowsze ID najpierw (ids[2], ids[1], ids[0])
    backend = FakeAiBackend([{"item": "parts_bundle", "photo_seen": True, "note": "płyta, procesor i RAM"},
                             {"item": "laptop", "photo_seen": True, "note": "laptop Dell"},
                             RuntimeError("HTTP 500")])
    stats = asyncio.run(classify_photos(cfg, conn, ai_cfg=object(), backend=backend))
    assert (stats["done"], stats["failed"]) == (2, 1)
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM listings")}
    assert (rows[ids[2]]["category"], rows[ids[2]]["state"], rows[ids[2]]["category_src"]) == ("ignored", "ignored", "ai")
    assert (rows[ids[1]]["category"], rows[ids[1]]["state"]) == ("laptop", "active")
    assert rows[ids[0]]["category_check"] == "failed" and rows[ids[0]]["category"] == "ram"   # z reguł zostaje

    # kolejne przejście nie nadpisuje decyzji AI i nie oznacza ponownie do sprawdzenia
    crawl(cfg, market, conn, catalog_id=3582)
    assert conn.execute("SELECT category, category_check FROM listings WHERE id=?", (ids[1],)).fetchone()[:] == \
        ("laptop", "done")

    # ponowienie błędu: odpowiedź „ram”; ta sama treść drugi raz - z cache, bez wywołania
    backend = FakeAiBackend([{"item": "ram", "photo_seen": True, "note": "dwie kości SO-DIMM"}])
    asyncio.run(classify_photos(cfg, conn, ai_cfg=object(), backend=backend, retry_failed=True))
    assert conn.execute("SELECT category, category_check FROM listings WHERE id=?", (ids[0],)).fetchone()[:] == \
        ("ram", "done")
    conn.execute("UPDATE listings SET category_check='pending', category_src='rule' WHERE id=?", (ids[0],))
    backend = FakeAiBackend([])
    stats = asyncio.run(classify_photos(cfg, conn, ai_cfg=object(), backend=backend))
    assert stats["cached"] == 1 and backend.calls == []


def test_ai_photo_without_key_keeps_rules():
    from analyzer.ai_classify import classify_photos

    class NoKey:
        api_key = ""
        provider = "gemini"

    market = FakeMarket([1500])
    market.titles = {next(iter(market.items)): "Laptop Dell 16GB RAM"}
    cfg = make_cfg(price_min=None)
    conn, _, _, _ = crawl(cfg, market, catalog_id=3582)
    stats = asyncio.run(classify_photos(cfg, conn, ai_cfg=NoKey()))
    assert stats["done"] == 0
    assert conn.execute("SELECT category_check FROM listings").fetchone()[0] == "pending"


def test_ai_anthropic_request_sends_photo_url():
    from analyzer.ai_classify import Backend, SCHEMA

    class Messages:
        async def create(self, **kw):
            self.kw = kw
            block = type("B", (), {"type": "text", "text": '{"item": "ram", "photo_seen": true, "note": "x"}'})
            usage = type("U", (), {"input_tokens": 500, "output_tokens": 10})
            return type("R", (), {"content": [block], "usage": usage})

    class Client:
        beta = type("Beta", (), {})()

    client = Client()
    client.beta.messages = Messages()
    ai_cfg = type("Cfg", (), {"provider": "anthropic", "api_key": "x", "timeout": 10, "photos": "url"})()
    backend = Backend(ai_cfg, "claude-haiku-5-5", client=client)
    text, usage = asyncio.run(backend.ask("Tytuł: Laptop 16GB RAM", "https://images1.vinted.net/t/x/f800/1.jpeg"))
    kw = client.beta.messages.kw
    assert kw["messages"][0]["content"][0] == {"type": "image", "source": {"type": "url",
                                               "url": "https://images1.vinted.net/t/x/f800/1.jpeg"}}
    assert kw["output_config"]["format"]["schema"] == SCHEMA and usage == (500, 10)


def test_reclassify_marks_ram_conflicts_pending():
    from analyzer.classify import reclassify
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO listings (id, catalog_id, title, first_seen, last_seen, state, state_at, category, "
                 "category_src) VALUES (1, 3582, 'Laptop Dell 16GB RAM', 'x', 'x', 'active', 'x', 'laptop', 'rule')")
    reclassify(conn)
    assert conn.execute("SELECT category_check FROM listings").fetchone()[0] == "pending"
