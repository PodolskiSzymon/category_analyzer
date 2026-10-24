"""Etap 3 v1: parametry ofert REGUŁAMI (bez sieci, bez AI) - z formularza Vinted (atrybuty), tytułu i opisu.

Kolejność źródeł (EKSTRAKCJA.md): formularz platformy (`attribute`) > tytuł (`title`) > opis (`description`); każde pole
zapisujemy z jego źródłem. Opisy są w ~10 językach (próbka 2026-10-24: 65% sprzedawców spoza Polski), więc reguły
łapią to, co pisze się liczbami i nazwami modeli (CPU, GPU, GB, %, Hz, cale) i najczęstsze słowa usterek / blokad;
resztę (opisowy stan, nietypowe usterki) uzupełni później AI tylko tam, gdzie reguły nic nie znalazły.

Wynik: tabela `features` (migracja v11) - kolumny do prostego SQL + `fields_json` (wszystko z źródłami) +
`config_key` (klucz grupowania cen w raportach, per kategoria).

`python -m analyzer extract [--again]`  ·  `python -m analyzer extract-report`
"""
import json
import re
import unicodedata

VERSION = 1

# ---------------------------------------------------------------------------------------------- pomocnicze


def norm(text):
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("ł", "l"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


def _gb(text):
    """„16 GB” / „1 TB” / „1,5 TB” / „512GB” → GB (TB = 1000 GB, jak liczą sprzedawcy dysków)."""
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(tb|gb|mb)\b", norm(text))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2)
    if unit == "tb":
        return int(round(value * 1000))
    if unit == "mb":
        return None
    return int(round(value))


class Fields:
    """Zbiera pola z źródłami: pierwsze znalezione wygrywa (kolejność wywołań = priorytet źródeł)."""

    def __init__(self):
        self.data = {}

    def put(self, name, value, source):
        if value is not None and value != "" and name not in self.data:
            self.data[name] = {"value": value, "source": source}

    def get(self, name):
        return (self.data.get(name) or {}).get("value")

    def src(self, name):
        return (self.data.get(name) or {}).get("source")


# ---------------------------------------------------------------------------------------------- wspólne

CONDITION_GRADE = {   # stan z formularza Vinted → wspólna skala (EKSTRAKCJA.md §3)
    "nowy z metka": "new_sealed", "nowy bez metki": "new_open", "bardzo dobry": "A", "dobry": "B",
    "zadowalajacy": "C",
}

FOR_PARTS = re.compile(
    r"\b(?:na czesci|do naprawy|uszkodzon\w*|nie dziala\w*|nie wlacza\w*|niesprawn\w*|for parts|not working|"
    r"doesn'?t (?:turn on|work)|broken|defect\w*|defekt\w*|na diely|nefunkcni|nefunkcn\w*|nem mukodik|hibas|"
    r"alkatresz\w*|piese|nu functioneaza|defect|pentru piese|dalims|neveikia|reservedele|virker ikke|funkar inte|"
    r"trasig|ei toimi|varaosiksi|kaputt|defekt|ersatzteil\w*|per pezzi|non funziona|pour pieces|hors service)\b")
CRACKED = re.compile(
    r"\b(?:pekniet\w*|peknieta|zbit\w*|rozbit\w*|stluczon\w*|cracked|broken screen|shattered|prasklin\w*|praskl\w*|"
    r"rozbit\w*|torott|repedt|spart\w*|fisurat\w*|sudauzyt\w*|ikilus\w*|knust|sprucken|sprick\w*|rikki|"
    r"gebrochen|kaputt\w* display|incrinat\w*)\b")
LOCKED = re.compile(
    r"\b(?:icloud (?:lock|zablok\w*|blokad\w*)|blokada icloud|zablokowan\w* (?:na )?icloud|activation lock|"
    r"frp|konto google zablok\w*|blokada konta|bios (?:password|haslo)|haslo (?:do )?bios|zablokowan\w* bios|"
    r"mdm|zarzadzan\w* przez firm\w*|locked to|simlock(?! ?free)|blokada sim(?!-lock: brak)|banned|ban(?:em)? na)\b")
NOT_LOCKED = re.compile(r"\b(?:bez blokad\w*|brak blokad\w*|odblokowan\w*|unlocked|sim free|simlock free|"
                        r"no locks?|wylogowan\w* z icloud|bez icloud|icloud (?:wylogowan\w*|czyst\w*|free))\b")
BATTERY_WORDS = r"(?:bateri\w*|battery|akku\w*|akum\w*|baterie|baterija|akkumulator\w*|kondycj\w*|health|zdravi\w*|" \
                r"kapacit\w*|capacit\w*|stan baterii|zdrowie)"
BATTERY = re.compile(BATTERY_WORDS + r"[^0-9%\n]{0,25}?(\d{2,3})\s*%|(\d{2,3})\s*%[^\n]{0,15}?" + BATTERY_WORDS)


def common(f, title, desc, attrs, listing):
    status = attrs.get("status") or listing.get("status_label")
    grade = CONDITION_GRADE.get(norm(status))
    f.put("condition_grade", grade, "attribute")
    text = norm(f"{title}\n{desc}")
    if FOR_PARTS.search(norm(title)):
        f.put("for_parts", True, "title")
    elif FOR_PARTS.search(norm(desc)):
        f.put("for_parts", True, "description")
    if CRACKED.search(text):
        f.put("cracked", True, "title" if CRACKED.search(norm(title)) else "description")
    if NOT_LOCKED.search(text):
        f.put("locked", False, "description")
    elif LOCKED.search(text):
        f.put("locked", True, "title" if LOCKED.search(norm(title)) else "description")
    for source, part in (("title", title), ("description", desc)):
        match = BATTERY.search(norm(part))
        if match:
            pct = int(match.group(1) or match.group(2))
            if 40 <= pct <= 100:
                f.put("battery_pct", pct, source)
    bucket = attrs.get("battery_health")
    if bucket and bucket.lower() not in ("nieznany",):
        f.put("battery_bucket", bucket, "attribute")


# ---------------------------------------------------------------------------------------------- laptopy

CPU_PATTERNS = (
    re.compile(r"\b(?:intel\s*)?(?:core\s*)?ultra\s*([579])\s*-?\s*(\d{3}[a-z]{0,2})\b"),
    re.compile(r"\b(?:intel\s*)?(?:core\s*)?(i[3579])\s*-?\s*(\d{4,5}[a-z]{0,2})\b"),
    re.compile(r"\b(?:amd\s*)?ryzen\s*(?:ai\s*)?([3579])\s*(?:pro\s*)?-?\s*(\d{3,4}[a-z]{0,2})\b"),
    # Apple M - tylko w tekście z „macbook” / „apple” (patrz _cpu), bez „M2 SSD”, „M.2 512”
    re.compile(r"\b(?:apple\s*)?(m[1345](?!\s*\d)|m2(?!\s*(?:\d|ssd|nvme|slot|sata|dysk|disk)))"
               r"(?:\s*(pro|max|ultra))?\b"),
    re.compile(r"\b(celeron|pentium|athlon|snapdragon x\s*(?:elite|plus))\s*-?\s*([a-z]?\d{3,5}[a-z]?)?\b"),
)
CPU_FAMILY = re.compile(r"\b(?:intel\s*)?(?:core\s*)?(i[3579])\b(?![-\s]*\d)|\bryzen\s*([3579])\b(?!\s*\d{3})")
GPU_PATTERNS = (
    re.compile(r"\b(rtx)\s*(a\d{3,4}|\d{4})\s*(ti|super)?\b"),
    re.compile(r"\b(gtx)\s*(\d{3,4})\s*(ti|super)?\b"),
    re.compile(r"\b(rx)\s*(\d{3,4})\s*(xt|xtx|m|s)?\b"),
    re.compile(r"\b(quadro)\s*([a-z]?\d{3,4}[a-z]?)\b"),
    re.compile(r"\b(mx)\s*(\d{3})\b"),
    re.compile(r"\b(arc)\s*(a\d{3}m?)\b"),
)
INTEGRATED = re.compile(r"\b(?:iris\s*xe|iris plus|intel (?:uhd|hd) graphics|uhd graphics|radeon (?:graphics|vega)|"
                        r"780m|680m|890m|integrated graphics|zintegrowan\w*)\b")
SCREEN = re.compile(r"(?<![\d.,])(1[0-8](?:[.,]\d)?)\s*(?:\"|”|''|cal\w*|inch\w*|tum|zoll|col\w*|hüvelyk|palc\w*)")
HZ = re.compile(r"\b(60|90|120|144|165|240|300|360)\s*hz\b")
RAM = re.compile(r"\b(\d{1,2})\s*gb\s*(?:ram|ddr\d?|lpddr\d?\w*|pamie\w*|memory|memoria|operacn\w*)\b|"
                 r"\b(?:ram|pamiec\w*|memory)\s*:?\s*(\d{1,2})\s*gb\b")
STORAGE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(tb|gb)\s*(?:ssd|nvme|m\.?2|hdd|emmc|dysk\w*|disk\w*|storage)\b|"
                     r"\b(?:ssd|nvme|dysk|disk)(?:\s*(?::|m\.?2|nvme|pcie|sata|ssd))*\s*(\d+(?:[.,]\d+)?)\s*(tb|gb)\b")


