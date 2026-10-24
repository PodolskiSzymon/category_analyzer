"""Powiadomienie na telefon (ntfy) po zakończeniu długiej pracy analizatora (recheck).

Temat z `ANALYZER_NTFY_TOPIC`, a gdy pusty - z `SNIPER_NTFY_TOPIC` (sniper/.env); serwer `SNIPER_NTFY_SERVER`
(domyślnie https://ntfy.sh), token `SNIPER_NTFY_TOKEN`. Temat działa jak hasło - tylko w .env, nigdy w repo.
Wysyłka bezpośrednio (NIE przez proxy), błąd tylko w logu.
"""
import logging
import os

import httpx

log = logging.getLogger("analyzer.notify")


def topic():
    return (os.getenv("ANALYZER_NTFY_TOPIC") or os.getenv("SNIPER_NTFY_TOPIC") or "").strip()


def build_message(title, lines, topic_name, priority=3, tags=("white_check_mark",)):
    return {"topic": topic_name, "title": title[:120], "message": "\n".join(lines)[:3000],
            "priority": int(priority), "tags": list(tags)}


async def send(title, lines, priority=3, tags=("white_check_mark",), client=None):
    """True = wysłano; False = brak tematu albo błąd (tylko w logu)."""
    name = topic()
    if not name:
        log.info("[NTFY] Brak ANALYZER_NTFY_TOPIC / SNIPER_NTFY_TOPIC w sniper/.env - bez powiadomienia.")
        return False
    server = (os.getenv("SNIPER_NTFY_SERVER") or "https://ntfy.sh").strip().rstrip("/")
    token = (os.getenv("SNIPER_NTFY_TOKEN") or "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, trust_env=False)
    try:
        r = await client.post(server, json=build_message(title, lines, name, priority, tags), headers=headers)
        r.raise_for_status()
        log.info("[NTFY] Wysłano powiadomienie: %s", title)
        return True
    except Exception as exc:
        log.error("[NTFY] Nie wysłałem powiadomienia: %r", exc)
        return False
    finally:
        if own:
            await client.aclose()
