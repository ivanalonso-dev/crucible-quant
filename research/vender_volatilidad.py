"""
vender_volatilidad.py - ¿Se gana VENDIENDO volatilidad cuando NO hay alerta?

Idea: comprar opciones pierde de media (el mercado cobra una "prima de volatilidad"), así que
venderlas gana de media... salvo cuando llega un movimiento grande. La alerta de volatilidad
sirve para APARTARSE justo en esos momentos.

Estrategias (fijadas de antemano), a 7 días, en el dinero, una operación cada vez (sin solapar):
  1. STRADDLE VENDIDO, al vencimiento          riesgo ILIMITADO
  2. STRADDLE VENDIDO con stop                 se recompra si su valor llega al doble de lo cobrado
  3. MARIPOSA DE HIERRO (iron butterfly)       se vende el straddle y se compran protecciones
                                               a +15 % y -15 %: la pérdida máxima queda LIMITADA
Filtros: "solo SIN alerta" (la idea), "siempre" (referencia) y "solo CON alerta" (control).

Precios con Black-Scholes y el DVOL de Deribit (cache/dvol_BTC.csv y dvol_ETH.csv, que crea
straddle_dvol.py). Costes: 3 % de la prima al abrir y 3 % al cerrar.
Resultados en % del precio del activo (lo que ganas o pierdes por cada 1 BTC/ETH de nominal).

LIMITACIONES: aproximación (DVOL a 30 días usado para 7 días, sin "skew": las protecciones
reales suelen costar más de lo que aquí se calcula). Las pérdidas en los peores casos son lo
más importante de mirar.

Uso: python vender_volatilidad.py   (tras haber ejecutado straddle_dvol.py al menos una vez)
"""

import os
import io
import math
import contextlib
import numpy as np
import pandas as pd
import straddle_dvol as sd

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
H, T = sd.H, sd.T_ANIOS
ALA = 0.15
rng = np.random.default_rng(33)


def bs(S, K, s, t, tipo):
    if t <= 0 or s <= 0:
        return max(S - K, 0) if tipo == "c" else max(K - S, 0)
    d1 = (math.log(S / K) + 0.5 * s * s * t) / (s * math.sqrt(t))
    d2 = d1 - s * math.sqrt(t)
    return S * sd.N(d1) - K * sd.N(d2) if tipo == "c" else K * sd.N(-d2) - S * sd.N(-d1)


def valor(estr, S, K, s, t):
    st = bs(S, K, s, t, "c") + bs(S, K, s, t, "p")
    if estr == "mariposa":
        st -= bs(S, K * (1 + ALA), s, t, "c") + bs(S, K * (1 - ALA), s, t, "p")
    return st


def operar(df, dvol, i, estr):
    S0 = K = df["close"].iloc[i]
    iv0 = dvol.get(df["t_cierre"].iloc[i])
    if iv0 is None or not iv0 == iv0:
        return None
    base = "mariposa" if estr == "mariposa" else "straddle"
    cobrado = valor(base, S0, K, iv0 / 100, T)
    neto = cobrado * (1 - sd.COSTE)
    for k in range(1, H + 1):
        j = i + k
        if j >= len(df):
            return None
        S = df["close"].iloc[j]
        iv = dvol.get(df["t_cierre"].iloc[j], iv0)
        iv = iv if iv == iv else iv0
        v = valor(base, S, K, iv / 100, T * (H - k) / H)
        if estr == "stop" and k < H:
            # peor punto de la vela (máximo o mínimo) para ser prudentes con el stop
            vmax = max(valor(base, df["high"].iloc[j], K, iv / 100, T * (H - k) / H),
                       valor(base, df["low"].iloc[j], K, iv / 100, T * (H - k) / H))
            if vmax >= 2 * cobrado:
                return (neto - vmax * (1 + sd.COSTE)) / S0
    return (neto - v * (1 + sd.COSTE if v > 0 else 1)) / S0


def casos(df, dvol, filtro, estr):
    out, a = [], df["alerta"].fillna(False).values
    hora4 = (df["t"].dt.hour == 4).values
    i = 540
    while i < len(df) - H - 1:
        ok = hora4[i] and df["t"].iloc[i] >= sd.INICIO and (
            filtro == "siempre" or (filtro == "sin alerta" and not a[i]) or (filtro == "con alerta" and a[i]))
        if ok:
            r = operar(df, dvol, i, estr)
            if r is not None:
                out.append({"t": df["t"].iloc[i], "r": r})
                i += H
                continue
        i += 1
    return pd.DataFrame(out)


def fila(n, E):
    if len(E) == 0:
        return f"{n:<44} sin casos"
    r = E["r"].values
    b = rng.choice(r, size=(3000, len(r)), replace=True).mean(axis=1)
    tr, te = E[E["t"] < sd.CORTE]["r"], E[E["t"] >= sd.CORTE]["r"]
    peor5 = np.sort(r)[:max(1, len(r) // 20)].mean()
    anual = r.mean() * 52
    return (f"{n:<44}{len(r):>5}{(r > 0).mean()*100:>7.0f}%{r.mean()*100:>+8.2f}%"
            f"  [{np.percentile(b, 2.5)*100:+5.2f}, {np.percentile(b, 97.5)*100:+5.2f}]"
            f"{tr.mean()*100:>+8.2f}%{te.mean()*100:>+8.2f}%{r.min()*100:>+9.1f}%{peor5*100:>+8.1f}%{anual*100:>+8.0f}%")


def main():
    cab = (f"{'estrategia | filtro':<44}{'ops':>5}{'ganad.':>8}{'medio':>9}{'IC 95 %':>17}"
           f"{'21-24':>9}{'25-hoy':>9}{'peor':>9}{'peor 5%':>9}{'x52':>8}")
    print("Resultados por operación en % del precio del activo (por 1 BTC/ETH de nominal).")
    print("'peor 5%' = media del 5 % de operaciones más malas. 'x52' = medio x 52 semanas (orientativo).\n")
    for moneda in ["BTC", "ETH"]:
        dv = pd.read_csv(os.path.join(sd.CACHE, f"dvol_{moneda}.csv"), parse_dates=["t"])
        dvol = dict(zip(dv["t"].astype("datetime64[ns]"), dv["dvol"]))
        df = sd.cargar_precios(moneda)
        print(f"==================== {moneda} ====================")
        print(cab)
        for estr, nombre in [("straddle", "1. Straddle vendido"), ("stop", "2. Straddle vendido + stop"),
                             ("mariposa", "3. Mariposa de hierro")]:
            for filtro in ["sin alerta", "siempre", "con alerta"]:
                print(fila(f"{nombre} | {filtro}", casos(df, dvol, filtro, estr)))
        print()


if __name__ == "__main__":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    print(buf.getvalue())
    with open(os.path.join(CARPETA, "vender_volatilidad_resultados.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Ejecutado: {pd.Timestamp.now():%Y-%m-%d %H:%M}\n\n" + buf.getvalue())