def _cpu(text):
    apple = re.search(r"\b(?:macbook|apple|imac)\b", text)
    for pattern in CPU_PATTERNS:
        if pattern is CPU_PATTERNS[3] and not apple:
            continue
        match = pattern.search(text)
        if match:
            parts = [p for p in match.groups() if p]
            name = " ".join(parts).replace("  ", " ")
            if pattern is CPU_PATTERNS[0]:
                name = f"ultra {parts[0]} {parts[1]}"
            elif pattern is CPU_PATTERNS[1]:
                name = f"{parts[0]}-{parts[1]}"
            elif pattern is CPU_PATTERNS[2]:
                name = f"ryzen {parts[0]} {parts[1]}"
            elif pattern is CPU_PATTERNS[3]:
                name = "apple " + " ".join(parts)
            return name.strip()
    return None


def _gpu(text):
    for pattern in GPU_PATTERNS:
        match = pattern.search(text)
        if match:
            return " ".join(p for p in match.groups() if p)
    if INTEGRATED.search(text):
        return "integrated"
    return None


RAM_SIZES = (2, 4, 6, 8, 12, 16, 20, 24, 32, 36, 48, 64, 96, 128)
# „RTX 3050 6GB” - pamięć karty (typowo 2-12 GB w laptopach); „RTX 3060 16GB 512GB” - 16 GB to już RAM.
_GPU_WITH_VRAM = re.compile(r"\b(?:rtx|gtx|rx|quadro|mx|arc)\s*a?\d{3,4}\s*(?:ti|super|xt|m)?\s*(?:(?:2|3|4|6|8|12)\s*gb\b)?")


