"""Kompresja surowego JSON do tabeli `raw`.

zstd (pakiet `zstandard`), gdy jest zainstalowany; inaczej zlib z biblioteki standardowej. Format rozpoznajemy po
nagłówku, więc baza może mieszać oba (np. po doinstalowaniu zstandard). Słownik zstd trenowany na próbce - później,
gdy będzie dość danych (ARCHITEKTURA.md, sekcja 3).
"""
import json
import zlib

try:
    import zstandard
except ImportError:  # opcjonalny
    zstandard = None

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def compress(obj):
    data = dumps(obj)
    if zstandard is not None:
        return zstandard.ZstdCompressor(level=10).compress(data)
    return zlib.compress(data, 9)


def decompress(blob):
    blob = bytes(blob)
    if blob[:4] == ZSTD_MAGIC:
        if zstandard is None:
            raise RuntimeError("Dane w zstd - zainstaluj: pip install zstandard")
        data = zstandard.ZstdDecompressor().decompress(blob)
    else:
        data = zlib.decompress(blob)
    return json.loads(data.decode("utf-8"))
