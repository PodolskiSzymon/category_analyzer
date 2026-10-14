"""Klasyfikacja ofert z kategorii „mieszanych” Vinted (podzespoły 3582, nośniki 3583, akcesoria komputerowe 3584)
do NASZYCH kategorii przedmiotu – bez sieci, tylko z tytułu i marki/modelu z formularza (`item_box`).

Prośba użytkownika 2026-10-14: zbieramy karty graficzne (`gpu`), pamięci RAM (`ram`), dyski SSD/NVMe – także do
konsol, bez HDD (`storage`) i gry (`game`); laptopy / konsole / telefony / tablety wystawione w złej kategorii trafiają
do istniejących kategorii (`laptop`, `console`, `phone`, `tablet`). Reszta = `ignored` (nie śledzimy, nie pobieramy
szczegółów, nie sprawdzamy zniknięć). Nierozpoznane = `unknown` (stan `unclassified`, bez kosztu proxy) – do raportu
`classify-report`, poprawy reguł (`reclassify`, offline) albo później AI.

Kolejność reguł ma znaczenie:
  1. zwroty „do laptopa”, „na PS5”, „for laptop” są usuwane przed szukaniem urządzeń („RAM do laptopa” = RAM),
  2. ewidentne akcesoria / części, których nie zbieramy („podstawka chłodząca”, „torba”, „HDD”) → ignored,
  3. komputery stacjonarne → ignored (nie zbieramy),
  4. urządzenia: laptop, konsola, telefon, tablet (przed podzespołami – „Laptop RTX 3060” to laptop),
  5. podzespoły: gpu, ram, storage, gra,
  6. słabe słowa „śmieciowe” (klawiatura, mysz, kabel…) → ignored,
  7. reszta → unknown.
"""
import re
import unicodedata

CATEGORY_BY_CATALOG = {3580: "laptop", 3661: "phone", 3025: "console", 3728: "tablet", 3026: "game"}
MIXED_CATALOGS = (3582, 3583, 3584)
WANTED = ("laptop", "phone", "console", "tablet", "gpu", "ram", "storage", "game")

DEVICE_WORDS = (r"laptop\w*|notebook\w*|macbook\w*|komputer\w*|pc|ps[345]|playstation\s*\d?|xbox\w*|switch\w*|"
                r"steam\s*deck|telefon\w*|iphone\w*|smartfon\w*|tablet\w*|ipad\w*|konsol\w*|console\w*|"
                r"nintendo|deck|ally|legion\s*go")
# „RAM do laptopa”, „dysk na PS5”, „for laptop”, „pentru laptop”, „für Notebook”, „pro notebook”
_TARGET = re.compile(rf"\b(?:do|z|ze|pod|na|dla|for|fur|pentru|pro|til|fur|per|pour|para|voor)\s+(?:\w+\s+)?(?:{DEVICE_WORDS})\b")


def _words(*items):
    return re.compile(r"\b(?:" + "|".join(items) + r")\b")