def _ram(text, loose=False):
    """RAM z „16GB RAM / DDR5 / pamięci”; loose=True (tytuł) - także goła liczba „16GB” obok większej pojemności
    dysku („i7 16GB 512GB SSD”), z pominięciem pamięci karty („RTX 3050 6GB”)."""
    match = RAM.search(text)
    if match:
        value = int(match.group(1) or match.group(2))
        if value in RAM_SIZES:
            return value
    if loose:
        clean = _GPU_WITH_VRAM.sub(" ", text)
        sizes = [(int(m.group(1)), m.end()) for m in re.finditer(r"\b(\d{1,4})\s*gb\b", clean)]
        small = [v for v, end in sizes if v in RAM_SIZES and v <= 64
                 and not re.match(r"\s*(?:ssd|nvme|hdd|emmc|m\.?2|dysk|disk|storage|vram)", clean[end:])]
        if small and any(v >= 128 for v, _ in sizes):
            return small[0]
    return None


def _storage(text):
    match = STORAGE.search(text)
    if not match:
        return None
    number, unit = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
    return _gb(f"{number} {unit}")


MACBOOK = re.compile(r"\bmac\s*book\s*(air|pro)?\s*(?:(1[3-6])(?:[.,]\d)?\s*(?:\"|”|''|cal\w*|inch\w*)?)?\s*"
                     r"(?:\(?\s*(20[12]\d)\s*\)?)?")


