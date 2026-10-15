"""Kategoria ze zdjęcia głównego przez AI - dla ofert z kategorii mieszanych, których tytuł pasuje do RAM-u i do
innej kategorii („Laptop Dell 16GB RAM”, „Płyta + procesor + RAM”, „RAM DDR4 z laptopa”). Prośba użytkownika
2026-10-15: przy RAM-ie nie decyduje kolejność słów w tytule, tylko to, co widać na zdjęciu.

* Kandydaci: listings.category_check = 'pending' (ustawia crawler / reclassify - classify.needs_photo_check).
* Zdjęcie idzie jako URL (`photo_url` z katalogu) - pobiera je dostawca AI, NIE nasze proxy (zero transferu).
  Dla Gemini z SNIPER_AI_PHOTOS=download pobieramy je sami, bezpośrednio z domowego IP (też bez proxy).
* Dostawca i klucz jak w Sniperze (SNIPER_AI_PROVIDER, SNIPER_AI_API_KEY); model: ANALYZER_AI_MODEL, domyślnie tani.
* Cache w ai_cache po (tytuł, marka/model, URL zdjęcia) - ta sama oferta nigdy dwa razy.
* Wynik: category_src = 'ai' (kolejne przejścia go nie nadpisują), category_rule = „ai: <co widać>”,
  category_check = 'done'; błąd → 'failed' (kategoria z reguł zostaje; `classify-ai --retry-failed` ponawia).
"""
import asyncio
import hashlib
import json
import logging

from . import db
from .classify import state_for
from .config import catalog_label

log = logging.getLogger("analyzer.ai")

TASK = "photo_category_v1"

# Co AI może odpowiedzieć → nasza kategoria (reszta = ignored).
ITEM_TO_CATEGORY = {
    "ram": "ram", "laptop": "laptop", "gpu": "gpu", "ssd": "storage", "phone": "phone", "tablet": "tablet",
    "console": "console",
}
ITEMS = ("ram", "laptop", "desktop_pc", "gpu", "ssd", "hdd", "cpu", "motherboard", "parts_bundle", "phone", "tablet",
         "console", "other")

SCHEMA = {
    "type": "object",
    "properties": {
        "item": {"type": "string", "enum": list(ITEMS),
                 "description": "Co jest przedmiotem sprzedaży (patrz instrukcja)."},
        "photo_seen": {"type": "boolean", "description": "Czy widzisz zdjęcie."},
        "note": {"type": "string", "description": "Max 15 słów po polsku: co widać na zdjęciu."},
    },
    "required": ["item", "photo_seen", "note"],
    "additionalProperties": False,
}

INSTRUCTION = """Oceniasz ogłoszenie z Vinted (kategorie: części komputerowe, nośniki, akcesoria komputerowe).
Tytuł wspomina o pamięci RAM i jednocześnie o czymś innym. Na podstawie GŁÓWNEGO ZDJĘCIA (tytuł pomocniczo) ustal,
CO JEST SPRZEDAWANE:
- ram: same moduły pamięci RAM (kości DIMM / SO-DIMM), jedna lub kilka sztuk;
- laptop: laptop (cały, także uszkodzony / na części);
- desktop_pc: komputer stacjonarny, mini PC, zestaw komputerowy w obudowie;
- gpu: karta graficzna; ssd: dysk SSD / NVMe; hdd: dysk talerzowy HDD;
- cpu: procesor; motherboard: płyta główna (sama);
- parts_bundle: kilka różnych części naraz (np. płyta + procesor + RAM);
- phone / tablet / console: telefon / tablet / konsola;
- other: coś innego.
Nie zgaduj z samego tytułu, jeśli zdjęcie pokazuje coś innego. Odpowiedz wyłącznie JSON-em według schematu."""

DEFAULT_MODELS = {"gemini": "gemini-3.8-flash", "anthropic": "claude-haiku-5-5"}


def content_hash(title, label, photo_url):
    return hashlib.sha256(f"{title or ''}\x1f{label or ''}\x1f{photo_url or ''}".encode()).hexdigest()