# 2. Ewidentne akcesoria / części spoza zakresu – sprawdzane przed urządzeniami („podstawka pod laptopa”).
STRONG_JUNK = _words(
    r"podstawk\w*", r"podkladk\w*", r"chlodzac\w*", r"cooling\s*pad", r"torb\w*", r"etui", r"pokrowi\w*", r"plecak\w*",
    r"sleeve", r"case\s+(?:na|do|for)", r"naklejk\w*", r"sticker\w*", r"skin\w*", r"folia", r"szklo\s+ochronne",
    r"ladowark\w*", r"charger", r"zasilacz\w*", r"psu", r"power\s*supply", r"kabel\w*", r"kable", r"cable\w*",
    r"przewod\w*", r"adapter\w*", r"przejsciowk\w*", r"hub\w*", r"stacj\w*\s+dokujac\w*", r"docking", r"obudow\w*",
    r"wentylator\w*", r"chlodzeni\w*", r"cooler\w*", r"radiator\s+do", r"pasta\s+termo\w*", r"termopad\w*",
    r"tasm\w*", r"raspberry", r"arduino", r"plyt\w*\s+glown\w*", r"motherboard", r"mainboard", r"procesor\w*",
    r"cpu", r"matryc\w*", r"bateri\w*", r"akumulator\w*", r"klawisz\w*", r"zawias\w*", r"glosnik\w*",
    r"hdd", r"dysk\w*\s+tward\w*", r"\d{4}\s*rpm", r"barracuda", r"ironwolf", r"wd\s+(?:blue|red|purple)\s+\d+\s*tb",
    r"pendrive\w*", r"pen\s*drive", r"flash\s*drive", r"usb\s+stick", r"karta?\s+(?:pamieci\s+)?(?:micro\s*)?sd\w*",
    r"microsd\w*", r"sdxc", r"sdhc", r"karta?\s+sim", r"sim\s*card", r"plyt\w*\s+(?:cd|dvd|blu)\w*", r"cd-r\w*",
    r"dvd-r\w*", r"czyst\w*\s+plyt\w*", r"riser\w*", r"backplate", r"uchwyt\w*", r"listw\w*", r"ups", r"router\w*",
    r"monitor\w*", r"drukark\w*", r"toner\w*", r"tusz\w*", r"kamer\w*", r"webcam\w*", r"mikrofon\w*", r"sluchawk\w*",
    r"headset\w*", r"kierownic\w*", r"joystick\w*", r"tabliczk\w*", r"plytk\w*\s+wzmacniaj\w*",
    r"karta?\s+sieciow\w*", r"wifi\s+card", r"modul\w*\s+wi-?fi", r"antena\w*", r"oprogramowani\w*", r"licencj\w*",
    r"windows\s+(?:10|11)\s+(?:pro|home)\s+klucz", r"klucz\s+(?:aktywacyjn|licencyj)\w*", r"gamepad\w*",
    r"dysk\w*\s+zewnetrzn\w*(?!.*\bssd)", r"external\s+(?:hard\s+)?drive(?!.*\bssd)",
)
# 3. Komputery stacjonarne (nie zbieramy – użytkownik 2026-10-14).
DESKTOP = _words(r"komputer[a-z]*(?![a-z])(?!\s+przenosn)", r"optiplex", r"prodesk", r"elitedesk", r"thinkcentre",
                 r"komputer\w*\s+stacjonarn\w*", r"stacjonarn\w*", r"zestaw\w*\s+komputerow\w*", r"desktop\w*",
                 r"pc\s+(?:gamingow\w*|gaming|do\s+gier)", r"gaming\s+pc", r"komputer\w*\s+(?:gamingow\w*|do\s+gier)",
                 r"mini\s*pc", r"all\s*in\s*one", r"nuc", r"imac\w*", r"mac\s*mini", r"mac\s*studio", r"mac\s*pro")
# 4. Urządzenia (do istniejących kategorii).
LAPTOP = _words(r"laptop\w*", r"komputer\w*\s+przenosn\w*", r"notebook\w*", r"netbook\w*", r"ultrabook\w*", r"macbook\w*", r"chromebook\w*",
                r"thinkpad\w*", r"latitude", r"elitebook\w*", r"probook\w*", r"zbook\w*", r"precision\s+\d{4}",
                r"ideapad\w*", r"thinkbook\w*", r"yoga\s+(?:slim|pro|\d)", r"vivobook\w*", r"zenbook\w*",
                r"expertbook\w*", r"rog\s+(?:strix|zephyrus|flow)", r"strix\s+(?:g|scar)\w*", r"scar\s+\d+", r"tuf\s+(?:gaming\s+)?[fa]\d+",
                r"legion\s+(?:\d|pro|slim|y\d)\w*", r"omen\s+\d+", r"victus", r"pavilion", r"envy\s+x360", r"spectre",
                r"predator\s+helios", r"helios", r"nitro\s+[5v]", r"aspire", r"swift\s+\d", r"inspiron", r"xps\s+1[3-7]",
                r"alienware\s+[mx]\d+", r"katana", r"raider", r"stealth", r"razer\s+blade", r"matebook\w*",
                r"surface\s+(?:laptop|book)", r"galaxy\s+book\w*", r"lg\s+gram")
# Sama nazwa platformy („FIFA 23 PS4”) to zwykle gra – konsola dopiero z wersją / pojemnością / słowem „konsola”.
CONSOLE = _words(r"konsol\w*", r"console\w*", r"steam\s*deck", r"rog\s+ally", r"legion\s+go", r"ps\s*vita",
                 r"xbox\s+series\s+[xs]",
                 r"(?:ps[345]|playstation\s*[345]|xbox\s+(?:one\s*[sx]?|360)|nintendo\s+switch|switch)\s+"
                 r"(?:slim|pro|fat|digital|disc|oled|lite|2|\d+\s*(?:gb|tb))")
PHONE = _words(r"iphone\s*\d+\w*", r"smartfon\w*", r"telefon\w*", r"galaxy\s+(?:s|a|z|note)\s*\d+\w*", r"pixel\s*\d+",
               r"redmi\s+note", r"xiaomi\s+\d+")