def laptop(f, title, desc, attrs, listing):
    t, d = norm(title), norm(desc)
    f.put("model", norm(attrs.get("model_nav")) or None, "attribute")
    f.put("model", norm(listing.get("model")) or None, "attribute")
    match = MACBOOK.search(t)
    if match:
        f.put("model", " ".join(p for p in ("macbook", match.group(1), match.group(2), match.group(3)) if p), "title")
    for source, text in (("title", t), ("description", d)):
        f.put("cpu", _cpu(text), source)
    f.put("cpu_line", attrs.get("computer_cpu_line"), "attribute")
    if not f.get("cpu"):
        for source, text in (("title", t), ("description", d)):
            match = CPU_FAMILY.search(text)
            if match:
                f.put("cpu_line", f"intel core {match.group(1)}" if match.group(1) else f"amd ryzen {match.group(2)}",
                      source)
    for source, text in (("title", t), ("description", d)):
        f.put("gpu", _gpu(text), source)
    ram_attr = _gb(attrs.get("computer_ram")) if attrs.get("computer_ram") else None
    if ram_attr is not None and ram_attr > 128:          # „256 GB” w polu RAM = pomyłka (pewnie dysk)
        f.put("platform_field_errors", f"computer_ram={attrs.get('computer_ram')}", "attribute")
        ram_attr = None
    f.put("ram_gb", ram_attr, "attribute")
    for source, text in (("title", t), ("description", d)):
        f.put("ram_gb", _ram(text, loose=source == "title"), source)
    disk_attr = _gb(attrs.get("computer_storage_capacity")) if attrs.get("computer_storage_capacity") else None
    if disk_attr is not None and disk_attr < 32:         # „8 GB” dysku w laptopie = pomyłka (pewnie RAM)
        f.put("platform_field_errors", f"computer_storage_capacity={attrs.get('computer_storage_capacity')}",
              "attribute")
        disk_attr = None
    f.put("storage_gb", disk_attr, "attribute")
    for source, text in (("title", t), ("description", d)):
        f.put("storage_gb", _storage(text), source)
    for source, text in (("title", title), ("description", desc)):
        match = SCREEN.search(norm(text))
        if match:
            size = float(match.group(1).replace(",", "."))
            if 10 <= size <= 18.5:
                f.put("screen_in", size, source)
    f.put("screen_bucket", attrs.get("laptop_display_size"), "attribute")
    for source, text in (("title", t), ("description", d)):
        match = HZ.search(text)
        if match:
            f.put("refresh_hz", int(match.group(1)), source)
    charger = norm(attrs.get("laptop_charger_included"))
    if charger:
        f.put("charger", not charger.startswith("brak"), "attribute")
    f.put("os", attrs.get("computer_operating_system"), "attribute")
    gpu = f.get("gpu") or ""
    segment = ("macbook" if "macbook" in norm(f.get("model") or title) else
               "workstation" if re.match(r"(rtx a|quadro)", gpu) else
               "gaming" if re.match(r"(rtx|gtx|rx)", gpu) else
               "for_parts" if f.get("for_parts") else "other")
    f.put("segment", segment, "rule")


def laptop_key(f):
    cpu = f.get("cpu") or f.get("cpu_line")
    parts = [f.get("model"), cpu, f.get("gpu"), f.get("ram_gb"), f.get("storage_gb")]
    if sum(p is not None for p in parts) < 3:
        return None
    return "|".join("?" if p is None else str(p).lower() for p in parts)


# ---------------------------------------------------------------------------------------------- telefony / tablety

IPHONE = re.compile(r"\biphone\s*(se|x[rs]?|\d{1,2})\s*(pro\s*max|pro|plus|max|mini|e)?\b")
GALAXY = re.compile(r"\b(?:samsung\s*)?galaxy\s*([sazm]\d{1,2}|note\s*\d{1,2}|z\s*(?:fold|flip)\s*\d)\s*"
                    r"(ultra|plus|\+|fe|lite|edge)?\b")
PIXEL = re.compile(r"\bpixel\s*(\d{1,2}a?)\s*(pro\s*xl|pro|xl)?\b")
IPAD = re.compile(r"\bi\s?pad\s*(pro|air|mini)?\s*(\d{1,2}(?:[.,]\d)?(?:\s*(?:\"|cal\w*|inch))?)?\s*"
                  r"(?:\(?\s*(\d{1,2})\s*(?:gen|generacj\w*|th)\)?)?")
