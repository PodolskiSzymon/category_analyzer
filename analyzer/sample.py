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


def export(conn, out_dir, per_category=150):
    path = Path(out_dir) / f"sample_{datetime.now():%Y%m%d_%H%M}.jsonl"
    counts = {}
    categories = [r[0] for r in conn.execute(
        "SELECT DISTINCT l.category FROM listings l JOIN details d ON d.listing_id = l.id "
        "WHERE l.category NOT IN ('ignored', 'unknown') AND d.description IS NOT NULL")]
    with path.open("w", encoding="utf-8") as f:
        for category in categories:
            half = max(1, per_category // 2)
            rows = []
            for states in (("sold", "deleted", "closed", "hidden", "reserved", "unlisted"), ("active",)):
                marks = ",".join("?" * len(states))
                rows += conn.execute(
                    f"""SELECT l.id, l.category, l.catalog_id, l.title, l.brand, l.model, l.status_label, l.state,
                               l.price_now, l.sold_price, l.days_to_sell, l.first_seen, l.last_seen,
                               d.description, d.attributes_json, d.seller_currency, d.photo_count
                        FROM listings l JOIN details d ON d.listing_id = l.id
                        WHERE l.category = ? AND l.state IN ({marks}) AND d.description IS NOT NULL
                        ORDER BY RANDOM() LIMIT ?""", (category, *states, half)).fetchall()
            for r in rows:
                item = dict(r)
                item["description"] = redact(item["description"])
                item["attributes"] = json.loads(item.pop("attributes_json") or "{}")
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            counts[category] = len(rows)
    return path, counts