TABLET = _words(r"tablet\w*", r"ipad\w*", r"galaxy\s+tab\w*", r"surface\s+(?:pro|go)", r"kindle", r"e-?czytnik\w*")
# 5. Podzespoły, które zbieramy.
GPU = _words(r"rtx\s*\d{3,4}\w*", r"gtx\s*\d{3,4}\w*", r"geforce", r"radeon\s+(?:rx|r9|vii|pro)\w*", r"rx\s*\d{3,4}\s*(?:xt|xtx)?",
             r"karta?\s+graficzn\w*", r"kart\w*\s+graficzn\w*", r"grafik\w*", r"graphics\s+card", r"gpu", r"quadro\w*",
             r"rtx\s*a\d{3,4}", r"arc\s+a\d{3}", r"titan\s+(?:x|rtx|v)\w*")
RAM = _words(r"ram", r"ddr[2345]\w*", r"so-?dimm\w*", r"dimm\w*", r"pamiec\w*\s+(?:ram|operacyjn\w*)", r"memory\s+kit",
             r"(?:fury|vengeance|ripjaws|trident\s*z|viper\s+(?:venom|steel|elite)|ballistix|dominator|xpg\s+lancer|lancer)\w*")
STORAGE = _words(r"nvme\w*", r"m\.?2", r"ssd\w*", r"pcie\s*[345]\.?0?", r"(?:970|980|990)\s*(?:evo|pro)\w*",
                 r"sn\d{3}\w*", r"kc3000", r"nv[123]", r"a2000", r"p[35]\s*plus", r"mx500", r"t[579]\s*(?:shield)?",
                 r"karta?\s+rozszerze\w*", r"expansion\s+card", r"storage\s+expansion", r"dysk\w*\s+(?:do|na)\s+(?:ps5|xbox)",
                 r"dysk\w*")
GAME = _words(r"gra", r"gry", r"game\w*", r"(?:ps[345]|xbox|switch|pc)\s+(?:gra|game)", r"steelbook\w*",
              r"(?:fifa|fc\s*2[4-6]|gta|call\s+of\s+duty|minecraft|zelda|mario|pokemon|elden\s+ring|spider-?man|"
              r"god\s+of\s+war|horizon|cyberpunk|red\s+dead|witcher|wiedzmin)\w*")
# 6. Słabe słowa „śmieciowe”.
WEAK_JUNK = _words(r"klawiatur\w*", r"keyboard\w*", r"mysz\w*", r"myszk\w*", r"mouse", r"pad\w*", r"kontroler\w*",
                   r"controller\w*", r"dualsense", r"dualshock", r"joy-?con\w*", r"ozdob\w*", r"figurk\w*", r"lamp\w*",
                   r"led", r"rgb\s+(?:tasma|pasek)", r"zabawk\w*", r"plakat\w*", r"podkladk\w*", r"glosnik\w*",
                   r"skaner\w*", r"projektor\w*", r"smartwatch\w*", r"zegarek\w*", r"opask\w*")

RULES = (
    ("ignored", "akcesorium/część", STRONG_JUNK),
    ("ignored", "komputer stacjonarny", DESKTOP),
    ("laptop", "laptop", LAPTOP),
    ("console", "konsola", CONSOLE),
    ("tablet", "tablet", TABLET),
    ("phone", "telefon", PHONE),
    ("gpu", "karta graficzna", GPU),
    ("ram", "RAM", RAM),
    ("storage", "dysk SSD/NVMe", STORAGE),
    ("game", "gra", GAME),
    ("ignored", "akcesorium (słabe)", WEAK_JUNK),
)