PHONE_STORAGE = re.compile(r"\b(16|32|64|128|256|512|1024|1)\s*(gb|tb)\b")


def _phone_model(text):
    match = IPHONE.search(text)
    if match:
        return " ".join(p for p in ("iphone", match.group(1), match.group(2)) if p).replace("  ", " ")
    match = GALAXY.search(text)
    if match:
        variant = (match.group(2) or "").replace("+", "plus")
        return " ".join(p for p in ("galaxy", match.group(1).replace(" ", ""), variant) if p)
    match = PIXEL.search(text)
    if match:
        return " ".join(p for p in ("pixel", match.group(1), match.group(2)) if p)
    return None


def phone(f, title, desc, attrs, listing, tablet=False):
    t, d = norm(title), norm(desc)
    for source, text in (("title", t), ("description", d)):
        f.put("model", _phone_model(text) if not tablet else None, source)
    f.put("model", norm(attrs.get("model_nav")) or None, "attribute")
    f.put("model", norm(listing.get("model")) or None, "attribute")
    if tablet:
        match = IPAD.search(t)
        if match:
            f.put("model", " ".join(p for p in ("ipad", match.group(1), match.group(2),
                                               f"gen {match.group(3)}" if match.group(3) else None) if p), "title")
    raw = attrs.get("internal_memory_capacity")
    if raw:
        value = _gb(raw)
        if value is None and "mb" in norm(raw):           # „256 MB” w formularzu = oczywista pomyłka → GB
            match = re.search(r"(\d+)", raw)
            value = int(match.group(1)) if match and int(match.group(1)) >= 16 else None
            if value:
                f.put("storage_gb", value, "model_guess")
        f.put("storage_gb", value, "attribute")
    for source, text in (("title", t), ("description", d)):
        match = PHONE_STORAGE.search(text)
        if match:
            f.put("storage_gb", _gb(match.group(0)), source)
    sim = norm(attrs.get("sim_lock"))
    if sim:
        f.put("sim_lock", not sim.startswith("brak"), "attribute")
    for_parts, locked = f.get("for_parts"), f.get("locked")
    f.put("segment", "for_parts" if for_parts else "locked" if locked else "working", "rule")


def phone_key(f):
    if not f.get("model"):
        return None
    return f"{f.get('model')}|{f.get('storage_gb') or '?'}"


# ---------------------------------------------------------------------------------------------- konsole

CONSOLE_VARIANT = re.compile(r"\b(slim|pro|fat|digital|disc|oled|lite|series\s*[xs]|one\s*[xs]?|360|2)\b")


def console(f, title, desc, attrs, listing):
    t = norm(title)
    f.put("platform", attrs.get("video_game_platform"), "attribute")
    match = CONSOLE_VARIANT.search(t)
    f.put("variant", match.group(1).replace(" ", "") if match else None, "title")
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(tb|gb)\b", t)
    f.put("storage_gb", _gb(match.group(0)) if match else None, "title")
    pads = re.search(r"\b(\d)\s*(?:x\s*)?(?:pad\w*|kontroler\w*|controller\w*|dualsense|joy-?con\w*)", norm(f"{title} {desc}"))
    f.put("controllers", int(pads.group(1)) if pads else None, "title")
    f.put("segment", "for_parts" if f.get("for_parts") else "working", "rule")


def console_key(f):
    if not f.get("platform"):
        return None
    return f"{f.get('platform')}|{f.get('variant') or '?'}|{f.get('storage_gb') or '?'}"


# ---------------------------------------------------------------------------------------------- podzespoły


def gpu_part(f, title, desc, attrs, listing):
    t, d = norm(title), norm(desc)
    for source, text in (("title", t), ("description", d)):
        gpu = _gpu(text)
        f.put("gpu", gpu if gpu != "integrated" else None, source)
    for source, text in (("title", t), ("description", d)):
        match = re.search(r"\b(\d{1,2})\s*gb\b", text)
        if match and 1 <= int(match.group(1)) <= 48:
            f.put("vram_gb", int(match.group(1)), source)
    f.put("segment", "for_parts" if f.get("for_parts") else "working", "rule")


