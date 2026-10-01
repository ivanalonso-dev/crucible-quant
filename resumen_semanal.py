"""
resumen_semanal.py - Prepara el POST SEMANAL para X con los resultados reales de Crucible
y te lo manda por Telegram (solo a ti, el administrador) para que lo copies en X.

Qué publica: SOLO alertas ya CERRADAS (7 días después de emitirse), nunca alertas abiertas,
para no regalar el producto. Incluye aciertos y fallos.

Te llega por Telegram:
  1. Una IMAGEN (1200x675) con los resultados de la semana  -> adjúntala al post
  2. El TEXTO del post (cabe en 280 caracteres)              -> pégalo en X
  3. El texto de la RESPUESTA con el enlace al bot           -> respóndete a ti mismo con él

Se ejecuta los domingos a las 10:30 (Madrid).
Uso:  python resumen_semanal.py                 (normal: semana que termina hoy)
      python resumen_semanal.py --no-enviar     (solo lo muestra y guarda la imagen, no envía)
      python resumen_semanal.py --fecha 2026-10-11   (simula que hoy es esa fecha)
"""
import os
import sys
import json
import datetime as dt
import requests
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import uni_datos as ud

CARPETA = os.path.dirname(os.path.abspath(__file__))
REGISTRO = os.path.join(CARPETA, "registro_alertas.csv")
CONFIG = os.path.join(CARPETA, "config_telegram.json")
IMAGEN = os.path.join(CARPETA, "resumen_semanal.png")
X = 0.08
ENLACE = "t.me/CrucibleQuantBot"
FB = os.path.join(CARPETA, "fuentes", "DejaVuSans-Bold.ttf")     # fuentes incluidas en el proyecto
FR = os.path.join(CARPETA, "fuentes", "DejaVuSans.ttf")


