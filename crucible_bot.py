"""
crucible_bot.py - Bot de SUSCRIPCIONES de Crucible Quant (Telegram + Telegram Stars).

Qué hace (tiene que estar SIEMPRE encendido, idealmente en un servidor):
  - /start           registra al usuario y activa su PRUEBA GRATIS de 30 días
  - /pricing, /subscribe   enlace de pago: suscripción mensual en Telegram Stars que se RENUEVA SOLA
  - /status          estado de su acceso + último resumen de alertas
  - /readme /disclaimer /privacy /help   textos informativos (en telegram/textos_telegram.py)
  - /cancel          cancela la renovación automática (mantiene el acceso hasta fin de periodo)
  - /stats           (solo administrador) usuarios, pruebas y suscripciones activas
  - Procesa los pagos: responde a pre_checkout y registra cada pago y cada renovación.

Además, crucible_monitor.py usa difundir() y recordatorios() de este archivo para:
  - enviar el resumen diario a TODOS los usuarios con acceso (prueba o suscripción activa)
  - avisar 3 días antes de que acabe la prueba y el día que acaba, con el botón de suscripción

Configuración: config_telegram.json  ->  {"token": "...", "chat_id": <tu id, administrador>,
                                          "precio_stars": 2300}
Datos: suscriptores.db (SQLite). NO subir a GitHub (está en .gitignore).
Uso:  python crucible_bot.py      (se queda escuchando; Ctrl+C para parar)
"""

import os
import sys
import json
import time
import sqlite3
import datetime as dt
import requests

CARPETA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(CARPETA, "telegram"))
import textos_telegram as TX  # noqa: E402

with open(os.path.join(CARPETA, "config_telegram.json"), encoding="utf-8") as _f:
    CFG = json.load(_f)
TOKEN = CFG["token"]
ADMIN = int(CFG["chat_id"])
PRECIO = int(CFG.get("precio_stars", 2300))       # precio mensual en Stars (ver PRICING)
API = f"https://api.telegram.org/bot{TOKEN}"
DB = os.path.join(CARPETA, "suscriptores.db")
RESUMEN = os.path.join(CARPETA, "ultimo_resumen.txt")
PRUEBA_DIAS = 30
PERIODO = 2592000                                  # 30 días: único periodo que admite Telegram
GRACIA = dt.timedelta(days=1)                      # margen por si la renovación llega con retraso


# ------------------------------------------------------------------ utilidades
def ahora():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def fecha(s):
    return dt.datetime.fromisoformat(s) if s else None


def api(metodo, **params):
    try:
        r = requests.post(f"{API}/{metodo}", json=params, timeout=60)
        return r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


def log(*a):
    print(f"[{ahora():%Y-%m-%d %H:%M:%S}]", *a, flush=True)


