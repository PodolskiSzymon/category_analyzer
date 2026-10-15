"""Klasyfikacja ofert z kategorii „mieszanych” Vinted (podzespoły 3582, nośniki 3583, akcesoria komputerowe 3584)
do NASZYCH kategorii przedmiotu – bez sieci, tylko z tytułu i marki/modelu z formularza (`item_box`).

Prośba użytkownika 2026-10-14: zbieramy karty graficzne (`gpu`), pamięci RAM (`ram`), dyski SSD/NVMe – także do
konsol, bez HDD (`storage`); gry – odpuszczone (rozpoznawane tylko, żeby je odrzucić); laptopy / konsole / telefony / tablety wystawione w złej kategorii trafiają
do istniejących kategorii (`laptop`, `console`, `phone`, `tablet`). Reszta = `ignored` (nie śledzimy, nie pobieramy
szczegółów, nie sprawdzamy zniknięć). Nierozpoznane = `unknown` (stan `unclassified`, bez kosztu proxy) – do raportu
`classify-report`, poprawy reguł (`reclassify`, offline) albo później AI.

Wybór reguły (od 2026-10-15): zwroty „do laptopa”, „na PS5”, „for laptop” są usuwane („RAM do laptopa” = RAM),
potem wygrywa reguła, której słowo pada w tytule NAJWCZEŚNIEJ (remis → kolejność RULES). Dzięki temu
„Laptop Dell + zasilacz” to laptop, a „Zasilacz Dell Latitude” / „Bateria MacBook” – część (ignored).
Ogólne „dysk” bez SSD/NVMe sprawdzane na końcu (FALLBACK). Słowa także po czesku, słowacku, litewsku, węgiersku,
rumuńsku, chorwacku, niemiecku, skandynawsku – na polskim Vinted jest dużo ofert zagranicznych.
Ignored: akcesoria i części spoza zakresu, procesory, płyty główne, zasilacze, chłodzenie, HDD, komputery
stacjonarne, gry; reszta → unknown.
"""
import re
import unicodedata

