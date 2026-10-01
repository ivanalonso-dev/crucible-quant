"""
publicar_info.py - Envía al chat del bot las 4 secciones (README, DISCLAIMER, PRIVACY, PRICING)
y FIJA el README arriba del chat.

Antes: rellena [CONTACT EMAIL], [YOUR NAME / COMPANY] y [PAYMENT INSTRUCTIONS / LINK]
en textos_telegram.py. El script se niega a publicar si quedan esos huecos.

Uso (desde la carpeta 004.CRUCIBLE QUANT o desde telegram/):  python telegram/publicar_info.py
"""
import os
import sys
import json
import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import textos_telegram as tx

CONFIG = os.path.join(os.path.dirname(AQUI), "config_telegram.json")
if not os.path.exists(CONFIG):
    raise SystemExit("No existe config_telegram.json: ejecuta antes configurar_telegram.py")
cfg = json.load(open(CONFIG, encoding="utf-8"))
API = f"https://api.telegram.org/bot{cfg['token']}"

huecos = [n for n, t in tx.SECCIONES if "[" in t and "]" in t and ("EMAIL" in t or "PAYMENT" in t or "COMPANY" in t)]
if huecos:
    raise SystemExit(f"Rellena antes los huecos entre corchetes en textos_telegram.py (secciones: {', '.join(huecos)})")

ids = {}
for nombre, texto in tx.SECCIONES:
    r = requests.post(f"{API}/sendMessage", data={"chat_id": cfg["chat_id"], "text": texto}, timeout=30).json()
    if not r.get("ok"):
        raise SystemExit(f"Error enviando {nombre}: {r}")
    ids[nombre] = r["result"]["message_id"]
    print(f"{nombre}: enviado")

r = requests.post(f"{API}/pinChatMessage", data={"chat_id": cfg["chat_id"], "message_id": ids["README"],
                                                 "disable_notification": True}, timeout=30).json()
print("README fijado arriba del chat" if r.get("ok") else f"No se pudo fijar: {r}")
