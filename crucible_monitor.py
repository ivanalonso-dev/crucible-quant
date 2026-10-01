"""
crucible_monitor.py - MONITOR DIARIO de Crucible Quant. Se ejecuta cada día a las 10:10 (Barcelona).

Hace, en este orden:
  1. Descarga datos FRESCOS (último año, velas 4h de futuros + spot + funding) del top 30.
  2. ALERTAS DE VOLATILIDAD: qué monedas tienen probabilidad alta de moverse ±8 % en 7 días
     (señales validadas: escenario, volatilidad disparada, funding extremo, volumen explosivo;
      "doble" = dos o más a la vez, la más fiable).
  3. REGISTRO EN VIVO: guarda cada alerta en registro_alertas.csv y comprueba a los 7 días si
     se cumplió -> porcentaje de acierto real, no de backtest.
  4. Envía el resumen por TELEGRAM (si existe config_telegram.json) y lo muestra por pantalla.

No dice la dirección del movimiento: no es predecible con estos datos (probado).
Uso:  python crucible_monitor.py          (configurar Telegram antes: python configurar_telegram.py)
"""

import os
import json
import time
import datetime as dt
import requests
import numpy as np
import pandas as pd
import uni_datos as ud
import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)

CARPETA = os.path.dirname(os.path.abspath(__file__))
REGISTRO = os.path.join(CARPETA, "registro_alertas.csv")
CONFIG_TG = os.path.join(CARPETA, "config_telegram.json")
DIAS = 400                 # historia necesaria para las señales (1 año de percentiles + margen)
X = 0.08

# ventaja validada (puntos de probabilidad sobre la base de la moneda) - senales_volatilidad.py
VENTAJA = PRM.VENTAJA
NOMBRE = {"escenario": "rally + pullback", "volatilidad": "volatility spike",
          "funding": "extreme funding", "volumen": "volume surge"}


# ------------------------------------------------------------------ hora de Madrid (sin librerías extra)
def ultimo_domingo(anio, mes):
    d = dt.datetime(anio, mes + 1, 1) - dt.timedelta(days=1) if mes < 12 else dt.datetime(anio, 12, 31)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def hora_madrid(t_utc):
    """Convierte UTC a hora de Madrid con la regla europea de horario de verano."""
    ini = ultimo_domingo(t_utc.year, 3).replace(hour=1)
    fin = ultimo_domingo(t_utc.year, 10).replace(hour=1)
    verano = ini <= t_utc < fin
    return t_utc + dt.timedelta(hours=2 if verano else 1), ("CEST" if verano else "CET")


def fmt(x):
    return f"{x:,.2f}" if x >= 100 else f"{x:.6g}"


# ------------------------------------------------------------------ datos y señales
def datos_moneda(m):
    desde = int((time.time() - DIAS * 86400) * 1000)
    spot, perp, fund = ud.descargar_todo(m["spot"], perp_simbolo=m["perp"], factor=m["factor"],
                                         desde_ms=desde, silencioso=True)
    df, _ = ud.construir(spot, perp, fund)
    return df


def senales(df):
    lr = np.log(df["close"]).diff()
    ratio = lr.rolling(42).std() / lr.rolling(540).std()
    fpct = df["funding_3d"].abs().rolling(2190, min_periods=540).rank(pct=True)
    return {"escenario": df["escenario"].astype(bool), "volatilidad": ratio > PRM.VOL_RATIO,
            "funding": fpct >= PRM.FUND_PCT, "volumen": df["vol_rel"] > PRM.VOLUMEN_REL}


def analizar(base, df):
    S = senales(df)
    i = df.index[-1]
    activas = [k for k, s in S.items() if bool(s.fillna(False).loc[i])]
    conocido = df["primero_8"].dropna()
    base_prob = conocido.isin(["arriba", "abajo", "ambos"]).mean() if len(conocido) else np.nan
    vent = [VENTAJA[k] for k in activas]
    vent += [v for k, v in VENTAJA.items() if isinstance(k, tuple) and all(x in activas for x in k)]
    ventaja = max(vent) if vent else 0.0
    return {"moneda": base, "t": df["t"].iloc[-1], "precio": float(df["close"].iloc[-1]),
            "activas": activas, "doble": len(activas) >= 2, "base": base_prob,
            "prob": min(base_prob + ventaja, 0.99) if activas and base_prob == base_prob else np.nan,
            }