CATEGORY_BY_CATALOG = {3580: "laptop", 3661: "phone", 3025: "console", 3728: "tablet"}
MIXED_CATALOGS = (3582, 3583, 3584)
WANTED = ("laptop", "phone", "console", "tablet", "gpu", "ram", "storage")

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
    r"tasm\w*", r"raspberry", r"arduino", r"matryc\w*", r"bateri\w*", r"akumulator\w*", r"klawisz\w*", r"zawias\w*", r"glosnik\w*",
    r"hdd", r"dysk\w*\s+tward\w*", r"\d{4}\s*rpm", r"barracuda", r"ironwolf", r"wd\s+(?:blue|red|purple)\s+\d+\s*tb",
    r"pendrive\w*", r"pen\s*drive", r"flash\s*drive", r"usb\s+stick", r"karta?\s+(?:pamieci\s+)?(?:micro\s*)?sd\w*",
    r"microsd\w*", r"sdxc", r"sdhc", r"karta?\s+sim", r"sim\s*card", r"plyt\w*\s+(?:cd|dvd|blu)\w*", r"cd-r\w*",
    r"dvd-r\w*", r"czyst\w*\s+plyt\w*", r"riser\w*", r"backplate", r"uchwyt\w*", r"listw\w*", r"ups", r"router\w*",
    r"monitor\w*", r"drukark\w*", r"toner\w*", r"tusz\w*", r"kamer\w*", r"webcam\w*", r"mikrofon\w*", r"sluchawk\w*",
    r"headset\w*", r"kierownic\w*", r"joystick\w*", r"tabliczk\w*", r"plytk\w*\s+wzmacniaj\w*",
    r"karta?\s+sieciow\w*", r"wifi\s+card", r"modul\w*\s+wi-?fi", r"antena\w*", r"oprogramowani\w*", r"licencj\w*",
    r"windows\s+(?:10|11)\s+(?:pro|home)\s+klucz", r"klucz\s+(?:aktywacyjn|licencyj)\w*", r"gamepad\w*",
    r"dysk\w*\s+zewnetrzn\w*(?!.*\bssd)", r"external\s+(?:hard\s+)?drive(?!.*\bssd)",
    # zasilacze (RO, HU, CZ/SK, LT, DE, HR, DK/NO, SE, FR, IT, NL)
    r"sursa\w*", r"tapegyseg\w*", r"napajec\w*", r"napajeni\w*", r"maitinimo\s+blok\w*", r"netzteil\w*",
    r"napajanj\w*", r"stromforsyning\w*", r"nataggregat\w*", r"alimentation", r"alimentator\w*",
    r"voeding\w*",
    # chłodzenie
    r"chlodnic\w*", r"aio", r"liquid\s+freezer\w*", r"\w*hutes\w*", r"ausintuv\w*", r"flakt\w*", r"ventilato\w*",
    r"ventilatory", r"fans", r"fan\s+\d+\s*mm", r"shield\s+tv", r"kuhler\w*", r"chladic\w*", r"chladeni\w*", r"vodni\s+chlazeni", r"dissipator\w*",
    r"galahad\w*", r"hyper\s*212",
    # HDD (CZ/SK „pevný disk”, HR „tvrdi disk”, HU „merevlemez”, DE, RO, LT, DK …) i stare dyski
    r"harddisk\w*", r"hard\s*-?\s*disk\w*", r"hard\s*-?\s*extern\w*", r"my\s*cloud", r"wd\s+elements",
    r"elements\s+(?:desktop|portable)", r"mg0\d\w*", r"hard\s*drive\w*", r"tvrd\w*\s+disk\w*", r"pevn\w*\s+disk\w*", r"merevlemez\w*",
    r"festplatte\w*", r"hhd", r"kietas\w*\s+disk\w*", r"disco\s+(?:duro|rigido)", r"medalist", r"quantum",
    r"exos", r"wd\s+(?:blue|red|purple|green|gold)(?!.*(?:\bsn\d|\bsa\d|ssd|nvme|m\.?2))", r"skyhawk", r"ultrastar",
    # pamięć flash, karty dźwiękowe, NAS, powerbanki
    r"flashk\w*", r"usb\s+flash\w*", r"karta?\s+dzwiekow\w*", r"sound\s*blaster\w*", r"sound\s*card", r"synology",
    r"qnap", r"nas", r"nvr", r"dvr", r"microsoft\s+365", r"office\s+20\d\d", r"stream\s*deck", r"elgato",
    r"capture\s+card", r"tower\s+case", r"\w*chassi\w*", r"source", r"zdroj\w*", r"ljudkort\w*", r"lydkort\w*", r"powerbank\w*", r"power\s*bank",
)
# Procesory i płyty główne (osobno, żeby „Laptop i5-8250U” nie był odrzucany – procesory laptopowe H/U/HS/HX
# nie pasują do wzorców poniżej).
PARTS = _words(
    r"procesor\w*", r"processzor\w*", r"processor\w*", r"procesad\w*", r"cpu", r"xeon", r"athlon\w*",
    r"ryzen\s*(?:[3579]\s*)?\d{4}(?:x3d|xt|x|g|ge|f|af)?(?![a-z0-9])",
    r"(?:core\s*)?i[3579]\s*-?\s*\d{4,5}(?:k|kf|f|t|ks|te)?(?![a-z0-9])",
    r"plyt\w*\s+glown\w*", r"motherboard\w*", r"mainboard\w*", r"alaplap\w*", r"zakladn\w*\s+dosk\w*",
    r"zakladni\s+desk\w*", r"maticn\w*\s+ploc\w*", r"placa\s+(?:de\s+baza|base|madre)", r"moderkort\w*",
    r"materska\s+dosk\w*", r"pagrindin\w*\s+plokst\w*", r"scheda\s+madre", r"carte\s+mere",
    r"(?:a320|a520|a620|b350|b450|b550|b650|b840|b850|x370|x470|x570|x670|x870|h61|h81|h110|h310|h410|h510|h610|"
    r"b250|b360|b365|b460|b560|b660|b760|b860|z170|z270|z370|z390|z490|z590|z690|z790|z890|x99|x299)\w*",
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
                r"surface\s+(?:laptop|book)", r"galaxy\s+book\w*", r"lg\s+gram", r"tuf\s+(?:gaming|dash)",
                # procesor laptopowy (H/HS/HX/HK/HQ/U) w tytule = laptop („Asus TUF Ryzen 7 4800H RTX 3050”)
                r"(?:i[3579]|ryzen\s*[3579])\s*-?\s*\d{4,5}(?:h|hs|hx|hk|hq|u)(?![a-z0-9])")
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
             r"rtx\s*a\d{3,4}", r"arc\s+a\d{3}", r"plac\w*\s+video", r"r[79]\s*\d{3}x?", r"radeon\s+hd\s*\d{4}",
             r"\d{4}\s*ti", r"titan\s+(?:x|rtx|v)\w*", r"3dfx", r"voodoo\s*\d?",
             r"vaizdo\s+plokst\w*", r"videokart\w*", r"videokaart\w*", r"grafikkart\w*", r"graficka\s+kart\w*",
             r"placa\s+(?:video|grafica|de\s+video)", r"carte\s+graphique", r"scheda\s+video", r"grafikus\s+kartya",
             r"videokartya", r"graficna\s+kartic\w*")