def normalize(text):
    """Małe litery, bez polskich znaków i akcentów, „×” → „x”, pojedyncze spacje."""
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("ł", "l").replace("×", "x"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def classify_text(title, label=""):
    """(kategoria, reguła) dla tytułu (+ marka/model z formularza). Kategoria ∈ WANTED ∪ {ignored, unknown}."""
    text = normalize(f"{title or ''} | {label or ''}")
    stripped = _TARGET.sub(" ", text)          # „RAM do laptopa” → „RAM”
    for category, name, pattern in RULES:
        source = stripped if category in ("laptop", "console", "tablet", "phone", "ignored") else text
        match = pattern.search(source)
        if match:
            return category, f"{name}: {match.group(0)}"
    return "unknown", None


def classify_item(item, catalog_id):
    """(kategoria, źródło, reguła) dla pozycji katalogu. Kategorie jednorodne – z katalogu, mieszane – z reguł."""
    catalog_id = int(catalog_id)
    if catalog_id not in MIXED_CATALOGS:
        return CATEGORY_BY_CATALOG.get(catalog_id, f"catalog_{catalog_id}"), "catalog", None
    label = " ".join(x for x in (getattr(item, "brand", None), getattr(item, "model", None)) if x)
    category, rule = classify_text(getattr(item, "title", ""), label)
    return category, "rule", rule


# ---------------------------------------------------------------- raport i ponowna klasyfikacja (offline, bez sieci)

def report(conn, examples=40):
    """Ile ofert z kategorii mieszanych trafiło do której naszej kategorii + przykłady nierozpoznanych i odrzuconych
    (do poprawy reguł i decyzji, czy klasyfikacja AI się opłaci)."""
    marks = ",".join("?" * len(MIXED_CATALOGS))
    lines = []
    rows = conn.execute(f"SELECT catalog_id, category, COUNT(*) AS n FROM listings WHERE catalog_id IN ({marks}) "
                        "GROUP BY catalog_id, category ORDER BY catalog_id, n DESC", MIXED_CATALOGS).fetchall()
    by_catalog = {}
    for r in rows:
        by_catalog.setdefault(r["catalog_id"], []).append((r["category"], r["n"]))
    for catalog_id, cats in by_catalog.items():
        total = sum(n for _, n in cats)
        unknown = sum(n for c, n in cats if c == "unknown")
        wanted = sum(n for c, n in cats if c in WANTED)
        lines.append(f"Katalog {catalog_id}: {total} ofert - nasze {wanted} ({wanted / total:.0%}), nierozpoznane "
                     f"{unknown} ({unknown / total:.0%}), odrzucone {total - wanted - unknown}")
        lines.append("    " + ", ".join(f"{c} {n}" for c, n in cats))
    if not by_catalog:
        return ["Brak ofert z kategorii mieszanych - najpierw crawl."]
    lines.append("")
    lines.append("Najczęstsze reguły odrzucenia:")
    for r in conn.execute(f"""SELECT substr(category_rule, 1, instr(category_rule || ':', ':') - 1) || ': ' ||
                                     trim(substr(category_rule, instr(category_rule, ':') + 1)) AS rule, COUNT(*) AS n
                              FROM listings WHERE catalog_id IN ({marks}) AND category='ignored'
                              GROUP BY rule ORDER BY n DESC LIMIT 15""", MIXED_CATALOGS):
        lines.append(f"    {r['n']:>6}  {r['rule']}")
    lines.append("")
    lines.append(f"Przykłady nierozpoznanych (do reguł / AI), {examples} najnowszych:")
    for r in conn.execute(f"SELECT title, brand, model, price_now FROM listings WHERE catalog_id IN ({marks}) "
                          "AND category='unknown' ORDER BY id DESC LIMIT ?", (*MIXED_CATALOGS, examples)):
        label = " / ".join(x for x in (r["brand"], r["model"]) if x)
        lines.append(f"    {r['price_now'] or 0:>8.2f} zł  {r['title']}" + (f"  [{label}]" if label else ""))
    lines.append("")
    lines.append("Przykłady odrzuconych (sprawdź, czy nie ma tu naszych przedmiotów):")
    for r in conn.execute(f"SELECT title, category_rule, price_now FROM listings WHERE catalog_id IN ({marks}) "
                          "AND category='ignored' ORDER BY RANDOM() LIMIT 20", MIXED_CATALOGS):
        lines.append(f"    {r['price_now'] or 0:>8.2f} zł  {r['title']}  ← {r['category_rule']}")
    return lines


def reclassify(conn, min_for=None):
    """Ponownie stosuje reguły do zapisanych ofert z kategorii mieszanych (category_src = rule). Bez sieci - po poprawce
    reguł nie trzeba nic pobierać. Zwraca {(stara, nowa): liczba}."""
    from .db import REVIVABLE, utcnow

    marks = ",".join("?" * len(MIXED_CATALOGS))
    changes = {}
    now = utcnow()
    rows = conn.execute(f"SELECT id, title, brand, model, category, state, price_now FROM listings "
                        f"WHERE catalog_id IN ({marks}) AND category_src='rule'", MIXED_CATALOGS).fetchall()
    with conn:
        for r in rows:
            label = " ".join(x for x in (r["brand"], r["model"]) if x)
            category, rule = classify_text(r["title"], label)
            if category == r["category"]:
                continue
            if category == "ignored":
                state = "ignored"
            elif category == "unknown":
                state = "unclassified"
            else:
                low = min_for(category) if min_for else 0
                state = "below_min" if low and (r["price_now"] or 0) < low else "active"
            if r["state"] not in REVIVABLE:
                state = r["state"]
            conn.execute("UPDATE listings SET category=?, category_rule=?, state=?, state_at=? WHERE id=?",
                         (category, rule, state, now, r["id"]))
            changes[(r["category"], category)] = changes.get((r["category"], category), 0) + 1
    return changes