# ------------------------------------------------------------------ registro en vivo
def actualizar_registro(resultados, datos):
    cols = ["t_alerta", "moneda", "precio", "senales", "doble", "prob", "base", "resultado"]
    reg = pd.read_csv(REGISTRO) if os.path.exists(REGISTRO) else pd.DataFrame(columns=cols)
    for r in resultados:
        if r["activas"]:
            fila = {"t_alerta": r["t"].strftime("%Y-%m-%d %H:%M"), "moneda": r["moneda"], "precio": r["precio"],
                    "senales": "+".join(r["activas"]), "doble": r["doble"], "prob": round(r["prob"], 3),
                    "base": round(r["base"], 3), "resultado": ""}
            # como mucho una alerta por moneda cada 7 días (igual que en el backtest)
            prev = reg[reg["moneda"] == r["moneda"]]
            if len(prev) and (pd.Timestamp(fila["t_alerta"]) - pd.to_datetime(prev["t_alerta"]).max()).days < 7:
                continue
            reg = pd.concat([reg, pd.DataFrame([fila])], ignore_index=True)
    reg["resultado"] = reg["resultado"].fillna("").astype(str)
    for idx, r in reg[reg["resultado"].isin(["", "nan"])].iterrows():
        df = datos.get(r["moneda"])
        if df is None:
            continue
        t0 = pd.Timestamp(r["t_alerta"])
        fut = df[(df["t"] > t0) & (df["t"] <= t0 + pd.Timedelta(days=7))]
        toca = ((fut["high"] >= r["precio"] * (1 + X)) | (fut["low"] <= r["precio"] * (1 - X))).any()
        if toca:
            reg.loc[idx, "resultado"] = "SI"
        elif df["t"].iloc[-1] >= t0 + pd.Timedelta(days=7):
            reg.loc[idx, "resultado"] = "NO"
    reg.to_csv(REGISTRO, index=False)
    cerradas = reg[reg["resultado"].isin(["SI", "NO"])]
    return reg, cerradas


# ------------------------------------------------------------------ mensaje
def mensaje(resultados, reg, cerradas):
    t = max(r["t"] for r in resultados) + pd.Timedelta(hours=4)          # cierre de la última vela
    local, zona = hora_madrid(t.to_pydatetime())
    ahora, _ = hora_madrid(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    alertas = sorted([r for r in resultados if r["activas"]], key=lambda r: -((r["prob"] - r["base"]) + r["doble"]))
    dobles = [r for r in alertas if r["doble"]]
    cab = "🚨" if dobles else ("⚠️" if alertas else "🟢")
    L = [f"{cab} CRUCIBLE · {ahora:%d/%m/%Y %H:%M}",
         f"Candle closed at {local:%H:%M} {zona} ({t:%H:%M} UTC)", ""]
    if alertas:
        L.append("LIKELY ±8% MOVE WITHIN 7 DAYS (direction unknown):")
        for r in alertas:
            icono = "🔴" if r["doble"] else "🟠"
            L.append(f"{icono} {r['moneda']} {fmt(r['precio'])} · {r['prob']*100:.0f}% (usual {r['base']*100:.0f}%)")
            L.append(f"    {', '.join(NOMBRE[a] for a in r['activas'])}")
    else:
        L.append("No move alerts today.")
    sin = [r["moneda"] for r in resultados if not r["activas"]]
    if sin:
        L.append(f"\nNo alert: {', '.join(sin)}")

    if len(cerradas):
        ac = (cerradas["resultado"] == "SI").mean()
        d = cerradas[cerradas["doble"].astype(str) == "True"]
        extra = f" · doubles {(d['resultado'] == 'SI').mean()*100:.0f}% of {len(d)}" if len(d) else ""
        L.append(f"\n📊 Live: {len(cerradas)} alerts closed, {ac*100:.0f}% moved ±8%{extra}")
        L.append(f"   (expected from backtest: {cerradas['prob'].astype(float).mean()*100:.0f}%)")
    else:
        L.append(f"\n📊 Live: {len(reg)} alerts logged, none closed yet (they take 7 days)")
    return "\n".join(L)


def enviar_telegram(texto):
    if not os.path.exists(CONFIG_TG):
        print("(Telegram no configurado: ejecuta configurar_telegram.py)")
        return
    with open(CONFIG_TG, encoding="utf-8") as f:
        cfg = json.load(f)
    # Telegram admite 4.096 caracteres por mensaje: si hace falta, se parte por líneas
    partes, actual = [], ""
    for linea in texto.split("\n"):
        if len(actual) + len(linea) + 1 > 4000:
            partes.append(actual)
            actual = ""
        actual += linea + "\n"
    partes.append(actual)
    for p in partes:
        r = requests.post(f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
                          data={"chat_id": cfg["chat_id"], "text": p}, timeout=30)
        print("Telegram:", "enviado" if r.ok else f"error {r.status_code} {r.text[:200]}")


def main():
    monedas = ud.top_monedas(30)
    resultados, datos = [], {}
    for m in monedas:
        try:
            df = datos_moneda(m)
            if len(df) < 600:
                continue
            datos[m["base"]] = df
            resultados.append(analizar(m["base"], df))
            print(f"  {m['base']} ok")
        except Exception as e:
            print(f"  {m['base']} omitida: {e}")
    if not resultados:
        texto = "⚠️ CRUCIBLE: could not download market data today."
    else:
        reg, cerradas = actualizar_registro(resultados, datos)
        texto = mensaje(resultados, reg, cerradas)
    print("\n" + texto + "\n")
    try:                                   # a todos los usuarios con prueba o suscripción activa
        import crucible_bot as cb
        cb.difundir(texto)
        cb.recordatorios()
    except Exception as e:                 # si falla, al menos te llega a ti
        print(f"(difusión fallida: {e}; se envía solo al administrador)")
        enviar_telegram(texto)


if __name__ == "__main__":
    main()