RAM = _words(r"ram", r"ddr[2345]\w*", r"so-?dimm\w*", r"dimm\w*", r"pamiec\w*\s+(?:ram|operacyjn\w*)", r"memory\s+kit",
             r"(?:fury|vengeance|ripjaws|trident\s*z|viper\s+(?:venom|steel|elite)|ballistix|dominator|xpg\s+lancer|lancer)\w*",
             r"operatyv\w*\s+atmint\w*", r"memori\w*\s+ram", r"arbeitsspeicher\w*", r"operacn\w*\s+pam\w*",
             r"rendszermemori\w*", r"radn\w*\s+memorij\w*", r"pamat\s+ram")
STORAGE = _words(r"nvme\w*", r"m\.?2", r"ssd\w*", r"pcie\s*[345]\.?0?", r"(?:970|980|990)\s*(?:evo|pro)\w*",
                 r"sn\d{3}\w*", r"kc3000", r"nv[123]", r"a2000", r"p[35]\s*plus", r"mx500", r"t[579]\s*(?:shield)?",
                 r"karta?\s+rozszerze\w*", r"expansion\s+card", r"storage\s+expansion", r"legend\s+\d{3}",
                 r"mz-?[v7n][0-9a-z]{3,}", r"a400", r"(?:860|870)\s*(?:evo|qvo|pro)", r"(?:bx|mx)500", r"sa\d{3}", r"firecuda\s*\d{3}")
# Ogólne „dysk” (bez SSD/NVMe/HDD w tytule) - na końcu, gdy nic innego nie pasuje.
STORAGE_GENERIC = _words(r"dysk\w*")
# Sama marka NVIDIA (często tylko w polu marki formularza) - też dopiero na końcu („Nvidia Shield TV” to nie karta).
GPU_BRAND = _words(r"nvidia")
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
    ("ignored", "procesor/płyta", PARTS),
    ("gpu", "karta graficzna", GPU),
    ("ram", "RAM", RAM),
    ("storage", "dysk SSD/NVMe", STORAGE),
    # Gry odpuszczone 2026-10-14 (użytkownik) - rozpoznajemy je tylko po to, żeby odrzucić.
    ("ignored", "gra (pominięte)", GAME),
    ("ignored", "akcesorium (słabe)", WEAK_JUNK),
)
FALLBACK = (
    ("storage", "dysk (ogólny)", STORAGE_GENERIC),
    ("gpu", "marka NVIDIA", GPU_BRAND),
)