def gpu_key(f):
    return f"{f.get('gpu')}|{f.get('vram_gb') or '?'}" if f.get("gpu") else None


def ram_part(f, title, desc, attrs, listing):
    text = norm(f"{title}\n{desc}")
    match = re.search(r"\b(?:lp)?ddr\s*([2345])\b", text)
    f.put("ram_type", f"ddr{match.group(1)}" if match else None, "title")
    form = "so-dimm" if re.search(r"\bso-?dimm|sodimm|laptop\w*|notebook\w*|\bsod\b", text) else \
        "dimm" if re.search(r"\b(?:u-?)?dimm\b|desktop|pc\b", text) else None
    f.put("form", form, "title")
    total = None
    match = re.search(r"\b(\d)\s*x\s*(\d{1,2})\s*gb\b", text) or re.search(r"\b(\d{1,2})\s*gb\s*\(\s*(\d)\s*x", text)
    if match:
        a, b = int(match.group(1)), int(match.group(2))
        total = a * b if a <= 8 else None
    if total is None:
        match = re.search(r"\b(\d{1,3})\s*gb\b", text)
        total = int(match.group(1)) if match else None
    f.put("total_gb", total, "title")
    match = re.search(r"\b(\d{4})\s*(?:mhz|mt/?s)\b", text)
    f.put("speed_mhz", int(match.group(1)) if match else None, "title")


def ram_key(f):
    return f"{f.get('ram_type') or '?'}|{f.get('form') or '?'}|{f.get('total_gb') or '?'}" if f.get("total_gb") else None


def storage_part(f, title, desc, attrs, listing):
    text = norm(f"{title}\n{desc}")
    kind = ("nvme" if re.search(r"\bnvme|pcie|m\.?2 ?2280|990 pro|980 pro|970 evo|sn\d{3}\b", text) else
            "sata_ssd" if re.search(r"\bssd\b|sata", text) else None)
    f.put("storage_type", kind, "title")
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(tb|gb)\b", norm(title)) or re.search(r"\b(\d+(?:[.,]\d+)?)\s*(tb|gb)\b", text)
    f.put("storage_gb", _gb(match.group(0)) if match else None, "title")
    match = re.search(r"\b(2280|2242|2230)\b", text)
    f.put("form", match.group(1) if match else ("2.5" if re.search(r'2[.,]5 ?(?:"|cal|inch)', text) else None), "title")


def storage_key(f):
    return f"{f.get('storage_type') or '?'}|{f.get('storage_gb')}" if f.get("storage_gb") else None


# ---------------------------------------------------------------------------------------------- całość

EXTRACTORS = {
    "laptop": (laptop, laptop_key),
    "phone": (phone, phone_key),
    "tablet": (lambda f, t, d, a, l: phone(f, t, d, a, l, tablet=True), phone_key),
    "console": (console, console_key),
    "gpu": (gpu_part, gpu_key),
    "ram": (ram_part, ram_key),
    "storage": (storage_part, storage_key),
}
COLUMNS = ("model", "cpu", "cpu_line", "gpu", "ram_gb", "storage_gb", "screen_in", "refresh_hz", "battery_pct",
           "condition_grade", "for_parts", "locked", "cracked", "segment")


def extract(category, title, description, attributes, listing=None):
    """→ (fields{nazwa: {value, source}}, config_key) albo (None, None) dla kategorii bez ekstraktora."""
    if category not in EXTRACTORS:
        return None, None
    fn, key_fn = EXTRACTORS[category]
    f = Fields()
    listing = listing or {}
    common(f, title or "", description or "", attributes or {}, listing)
    fn(f, title or "", description or "", attributes or {}, listing)
    return f.data, key_fn(f)


