"""Diagnostyka rozpoznawania sprzedaży (2026-10-24: po 2 tygodniach 0 ofert `sold` i 0 `closed` przy ~30 tys. zniknięć).

`python -m analyzer resolve-report` - bez sieci:
  * zestawienie zapisanych odpowiedzi resolvera (raw kind='resolve'): HTTP, code, pola item_status i flagi z góry
    odpowiedzi - czym naprawdę różnią się zniknięte oferty,
  * ile razy sprawdzano oferty unlisted / hidden (czy ponowne sprawdzanie działa),
  * plik data/resolve_sample_<czas>.jsonl - po kilkanaście przykładów na stan, tylko pola statusu (bez opisu
    i danych sprzedawcy) - do przesłania Claude,
  * linki do ręcznego sprawdzenia w przeglądarce (czy „usunięta” / „niewidoczna” nie jest w rzeczywistości sprzedana).
"""
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from sniper.extractor import get_plugin, unwrap_sidebar

from . import rawstore

STATUS_KEYS = ("is_closed", "item_closing_action", "is_reserved", "is_hidden", "is_draft", "is_processing",
               "transaction_permitted", "stats_visible", "item_alert")
TOP_KEYS = ("is_closed", "is_reserved", "is_hidden", "can_buy", "instant_buy", "code", "message_code")


def fingerprint(stored):
    """Najważniejsze pola jednej zapisanej odpowiedzi resolvera."""
    status_code = stored.get("_status")
    body = stored.get("body") if isinstance(stored.get("body"), dict) else {}
    out = {"http": status_code, "code": body.get("code")}
    if status_code == 200:
        sidebar = unwrap_sidebar(body)
        status = get_plugin(sidebar, "item_status") or {}
        out.update({f"st.{k}": status.get(k) for k in STATUS_KEYS if k in status})
        out.update({f"top.{k}": sidebar.get(k) for k in TOP_KEYS if k in sidebar})
        out["top.reservation"] = None if sidebar.get("reservation") in (None, {}, []) else "SET"
        out["plugins"] = ",".join(sorted(p.get("name") or "?" for p in sidebar.get("plugins") or []))
        out["has_item_status"] = bool(status)
    else:
        out["message"] = str(body.get("message") or body.get("_text") or "")[:80]
    return out


def report(conn, out_dir, per_state=15, progress=None):
    say = progress or (lambda _text: None)
    say("Czytam zapisane odpowiedzi resolvera...")
    total = conn.execute("SELECT COUNT(*) FROM raw WHERE kind = 'resolve'").fetchone()[0]
    say(f"  odpowiedzi: {total}")
    rows = conn.execute("""SELECT r.listing_id, r.fetched_at, r.body, l.state, l.title, l.category
                           FROM raw r JOIN listings l ON l.id = r.listing_id
                           WHERE r.kind = 'resolve' ORDER BY r.listing_id, r.fetched_at""")   # kursor - bez
    # wczytywania wszystkich odpowiedzi naraz (4 GB RAM na serwerze)
    combos, checks, per_listing = Counter(), Counter(), {}
    for n, r in enumerate(rows):
        if n and n % 20000 == 0:
            say(f"  ... {n}/{total}")
        fp = fingerprint(rawstore.decompress(r["body"]))
        key = json.dumps({k: v for k, v in fp.items() if k != "plugins"}, ensure_ascii=False, sort_keys=True)
        combos[(r["state"], key)] += 1
        item = per_listing.setdefault(r["listing_id"], {"id": r["listing_id"], "state": r["state"],
                                                        "category": r["category"], "title": r["title"], "checks": []})
        item["checks"].append({"at": r["fetched_at"], **fp})
    for item in per_listing.values():
        checks[(item["state"], min(len(item["checks"]), 5))] += 1

    lines = ["Odpowiedzi resolvera wg obecnego stanu oferty (najczęstsze kombinacje pól):"]
    for (state, key), n in combos.most_common(25):
        lines.append(f"  {n:>7}  {state:<11} {key}")
    lines.append("")
    lines.append("Ile razy sprawdzono ofertę (5 = 5 lub więcej):")
    for (state, k), n in sorted(checks.items()):
        lines.append(f"  {state:<11} sprawdzeń {k}: {n}")

    path = Path(out_dir) / f"resolve_sample_{datetime.now():%Y%m%d_%H%M}.jsonl"
    by_state = {}
    for item in per_listing.values():
        by_state.setdefault(item["state"], []).append(item)
    with path.open("w", encoding="utf-8") as f:
        for state, items in sorted(by_state.items()):
            # najpierw oferty sprawdzane kilka razy (widać, jak zmienia się odpowiedź)
            items.sort(key=lambda it: (-len(it["checks"]), -it["id"]))
            for item in items[:per_state]:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    lines.append("")
    lines.append(f"Próbka do przesłania: {path} ({path.stat().st_size / 1e3:.0f} KB)")
    lines.append("")
    lines.append("Sprawdź ręcznie w przeglądarce (czy jest napis „Sprzedane”, „Page not found”, czy zwykła oferta):")
    for state in ("deleted", "unlisted", "hidden"):
        for item in sorted(by_state.get(state, []), key=lambda it: -it["id"])[:4]:
            lines.append(f"  {state:<9} https://www.vinted.pl/items/{item['id']}   {(item['title'] or '')[:50]}")
    return lines
