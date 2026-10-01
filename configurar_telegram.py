"""
configurar_telegram.py - Configura el envío de las alertas de Crucible a tu Telegram (una sola vez).

Antes:
  1. En Telegram, habla con @BotFather, escribe /newbot y sigue los pasos. Te dará un TOKEN.
  2. Busca tu bot nuevo en Telegram y envíale cualquier mensaje (por ejemplo "hola").
Después:
  python configurar_telegram.py   -> pega el token cuando lo pida.

Guarda config_telegram.json (token y chat). NO subas ese archivo a GitHub (.gitignore ya lo excluye).
"""
import os
import json
import requests

CARPETA = os.path.dirname(os.path.abspath(__file__))
token = input("Pega el token de @BotFather: ").strip()
r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
if not r.get("ok"):
    raise SystemExit(f"Token no válido: {r}")
chats = [u["message"]["chat"]["id"] for u in r["result"] if "message" in u]
if not chats:
    raise SystemExit("No encuentro mensajes: envía 'hola' a tu bot en Telegram y vuelve a ejecutar esto.")
cfg = {"token": token, "chat_id": chats[-1]}
with open(os.path.join(CARPETA, "config_telegram.json"), "w", encoding="utf-8") as f:
    json.dump(cfg, f)
ok = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   data={"chat_id": cfg["chat_id"], "text": "✅ Crucible connected. You will receive the daily summary at 10:10."},
                   timeout=30).ok
print("Configurado y mensaje de prueba enviado." if ok else "Configurado, pero falló el mensaje de prueba.")
