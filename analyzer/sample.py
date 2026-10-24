"""Próbka prawdziwych ofert ze szczegółami (opis + atrybuty) do zaprojektowania ekstrakcji parametrów (etap 3).

`python -m analyzer sample [--per-category 150]` → data/sample_<data>.jsonl - losowe oferty z opisem z każdej naszej
kategorii, po połowie sprzedane/zniknięte i aktywne. Bez danych sprzedawcy; e-maile, numery telefonów i linki w opisie
zamaskowane. Plik można przesłać Claude (to ok. 1-3 MB).
"""
import json
import re
from datetime import datetime
from pathlib import Path

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){9,13}(?!\d)")
_URL = re.compile(r"https?://\S+|www\.\S+")


def redact(text):
    text = _EMAIL.sub("[email]", text or "")
    text = _URL.sub("[link]", text)
    return _PHONE.sub("[telefon]", text)


def export(conn, out_dir, per_category=150, progress=None):
    """Losowanie po samych ID (szybkie), dopiero potem odczyt opisów wylosowanych ofert."""
    import random

    say = progress or (lambda _text: None)
    path = Path(out_dir) / f"sample_{datetime.now():%Y%m%d_%H%M}.jsonl"
    counts = {}
    say("Szukam ofert z opisami...")
    ids = {}
    for r in conn.execute("SELECT l.id, l.category, l.state FROM listings l JOIN details d ON d.listing_id = l.id "
                          "WHERE l.category NOT IN ('ignored', 'unknown') AND d.description IS NOT NULL"):
        group = "active" if r["state"] == "active" else "gone"
        ids.setdefault(r["category"], {"active": [], "gone": []})[group].append(r["id"])
    half = max(1, per_category // 2)
    with path.open("w", encoding="utf-8") as f:
        for category, groups in sorted(ids.items()):
            chosen = []
            for group in ("gone", "active"):
                pool = groups[group]
                chosen += random.sample(pool, min(half, len(pool)))
            say(f"  {category}: z opisem {len(groups['active'])} aktywnych, {len(groups['gone'])} zniknętych "
                f"- wybieram {len(chosen)}")
            for listing_id in chosen:
                r = conn.execute(
                    """SELECT l.id, l.category, l.catalog_id, l.title, l.brand, l.model, l.status_label, l.state,
                              l.price_now, l.sold_price, l.days_to_sell, l.first_seen, l.last_seen,
                              d.description, d.attributes_json, d.seller_currency, d.photo_count
                       FROM listings l JOIN details d ON d.listing_id = l.id WHERE l.id = ?""",
                    (listing_id,)).fetchone()
                item = dict(r)
                item["description"] = redact(item["description"])
                item["attributes"] = json.loads(item.pop("attributes_json") or "{}")
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            counts[category] = len(chosen)
    return path, counts