def con():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        user_id INTEGER PRIMARY KEY, chat_id INTEGER, nombre TEXT, alta TEXT,
        fin_prueba TEXT, fin_suscripcion TEXT, charge_id TEXT,
        estado TEXT DEFAULT 'activo', aviso_prueba INTEGER DEFAULT 0)""")
    return c


def usuario(uid):
    with con() as c:
        return c.execute("SELECT * FROM usuarios WHERE user_id=?", (uid,)).fetchone()


def tiene_acceso(u):
    if u is None:
        return False
    if u["user_id"] == ADMIN:
        return True
    t = ahora()
    if u["fin_prueba"] and t < fecha(u["fin_prueba"]):
        return True
    return bool(u["fin_suscripcion"]) and t < fecha(u["fin_suscripcion"]) + GRACIA


def enviar(chat_id, texto, boton=None):
    """Envía partiendo en trozos de <4000 caracteres. Devuelve False si el usuario bloqueó el bot."""
    trozos, actual = [], ""
    for linea in texto.split("\n"):
        if len(actual) + len(linea) + 1 > 4000:
            trozos.append(actual)
            actual = ""
        actual += linea + "\n"
    trozos.append(actual)
    for i, t in enumerate(trozos):
        p = {"chat_id": chat_id, "text": t, "disable_web_page_preview": True}
        if boton and i == len(trozos) - 1:
            p["reply_markup"] = {"inline_keyboard": [[boton]]}
        r = api("sendMessage", **p)
        if not r.get("ok"):
            if r.get("error_code") == 403:
                return False
            log("error enviando a", chat_id, r.get("description"))
    return True


def boton_suscripcion():
    r = api("createInvoiceLink", title="Crucible Quant — monthly",
            description="Daily volatility alerts for the top 30 cryptos. Renews every 30 days; cancel anytime.",
            payload="crucible_monthly", currency="XTR",
            prices=[{"label": "Monthly subscription", "amount": PRECIO}],
            subscription_period=PERIODO)
    if not r.get("ok"):
        log("createInvoiceLink falló:", r.get("description"))
        return None
    return {"text": f"⭐ Subscribe — {PRECIO} Stars / month", "url": r["result"]}


def texto_estado(u):
    t = ahora()
    if u is None:
        return "You are not registered yet. Send /start to begin your 30-day free trial."
    if u["user_id"] == ADMIN:
        return "👑 Admin account: unlimited access."
    if u["fin_suscripcion"] and t < fecha(u["fin_suscripcion"]) + GRACIA:
        return f"✅ Active subscription. Current period ends {fecha(u['fin_suscripcion']):%Y-%m-%d} (renews automatically unless cancelled)."
    if u["fin_prueba"] and t < fecha(u["fin_prueba"]):
        dias = (fecha(u["fin_prueba"]) - t).days + 1
        return f"🎁 Free trial active: {dias} day(s) left (ends {fecha(u['fin_prueba']):%Y-%m-%d})."
    return "⛔ Your free trial has ended. Subscribe with /subscribe to keep receiving the daily alerts."


# ------------------------------------------------------------------ comandos
def cmd_start(msg):
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    nombre = msg["from"].get("username") or msg["from"].get("first_name", "")
    u = usuario(uid)
    if u is None:
        fin = ahora() + dt.timedelta(days=PRUEBA_DIAS)
        with con() as c:
            c.execute("INSERT INTO usuarios (user_id, chat_id, nombre, alta, fin_prueba) VALUES (?,?,?,?,?)",
                      (uid, chat, nombre, ahora().isoformat(), fin.isoformat()))
        log("nuevo usuario", uid, nombre)
        enviar(chat, f"👋 Welcome to Crucible Quant!\n\n🎁 Your 30-day free trial is active until {fin:%Y-%m-%d}.\n"
                     f"You will receive one volatility summary every day at 10:10 (Madrid time).\n\n"
                     f"Commands: /readme /status /pricing /disclaimer /privacy /help")
        enviar(chat, TX.README)
    else:
        with con() as c:
            c.execute("UPDATE usuarios SET estado='activo', chat_id=? WHERE user_id=?", (chat, uid))
        enviar(chat, "👋 Welcome back!\n\n" + texto_estado(usuario(uid)))


def cmd_pricing(msg):
    b = boton_suscripcion()
    extra = "" if b else "\n\n(Subscriptions are temporarily unavailable. Please try again later.)"
    enviar(msg["chat"]["id"], TX.PRICING + extra, b)


def cmd_status(msg):
    u = usuario(msg["from"]["id"])
    t = texto_estado(u)
    if tiene_acceso(u) and os.path.exists(RESUMEN):
        t += "\n\n— Latest summary —\n\n" + open(RESUMEN, encoding="utf-8").read()
    enviar(msg["chat"]["id"], t)


def cmd_cancel(msg):
    u = usuario(msg["from"]["id"])
    if not u or not u["charge_id"]:
        return enviar(msg["chat"]["id"], "You have no active subscription to cancel.")
    r = api("editUserStarSubscription", user_id=u["user_id"],
            telegram_payment_charge_id=u["charge_id"], is_canceled=True)
    if r.get("ok"):
        enviar(msg["chat"]["id"], f"Your subscription will not renew. You keep access until "
                                  f"{fecha(u['fin_suscripcion']):%Y-%m-%d}. You can resubscribe anytime with /subscribe.")
    else:
        enviar(msg["chat"]["id"], "Could not cancel automatically. You can also cancel it from Telegram: "
                                  "Settings → My Stars → Subscriptions.")
        log("cancel falló", u["user_id"], r.get("description"))


def cmd_stats(msg):
    if msg["from"]["id"] != ADMIN:
        return
    with con() as c:
        filas = c.execute("SELECT * FROM usuarios").fetchall()
    t = ahora()
    subs = sum(1 for u in filas if u["fin_suscripcion"] and t < fecha(u["fin_suscripcion"]) + GRACIA)
    prueba = sum(1 for u in filas if u["fin_prueba"] and t < fecha(u["fin_prueba"])
                 and not (u["fin_suscripcion"] and t < fecha(u["fin_suscripcion"])))
    bloq = sum(1 for u in filas if u["estado"] == "bloqueado")
    enviar(msg["chat"]["id"], f"📊 Users: {len(filas)}\n🎁 In trial: {prueba}\n⭐ Paying: {subs}\n"
                              f"🚫 Blocked the bot: {bloq}\n💰 Est. monthly: {subs * PRECIO} Stars")


COMANDOS = {
    "/start": cmd_start,
    "/readme": lambda m: enviar(m["chat"]["id"], TX.README),
    "/disclaimer": lambda m: enviar(m["chat"]["id"], TX.DISCLAIMER),
    "/privacy": lambda m: enviar(m["chat"]["id"], TX.PRIVACY),
    "/pricing": cmd_pricing,
    "/subscribe": cmd_pricing,
    "/status": cmd_status,
    "/cancel": cmd_cancel,
    "/stats": cmd_stats,
    "/help": lambda m: enviar(m["chat"]["id"], "Commands:\n/status – your access and the latest summary\n"
                              "/readme – how it works\n/pricing – trial and subscription\n/subscribe – subscribe\n"
                              "/cancel – stop auto-renewal\n/disclaimer – not financial advice\n/privacy – privacy policy"),
}


# ------------------------------------------------------------------ pagos
def pago_ok(msg):
    sp = msg["successful_payment"]
    uid = msg["from"]["id"]
    exp = sp.get("subscription_expiration_date")
    fin = dt.datetime.fromtimestamp(exp, dt.timezone.utc).replace(tzinfo=None) if exp else ahora() + dt.timedelta(days=30)
    if usuario(uid) is None:
        cmd_start(msg)
    with con() as c:
        c.execute("UPDATE usuarios SET fin_suscripcion=?, charge_id=?, estado='activo' WHERE user_id=?",
                  (fin.isoformat(), sp.get("telegram_payment_charge_id"), uid))
    log("pago", uid, sp.get("total_amount"), sp.get("currency"), "recurrente" if sp.get("is_recurring") else "", "hasta", fin)
    if not sp.get("is_recurring") or sp.get("is_first_recurring"):
        enviar(msg["chat"]["id"], f"✅ Thank you! Your subscription is active until {fin:%Y-%m-%d} and renews "
                                  f"automatically every 30 days. Cancel anytime with /cancel.")


# ------------------------------------------------------------------ usado por crucible_monitor.py
def difundir(texto):
    """Envía el resumen diario a todos los usuarios con acceso. Devuelve nº de envíos."""
    with open(RESUMEN, "w", encoding="utf-8") as f:
        f.write(texto)
    with con() as c:
        filas = c.execute("SELECT * FROM usuarios WHERE estado='activo'").fetchall()
    destinos = {u["chat_id"]: u for u in filas if tiene_acceso(u)}
    destinos.setdefault(ADMIN, None)
    n = 0
    for chat, u in destinos.items():
        if enviar(chat, texto):
            n += 1
        elif u is not None:
            with con() as c:
                c.execute("UPDATE usuarios SET estado='bloqueado' WHERE user_id=?", (u["user_id"],))
        time.sleep(0.05)                                   # respetar límites de Telegram
    log(f"resumen enviado a {n} usuario(s)")
    return n


def recordatorios():
    """Avisos de fin de prueba: 3 días antes (aviso 1) y al terminar (aviso 2)."""
    t = ahora()
    with con() as c:
        filas = c.execute("SELECT * FROM usuarios WHERE estado='activo'").fetchall()
    for u in filas:
        if u["user_id"] == ADMIN or (u["fin_suscripcion"] and t < fecha(u["fin_suscripcion"]) + GRACIA):
            continue
        fin = fecha(u["fin_prueba"])
        if fin is None:
            continue
        nivel = None
        if u["aviso_prueba"] < 1 and dt.timedelta(0) < fin - t <= dt.timedelta(days=3):
            nivel, txt = 1, f"⏳ Your free trial ends on {fin:%Y-%m-%d}. Subscribe to keep receiving the daily alerts."
        elif u["aviso_prueba"] < 2 and t >= fin:
            nivel, txt = 2, "⛔ Your free trial has ended. Subscribe to continue receiving Crucible Quant alerts."
        if nivel:
            enviar(u["chat_id"], txt, boton_suscripcion())
            with con() as c:
                c.execute("UPDATE usuarios SET aviso_prueba=? WHERE user_id=?", (nivel, u["user_id"]))


# ------------------------------------------------------------------ bucle principal
def procesar(upd):
    if "pre_checkout_query" in upd:
        q = upd["pre_checkout_query"]
        api("answerPreCheckoutQuery", pre_checkout_query_id=q["id"], ok=True)
        return
    msg = upd.get("message")
    if not msg or msg.get("chat", {}).get("type") != "private":
        return
    if "successful_payment" in msg:
        return pago_ok(msg)
    texto = (msg.get("text") or "").strip()
    cmd = texto.split()[0].split("@")[0].lower() if texto.startswith("/") else None
    if cmd in COMANDOS:
        COMANDOS[cmd](msg)
    else:
        enviar(msg["chat"]["id"], "I only understand commands. Try /help.")


def main():
    con().close()
    api("deleteWebhook")
    log(f"Crucible bot en marcha (precio {PRECIO} Stars/mes). Ctrl+C para parar.")
    offset = None
    while True:
        r = api("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "pre_checkout_query"])
        if not r.get("ok"):
            log("getUpdates:", r.get("description"))
            time.sleep(5)
            continue
        for upd in r["result"]:
            offset = upd["update_id"] + 1
            try:
                procesar(upd)
            except Exception as e:
                log("error procesando update:", e)


if __name__ == "__main__":
    main()