def run(conn, again=False, progress=None):
    """Ekstrakcja dla ofert z naszych kategorii (z opisem albo bez - wtedy tytuł + dane z katalogu). Zwraca liczbę."""
    from .db import utcnow

    say = progress or (lambda _t: None)
    where = "" if again else f"AND (x.listing_id IS NULL OR x.version < {VERSION} OR x.extracted_at < l.details_at)"
    rows = conn.execute(f"""SELECT l.id, l.category, l.title, l.model, l.status_label, d.description, d.attributes_json
                            FROM listings l LEFT JOIN details d ON d.listing_id = l.id
                            LEFT JOIN features x ON x.listing_id = l.id
                            WHERE l.category IN ({','.join('?' * len(EXTRACTORS))}) {where}""",
                        tuple(EXTRACTORS)).fetchall()
    say(f"Ofert do ekstrakcji: {len(rows)}")
    now, batch, done = utcnow(), [], 0
    for r in rows:
        attrs = json.loads(r["attributes_json"] or "{}")
        fields, key = extract(r["category"], r["title"], r["description"], attrs,
                              {"model": r["model"], "status_label": r["status_label"]})
        values = [(fields.get(c) or {}).get("value") for c in COLUMNS]
        values = [int(v) if isinstance(v, bool) else v for v in values]
        batch.append((r["id"], r["category"], VERSION, now, json.dumps(fields, ensure_ascii=False), key, *values))
        if len(batch) >= 2000:
            done += _flush(conn, batch)
            say(f"  zapisano {done}/{len(rows)}")
    done += _flush(conn, batch)
    say(f"  zapisano {done}/{len(rows)}")
    return done


def _flush(conn, batch):
    if not batch:
        return 0
    cols = ", ".join(COLUMNS)
    marks = ", ".join("?" * (6 + len(COLUMNS)))
    with conn:
        conn.executemany(f"INSERT OR REPLACE INTO features (listing_id, category, version, extracted_at, fields_json, "
                         f"config_key, {cols}) VALUES ({marks})", batch)
    n = len(batch)
    batch.clear()
    return n


def report(conn, top=15):
    """Pokrycie pól per kategoria + najczęstsze konfiguracje z liczbą ofert, sprzedanych i medianami cen."""
    lines = []
    for cat in EXTRACTORS:
        total = conn.execute("SELECT COUNT(*) FROM features WHERE category=?", (cat,)).fetchone()[0]
        if not total:
            continue
        fields = {}
        for (blob,) in conn.execute("SELECT fields_json FROM features WHERE category=?", (cat,)):
            for name, val in json.loads(blob).items():
                fields.setdefault(name, {}).setdefault(val["source"], 0)
                fields[name][val["source"]] += 1
        keyed = conn.execute("SELECT COUNT(*) FROM features WHERE category=? AND config_key IS NOT NULL",
                             (cat,)).fetchone()[0]
        lines.append(f"== {cat}: {total} ofert, z kluczem konfiguracji {keyed} ({keyed / total:.0%})")
        for name, by_src in sorted(fields.items(), key=lambda kv: -sum(kv[1].values())):
            n = sum(by_src.values())
            lines.append(f"   {name:<16} {n / total:6.1%}  ({', '.join(f'{s} {c}' for s, c in sorted(by_src.items()))})")
        lines.append(f"   najczęstsze konfiguracje (ofert / sprzedanych / mediana ceny / mediana ceny sprzedaży):")
        for key, n in conn.execute("SELECT config_key, COUNT(*) AS n FROM features WHERE category=? AND config_key "
                                   "IS NOT NULL GROUP BY config_key ORDER BY n DESC LIMIT ?", (cat, top)):
            prices = sorted(p for (p,) in conn.execute(
                "SELECT l.price_now FROM features x JOIN listings l ON l.id=x.listing_id WHERE x.config_key=? "
                "AND l.price_now IS NOT NULL", (key,)))
            sold = sorted(p for (p,) in conn.execute(
                "SELECT l.sold_price FROM features x JOIN listings l ON l.id=x.listing_id WHERE x.config_key=? "
                "AND l.state='sold' AND l.sold_price IS NOT NULL", (key,)))
            med = lambda xs: f"{xs[len(xs) // 2]:.0f} zł" if xs else "-"   # noqa: E731
            lines.append(f"     {n:>5} / {len(sold):>4} / {med(prices):>9} / {med(sold):>9}   {key}")
    return lines or ["Brak wyników - najpierw: python -m analyzer extract"]