# ------------------------------------------------------------------ fuentes (Windows o Linux)
def fuente(negrita, tam):
    for f in ([FB, "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"] if negrita
              else [FR, "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]):
        if os.path.exists(f):
            return ImageFont.truetype(f, tam)
    return ImageFont.load_default()


# ------------------------------------------------------------------ datos
_PERPS = None


def simbolo_perp(base):
    global _PERPS
    if _PERPS is None:
        info = ud._get(ud.FAPI + "/fapi/v1/exchangeInfo", {})
        _PERPS = {s["symbol"] for s in info["symbols"] if s.get("contractType") == "PERPETUAL"}
    for f in ("", "1000", "1000000"):
        if f"{f}{base}USDT" in _PERPS:
            return f"{f}{base}USDT"
    return None


def velas_alerta(base, t0):
    """Velas 4h del perpetuo desde la vela de la alerta hasta 7 días después."""
    sim = simbolo_perp(base)
    if sim is None:
        return None
    desde = int(t0.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    df = ud.velas(ud.FAPI + "/fapi/v1/klines", sim, "4h", 60, desde)
    return df[df["t"] <= t0 + pd.Timedelta(days=7)]


def medir(alerta):
    """Movimiento máximo arriba/abajo en los 7 días siguientes, relativo al cierre de la vela de alerta."""
    t0 = pd.Timestamp(alerta["t_alerta"])
    df = velas_alerta(alerta["moneda"], t0)
    if df is None or df.empty or df["t"].iloc[0] != t0:
        return None
    ref = df["close"].iloc[0]
    fut = df[df["t"] > t0]
    if fut.empty:
        return None
    arriba = fut["high"].max() / ref - 1
    abajo = fut["low"].min() / ref - 1
    mov = arriba if arriba >= -abajo else abajo        # el mayor de los dos, con su signo
    return {"arriba": arriba, "abajo": abajo, "mov": mov, "acierto": arriba >= X or -abajo >= X}


def semana(hoy):
    reg = pd.read_csv(REGISTRO) if os.path.exists(REGISTRO) else pd.DataFrame()
    if reg.empty:
        return reg, pd.DataFrame()
    reg["t0"] = pd.to_datetime(reg["t_alerta"])
    reg["cierre"] = reg["t0"] + pd.Timedelta(days=7)
    reg["doble"] = reg["doble"].astype(str) == "True"
    sem = reg[(reg["cierre"] > hoy - pd.Timedelta(days=7)) & (reg["cierre"] <= hoy)].copy()
    filas = []
    for _, a in sem.iterrows():
        try:
            m = medir(a)
        except Exception as e:
            print(f"  {a['moneda']}: sin datos ({e})")
            m = None
        if m:
            filas.append({**a.to_dict(), **m})
    return reg, pd.DataFrame(filas)


# ------------------------------------------------------------------ texto del post (≤ 280)
def largo_x(t):
    """X cuenta emojis como 2 caracteres."""
    return sum(2 if ord(c) > 0x2FFF else 1 for c in t)


def pct(x):
    return f"{x * 100:+.0f}%"


def texto_post(res, reg, hoy):
    n, k = len(res), int(res["acierto"].sum())
    d = res[res["doble"]]
    L = [f"📊 Crucible Quant · Week {hoy.isocalendar()[1]} results", "",
         f"{n} alerts closed · {k} moved ±8% within 7 days ({k / n * 100:.0f}%)"]
    if len(d):
        L.append(f"🔴 Double alerts: {int(d['acierto'].sum())}/{len(d)} ({d['acierto'].mean() * 100:.0f}%)")
    mejor = res.loc[res["mov"].abs().idxmax()]
    L += ["", f"Best: {mejor['moneda']} flagged {mejor['t0'].strftime('%b')} {mejor['t0'].day} → {pct(mejor['mov'])}"]
    fallos = res[~res["acierto"]]
    if len(fallos):
        f = fallos.loc[fallos["mov"].abs().idxmin()]
        L.append(f"Miss: {f['moneda']} flagged {f['t0'].strftime('%b')} {f['t0'].day} → max {pct(f['mov'])}")
    cerr = reg[reg["resultado"].isin(["SI", "NO"])]
    total = [f"All-time live: {len(cerr)} alerts · {(cerr['resultado'] == 'SI').mean() * 100:.0f}% hit"] if len(cerr) else []
    pie = ["", "Every alert tracked live. Not financial advice."]
    for extra in (total, []):                     # si no cabe, se quita la línea histórica
        t = "\n".join(L + ([""] + extra if extra else []) + pie)
        if largo_x(t) <= 280:
            return t
    return "\n".join(L + pie)[:280]


TEXTO_RESPUESTA = (f"Get every alert in real time, every day at 10:10 (Madrid time).\n"
                   f"30-day free trial, no payment needed 👉 {ENLACE}")


# ------------------------------------------------------------------ imagen 1200x675
def imagen(res, hoy, ruta):
    W, H = 1200, 675
    CY, MAG, OK, KO = (0, 240, 255), (255, 40, 200), (60, 220, 140), (255, 90, 90)
    img = Image.new("RGB", (W, H), (6, 9, 24))
    g = ImageDraw.Draw(img)
    for x in range(0, W, 40):
        g.line([(x, 0), (x, H)], fill=(18, 26, 52))
    for y in range(0, H, 40):
        g.line([(0, y), (W, y)], fill=(18, 26, 52))
    n, k = len(res), int(res["acierto"].sum())
    d = res[res["doble"]]
    g.text((50, 38), "CRUCIBLE QUANT", font=fuente(True, 40), fill=(245, 250, 255))
    g.text((52, 92), f"Week {hoy.isocalendar()[1]} · live results · alerts closed this week",
           font=fuente(False, 22), fill=(160, 180, 215))
    g.line([(50, 132), (1150, 132)], fill=CY, width=3)
    # cifras grandes
    g.text((50, 160), f"{k / n * 100:.0f}%", font=fuente(True, 110), fill=CY)
    g.text((55, 290), f"{k} of {n} alerts moved ±8% within 7 days", font=fuente(False, 22), fill=(210, 225, 245))
    if len(d):
        g.text((50, 345), f"{d['acierto'].mean() * 100:.0f}%", font=fuente(True, 70), fill=MAG)
        g.text((55, 430), f"double alerts ({int(d['acierto'].sum())}/{len(d)})", font=fuente(False, 22),
               fill=(210, 225, 245))
    g.text((50, 625), "Every alert is checked 7 days after it fires · Not financial advice",
           font=fuente(False, 18), fill=(120, 140, 180))
    g.text((50, 500), "● double alert (2+ signals)   ○ single", font=fuente(False, 18), fill=(150, 165, 200))
    # tabla
    x0, y0, fila = 560, 165, 38
    f1, f2 = fuente(True, 20), fuente(False, 20)
    for i, (txt, xx) in enumerate([("COIN", 0), ("FLAGGED", 130), ("MAX MOVE", 290), ("±8%", 470)]):
        g.text((x0 + xx, y0), txt, font=fuente(True, 16), fill=(120, 140, 180))
    orden = res.assign(o=res["doble"].astype(int) * 10 + res["mov"].abs()).sort_values("o", ascending=False)
    maxf = 10
    for j, (_, r) in enumerate(orden.head(maxf).iterrows()):
        y = y0 + 34 + j * fila
        g.text((x0, y), ("● " if r["doble"] else "○ ") + r["moneda"], font=f1,
               fill=MAG if r["doble"] else (230, 235, 245))
        g.text((x0 + 130, y), f"{r['t0'].strftime('%b')} {r['t0'].day}", font=f2, fill=(200, 210, 230))
        g.text((x0 + 290, y), pct(r["mov"]), font=f1, fill=OK if r["mov"] > 0 else KO)
        g.text((x0 + 470, y), "✓" if r["acierto"] else "✗", font=fuente(True, 22), fill=OK if r["acierto"] else KO)
    if len(orden) > maxf:
        g.text((x0, y0 + 34 + maxf * fila), f"+ {len(orden) - maxf} more", font=f2, fill=(120, 140, 180))
    img.save(ruta)


# ------------------------------------------------------------------ envío por Telegram (solo admin)
def enviar(cfg, foto, texto, respuesta):
    api = f"https://api.telegram.org/bot{cfg['token']}"
    chat = cfg["chat_id"]
    requests.post(f"{api}/sendMessage", timeout=30, data={"chat_id": chat, "text":
                  "📣 POST SEMANAL PARA X\n1) Adjunta la imagen\n2) Pega el texto del post\n"
                  "3) Publica y respóndete a ti mismo con el texto de la respuesta (lleva el enlace)"})
    if foto:
        with open(foto, "rb") as fh:
            requests.post(f"{api}/sendPhoto", data={"chat_id": chat}, files={"photo": fh}, timeout=60)
    requests.post(f"{api}/sendMessage", data={"chat_id": chat, "text": texto}, timeout=30)
    requests.post(f"{api}/sendMessage", data={"chat_id": chat, "text": respuesta}, timeout=30)


def main():
    args = sys.argv[1:]
    hoy = pd.Timestamp(args[args.index("--fecha") + 1]) + pd.Timedelta(hours=8) if "--fecha" in args \
        else pd.Timestamp(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    reg, res = semana(hoy)
    if res.empty:
        texto, foto = (f"📣 Semana {hoy.isocalendar()[1]}: no se ha cerrado ninguna alerta esta semana, "
                       f"así que hoy no hay post de resultados para X."), None
        respuesta = "Publica un post a mano (cómo funciona una señal, lecciones de construir Crucible…)."
    else:
        texto = texto_post(res, reg, hoy)
        imagen(res, hoy, IMAGEN)
        foto, respuesta = IMAGEN, TEXTO_RESPUESTA
        print(f"Imagen: {IMAGEN}")
    print("\n" + texto + f"\n\n[{largo_x(texto)}/280]\n\nRespuesta:\n{respuesta}\n")
    if "--no-enviar" not in args and os.path.exists(CONFIG):
        enviar(json.load(open(CONFIG, encoding="utf-8")), foto, texto, respuesta)
        print("Enviado por Telegram.")


if __name__ == "__main__":
    main()