def prompt_text(row):
    label = " / ".join(x for x in (row["brand"], row["model"]) if x)
    return (f"Kategoria Vinted: {catalog_label(row['catalog_id'])}\nTytuł: {row['title']}\n"
            + (f"Marka / model z formularza: {label}\n" if label else "")
            + (f"Cena: {row['price_now']:.2f} zł\n" if row["price_now"] is not None else ""))


def parse_result(text):
    """JSON od modelu → {"item", "photo_seen", "note"}. ValueError przy błędnej odpowiedzi."""
    data = json.loads(text)
    item = str(data.get("item") or "").strip().lower()
    if item not in ITEMS:
        raise ValueError(f"nieznana odpowiedź: {item!r}")
    return {"item": item, "photo_seen": bool(data.get("photo_seen")), "note": str(data.get("note") or "")[:200]}


class Backend:
    """Jedno zapytanie: (instrukcja + tekst + URL zdjęcia) → tekst JSON. Gemini albo Anthropic (jak w Sniperze)."""

    def __init__(self, ai_cfg, model, client=None):
        self.provider = ai_cfg.provider
        self.model = model
        self.photos = getattr(ai_cfg, "photos", "url")
        self._http = None
        if client is not None:
            self.client = client
        elif self.provider == "anthropic":
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=ai_cfg.api_key, timeout=ai_cfg.timeout, max_retries=2)
        else:
            from google import genai
            from google.genai import types
            self.client = genai.Client(api_key=ai_cfg.api_key,
                                       http_options=types.HttpOptions(timeout=int(ai_cfg.timeout * 1000)))

    async def ask(self, text, photo_url):
        if self.provider == "anthropic":
            content = [{"type": "image", "source": {"type": "url", "url": photo_url}}] if photo_url else []
            content.append({"type": "text", "text": text})
            # Jak w Sniperze (sniper/evaluator.py): beta.messages + output_config (odpowiedź zgodna ze schematem).
            response = await self.client.beta.messages.create(
                model=self.model, max_tokens=400, system=INSTRUCTION,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
            usage = (getattr(response.usage, "input_tokens", 0) or 0, getattr(response.usage, "output_tokens", 0) or 0)
            return "".join(b.text for b in response.content if getattr(b, "type", None) == "text"), usage

        from google.genai import types
        from sniper.evaluator import image_mime
        parts = []
        if photo_url:
            data = await self._download(photo_url) if self.photos == "download" else None
            parts.append(types.Part.from_bytes(data=data, mime_type=image_mime(photo_url)) if data is not None
                         else types.Part.from_uri(file_uri=photo_url, mime_type=image_mime(photo_url)))
        parts.append(types.Part.from_text(text=text))
        config = types.GenerateContentConfig(
            system_instruction=INSTRUCTION, response_mime_type="application/json", response_json_schema=SCHEMA,
            max_output_tokens=2000, thinking_config=types.ThinkingConfig(thinking_level="LOW"),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        response = await self.client.aio.models.generate_content(
            model=self.model, contents=[types.Content(role="user", parts=parts)], config=config)
        meta = getattr(response, "usage_metadata", None)
        usage = (getattr(meta, "prompt_token_count", 0) or 0,
                 (getattr(meta, "candidates_token_count", 0) or 0) + (getattr(meta, "thoughts_token_count", 0) or 0))
        return response.text, usage

    async def _download(self, url):
        import httpx
        if self._http is None:
            # Bezpośrednio z domowego IP, bez proxy (trust_env=False) - zdjęcia nie idą przez IPRoyal / Evomi.
            self._http = httpx.AsyncClient(trust_env=False, timeout=20.0, follow_redirects=True)
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            log.warning("[AI] Nie pobrałem zdjęcia %s: %r", url, exc)
            return None

    async def close(self):
        if self._http is not None:
            await self._http.aclose()
        close = getattr(self.client, "close", None)
        if self.provider == "anthropic" and close:
            await close()


def candidates(conn, limit=None, retry_failed=False):
    states = ("pending", "failed") if retry_failed else ("pending",)
    marks = ",".join("?" * len(states))
    sql = (f"SELECT id, catalog_id, title, brand, model, photo_url, price_now, category, state FROM listings "
           f"WHERE category_check IN ({marks}) AND category_src='rule' ORDER BY id DESC")
    params = list(states)
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def apply(conn, row, result, model, min_for=None):
    """Zapisuje decyzję AI: kategoria, stan (jak po reclassify), category_src='ai'."""
    category = ITEM_TO_CATEGORY.get(result["item"], "ignored")
    state = state_for(category, row["state"], row["price_now"], min_for)
    now = db.utcnow()
    rule = f"ai: {result['item']} - {result['note']}"[:300]
    conn.execute("UPDATE listings SET category=?, category_src='ai', category_rule=?, category_check='done', "
                 "state=?, state_at=CASE WHEN state != ? THEN ? ELSE state_at END WHERE id=?",
                 (category, rule, state, state, now, row["id"]))
    return category


async def classify_photos(cfg, conn, ai_cfg=None, backend=None, limit=None, retry_failed=False, concurrency=3):
    """Rozstrzyga kategorie 'pending' ze zdjęcia. Zwraca {"done": n, "failed": n, "cached": n, "changes": {...}}."""
    if ai_cfg is None:
        from sniper.config import AiConfig
        ai_cfg = AiConfig()
    stats = {"done": 0, "failed": 0, "cached": 0, "changes": {}, "tokens_in": 0, "tokens_out": 0}
    rows = candidates(conn, limit or cfg.ai_classify_limit, retry_failed)
    if not rows:
        return stats
    if backend is None:
        if not ai_cfg.api_key:
            log.warning("[AI] %d ofert czeka na sprawdzenie zdjęcia, ale brak klucza AI (SNIPER_AI_API_KEY) - "
                        "zostają z kategorią z reguł.", len(rows))
            return stats
        backend = Backend(ai_cfg, cfg.ai_model or DEFAULT_MODELS.get(ai_cfg.provider, ai_cfg.model))
    model = backend.model
    log.info("[AI] Sprawdzam zdjęcia %d ofert (RAM + inna kategoria w tytule), model %s.", len(rows), model)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(row):
        label = " ".join(x for x in (row["brand"], row["model"]) if x)
        key = content_hash(row["title"], label, row["photo_url"])
        cached = conn.execute("SELECT result_json FROM ai_cache WHERE content_hash=? AND task=?", (key, TASK)).fetchone()
        if cached:
            stats["cached"] += 1
            return row, json.loads(cached[0]), key, False
        async with semaphore:
            try:
                text, (t_in, t_out) = await backend.ask(prompt_text(row), row["photo_url"])
                stats["tokens_in"] += t_in
                stats["tokens_out"] += t_out
                return row, parse_result(text), key, True
            except Exception as exc:     # błąd jednej oferty nie zatrzymuje reszty
                log.warning("[AI] Oferta %s: %s", row["id"], (str(exc).splitlines() or [""])[0][:200] or type(exc))
                return row, None, key, False

    try:
        results = await asyncio.gather(*(one(r) for r in rows))
    finally:
        if backend is not None:
            await backend.close()
    with conn:
        for row, result, key, fresh in results:
            if result is None:
                conn.execute("UPDATE listings SET category_check='failed' WHERE id=?", (row["id"],))
                stats["failed"] += 1
                continue
            if fresh:
                conn.execute("INSERT OR REPLACE INTO ai_cache (content_hash, task, model, result_json, created_at) "
                             "VALUES (?, ?, ?, ?, ?)", (key, TASK, model, json.dumps(result), db.utcnow()))
            new = apply(conn, row, result, model, getattr(cfg, "category_min", None))
            change = (row["category"], new)
            stats["changes"][change] = stats["changes"].get(change, 0) + 1
            stats["done"] += 1
    log.info("[AI] Zdjęcia: rozstrzygnięte %d (z cache %d), błędy %d, tokeny %d/%d; zmiany: %s",
             stats["done"], stats["cached"], stats["failed"], stats["tokens_in"], stats["tokens_out"],
             ", ".join(f"{a} → {b}: {n}" for (a, b), n in sorted(stats["changes"].items())) or "brak")
    return stats