def normalize(text):
    """Małe litery, bez polskich znaków i akcentów, „×” → „x”, pojedyncze spacje."""
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("ł", "l").replace("×", "x"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _prepare(title, label=""):
    text = normalize(f"{title or ''} | {label or ''}")
    return _TARGET.sub(" ", text)              # „RAM do laptopa” → „RAM”


def _matches(text):
    """Wszystkie pasujące reguły: [(pozycja, kolejność, kategoria, opis)] - najwcześniejsze słowo pierwsze."""
    found = []
    for order, (category, name, pattern) in enumerate(RULES):
        match = pattern.search(text)
        if match:
            found.append((match.start(), order, category, f"{name}: {match.group(0)}"))
    return sorted(found)


def classify_text(title, label=""):
    """(kategoria, reguła) dla tytułu (+ marka/model z formularza). Kategoria ∈ WANTED ∪ {ignored, unknown}."""
    text = _prepare(title, label)
    found = _matches(text)
    if found:
        return found[0][2], found[0][3]
    for category, name, pattern in FALLBACK:
        match = pattern.search(text)
        if match:
            return category, f"{name}: {match.group(0)}"
    return "unknown", None


def needs_photo_check(title, label=""):
    """True, gdy tytuł pasuje do RAM-u I do innej kategorii („Laptop Dell 16GB RAM”, „Płyta + procesor + RAM”) -
    wtedy o kategorii decyduje AI ze zdjęcia głównego (ai_classify.py), a nie kolejność słów (prośba użytkownika
    2026-10-15). Do tego czasu oferta ma kategorię z reguł (tymczasową)."""
    categories = {category for _, _, category, _ in _matches(_prepare(title, label))}
    return "ram" in categories and len(categories) > 1


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
    checks = conn.execute(f"SELECT category_check, COUNT(*) FROM listings WHERE catalog_id IN ({marks}) "
                          "AND category_check IS NOT NULL GROUP BY category_check", MIXED_CATALOGS).fetchall()
    if checks:
        lines.append("Zdjęcie przez AI (RAM + inna kategoria w tytule): "
                     + ", ".join(f"{r[0]} {r[1]}" for r in checks))
        for r in conn.execute(f"SELECT title, category, category_rule FROM listings WHERE catalog_id IN ({marks}) "
                              "AND category_src='ai' ORDER BY state_at DESC LIMIT 15", MIXED_CATALOGS):
            lines.append(f"    {r['category']:<8} {(r['title'] or '')[:60]:<60}  ← {r['category_rule']}")
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


def reclassify(conn, min_for=None, progress=None, chunk=2000):
    """Ponownie stosuje reguły do zapisanych ofert z kategorii mieszanych (category_src = rule). Bez sieci - po poprawce
    reguł nie trzeba nic pobierać. Zwraca {(stara, nowa): liczba}.

    Najpierw liczy wszystko bez blokady bazy, potem zapisuje porcjami po `chunk` wierszy (krótkie transakcje - może
    działać równolegle z `watch`). progress(tekst) - opcjonalne komunikaty o postępie."""
    from .db import utcnow

    say = progress or (lambda _text: None)
    marks = ",".join("?" * len(MIXED_CATALOGS))
    changes = {}
    now = utcnow()
    rows = conn.execute(f"SELECT id, title, brand, model, category, state, price_now, category_check FROM listings "
                        f"WHERE catalog_id IN ({marks}) AND category_src='rule'", MIXED_CATALOGS).fetchall()
    say(f"Ofert z kategorii mieszanych: {len(rows)} - klasyfikuję...")
    updates, pending = [], []
    for r in rows:
        label = " ".join(x for x in (r["brand"], r["model"]) if x)
        if r["category_check"] is None and needs_photo_check(r["title"], label):
            pending.append((r["id"],))
        category, rule = classify_text(r["title"], label)
        if category == r["category"]:
            continue
        state = state_for(category, r["state"], r["price_now"], min_for)
        updates.append((category, rule, state, now, r["id"]))
        changes[(r["category"], category)] = changes.get((r["category"], category), 0) + 1
    say(f"Do zmiany: {len(updates)} - zapisuję...")
    for start in range(0, len(updates), chunk):
        with conn:
            conn.executemany("UPDATE listings SET category=?, category_rule=?, state=?, state_at=? WHERE id=?",
                             updates[start:start + chunk])
        say(f"  zapisano {min(start + chunk, len(updates))}/{len(updates)}")
    if pending:
        with conn:
            conn.executemany("UPDATE listings SET category_check='pending' WHERE id=?", pending)
        say(f"Do sprawdzenia zdjęcia przez AI (RAM + inna kategoria w tytule): {len(pending)}")
    return changes


def state_for(category, old_state, price, min_for=None):
    """Stan oferty po zmianie kategorii (reclassify / AI). sold / deleted / closed zostają."""
    from .db import REVIVABLE

    if old_state not in REVIVABLE:
        return old_state
    if category == "ignored":
        return "ignored"
    if category == "unknown":
        return "unclassified"
    low = min_for(category) if min_for else 0
    return "below_min" if low and (price or 0) < low else "active"
