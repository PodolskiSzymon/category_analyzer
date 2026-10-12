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
