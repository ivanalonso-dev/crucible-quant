"""
straddle_dvol.py - ¿Habría ganado un STRADDLE comprado en cada alerta de volatilidad?

Solo BTC y ETH (son las que tienen índice de volatilidad implícita DVOL en Deribit, desde 2021).

Pasos:
  1. Descarga el histórico del índice DVOL de Deribit (API pública, sin cuenta) -> cache/dvol_BTC.csv, dvol_ETH.csv
  2. Usa los precios de tu carpeta cache/ y las mismas alertas de senales_volatilidad.py.
  3. En cada alerta (10:10 Barcelona) "compra" un straddle a 7 días en el dinero, valorado con
     Black-Scholes usando el DVOL de ese momento como volatilidad implícita.
  4. Tres formas de salir (fijadas de antemano):
       - VENCIMIENTO:  se mantiene los 7 días
       - TOCA ±8 %:    se vende en cuanto el precio toca +8 % o -8 % (lo que predice la alerta),
                       o al vencimiento si no lo toca
       - TP/SL 50 %:   se vende si el straddle gana un 50 % o pierde un 50 %, o al vencimiento
     Revalorización cada 4 horas con el DVOL de ese momento y el tiempo que queda.
  5. Costes: 3 % de la prima al comprar y 3 % del valor al vender (comisión + horquilla, estimado).
  6. REFERENCIA: comprar el mismo straddle TODOS los días a la misma hora, sin alerta.
     (Comprar opciones sin ventaja suele perder: el mercado cobra una "prima de volatilidad").

Veredicto: la alerta aporta valor si los straddles con alerta ganan dinero Y claramente más que sin alerta,
tanto en 2021-2024 como en 2025-hoy.

LIMITACIONES (importante): es una APROXIMACIÓN. El DVOL mide la volatilidad implícita a 30 días y aquí se
usa para opciones a 7 días; los precios reales de las opciones pueden diferir. Si sale prometedor, el
siguiente paso sería validarlo con precios reales de opciones.

Uso (en tu ordenador, dentro de la carpeta del proyecto):
    python straddle_dvol.py
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import io
import time
import glob
import math
import contextlib
import requests
import numpy as np
import pandas as pd
import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CACHE = os.path.join(CARPETA, "cache")
URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
INICIO = pd.Timestamp("2021-03-01")
CORTE = pd.Timestamp("2025-01-01")
H = 42                         # 7 días en velas de 4h
T_ANIOS = 7 / 365
COSTE = 0.03
rng = np.random.default_rng(21)


# ------------------------------------------------------------------ DVOL
def descargar_dvol(moneda):
    ruta = os.path.join(CACHE, f"dvol_{moneda}.csv")
    if os.path.exists(ruta) and (time.time() - os.path.getmtime(ruta)) < 12 * 3600:
        return pd.read_csv(ruta, parse_dates=["t"])
    print(f"Descargando DVOL de {moneda} desde Deribit...")
    filas = []
    ini = int(INICIO.timestamp() * 1000)
    fin_total = int(time.time() * 1000)
    paso = 900 * 3600 * 1000                     # ventanas de 900 horas
    while ini < fin_total:
        fin = min(ini + paso, fin_total)
        for intento in range(3):
            try:
                r = requests.get(URL, params={"currency": moneda, "start_timestamp": ini,
                                              "end_timestamp": fin, "resolution": "3600"}, timeout=30)
                r.raise_for_status()
                filas.extend(r.json()["result"]["data"])
                break
            except Exception as e:
                if intento == 2:
                    raise SystemExit(f"No se pudo descargar el DVOL ({e}). Revisa tu conexión y vuelve a probar.")
                time.sleep(3)
        ini = fin + 1
        time.sleep(0.2)
    df = pd.DataFrame(filas, columns=["ts", "open", "high", "low", "close"]).drop_duplicates("ts")
    df["t"] = pd.to_datetime(df["ts"], unit="ms")
    df = df[["t", "close"]].rename(columns={"close": "dvol"}).sort_values("t")
    os.makedirs(CACHE, exist_ok=True)
    df.to_csv(ruta, index=False)
    print(f"  {len(df)} horas, del {df['t'].min():%Y-%m-%d} al {df['t'].max():%Y-%m-%d}")
    return df


# ------------------------------------------------------------------ precios y alertas
def cargar_precios(moneda):
    ficheros = sorted(glob.glob(os.path.join(CACHE, f"{moneda}_*.pkl")))
    if not ficheros:
        raise SystemExit(f"No hay caché de {moneda}: ejecuta antes backtest_senales.py")
    df = pd.read_pickle(ficheros[-1]).reset_index(drop=True)
    lr = np.log(df["close"]).diff()
    fa = df["funding_3d"].abs().rolling(2190, min_periods=540).rank(pct=True)
    df["alerta"] = (df["escenario"].astype(bool) | (lr.rolling(42).std() / lr.rolling(540).std() > PRM.VOL_RATIO)
                    | (fa >= PRM.FUND_PCT) | (df["vol_rel"] > PRM.VOLUMEN_REL))
    df["t_cierre"] = (df["t"] + pd.Timedelta(hours=4)).astype("datetime64[ns]")
    return df


# ------------------------------------------------------------------ Black-Scholes (tipo 0)
def N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def straddle(S, K, sigma, T):
    if T <= 0 or sigma <= 0:
        return abs(S - K)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    call = S * N(d1) - K * N(d2)
    put = K * N(-d2) - S * N(-d1)
    return call + put


def simular(df, dvol, i, modo):
    """Straddle comprado al cierre de la vela i. Devuelve rentabilidad sobre la prima pagada."""
    S0, K = df["close"].iloc[i], df["close"].iloc[i]
    iv0 = dvol.get(df["t_cierre"].iloc[i])
    if iv0 is None or not iv0 == iv0:
        return None
    prima = straddle(S0, K, iv0 / 100, T_ANIOS)
    pagado = prima * (1 + COSTE)
    for k in range(1, H + 1):
        j = i + k
        if j >= len(df):
            return None
        quedan = T_ANIOS * (H - k) / H
        S = df["close"].iloc[j]
        iv = dvol.get(df["t_cierre"].iloc[j], iv0)
        iv = iv if iv == iv else iv0
        if modo == "TOCA ±8 %" and k < H:
            hi, lo = df["high"].iloc[j], df["low"].iloc[j]
            if hi >= S0 * 1.08 or lo <= S0 * 0.92:
                Sx = S0 * 1.08 if hi >= S0 * 1.08 else S0 * 0.92
                valor = straddle(Sx, K, iv / 100, quedan)
                return valor * (1 - COSTE) / pagado - 1
        valor = straddle(S, K, iv / 100, quedan)
        if modo == "TP/SL 50 %" and k < H:
            if valor * (1 - COSTE) >= pagado * 1.5 or valor * (1 - COSTE) <= pagado * 0.5:
                return valor * (1 - COSTE) / pagado - 1
    return abs(S - K) * (1 - COSTE) / pagado - 1           # vencimiento


def casos(df, dvol, con_alerta, modo):
    out = []
    a = df["alerta"].fillna(False).values
    hora4 = (df["t"].dt.hour == 4).values
    i = 540
    while i < len(df) - H - 1:
        if hora4[i] and df["t"].iloc[i] >= INICIO and (a[i] if con_alerta else True):
            r = simular(df, dvol, i, modo)
            if r is not None:
                out.append({"t": df["t"].iloc[i], "r": r, "iv": dvol.get(df["t_cierre"].iloc[i])})
            i += H if con_alerta else 6          # sin alerta: un straddle cada día
        else:
            i += 1
    return pd.DataFrame(out)


def fila(nombre, E):
    if len(E) == 0:
        return f"{nombre:<34} sin casos"
    b = rng.choice(E["r"].values, size=(3000, len(E)), replace=True).mean(axis=1)
    tr, te = E[E["t"] < CORTE], E[E["t"] >= CORTE]
    return (f"{nombre:<34}{len(E):>5}{(E['r'] > 0).mean()*100:>9.0f}%{E['r'].mean()*100:>+9.1f}%"
            f"   [{np.percentile(b, 2.5)*100:+6.1f}, {np.percentile(b, 97.5)*100:+6.1f}]"
            f"{tr['r'].mean()*100:>+10.1f}%{te['r'].mean()*100:>+10.1f}%{E['iv'].mean():>8.0f}")


def main(dvols):
    print("Rentabilidad = sobre la prima pagada por straddle. IV media = DVOL medio al comprar.\n")
    cab = (f"{'prueba':<34}{'ops':>5}{'ganad.':>10}{'medio':>10}{'IC 95 %':>20}{'2021-24':>11}{'2025-hoy':>11}{'IV':>8}")
    for moneda in ["BTC", "ETH"]:
        dv = dvols[moneda]
        dvol = dict(zip(pd.to_datetime(dv["t"]).astype("datetime64[ns]"), dv["dvol"]))
        df = cargar_precios(moneda)
        print(f"\n==================== {moneda} ====================")
        print(cab)
        for modo in ["VENCIMIENTO", "TOCA ±8 %", "TP/SL 50 %"]:
            print(fila(f"CON alerta | {modo}", casos(df, dvol, True, modo)))
            print(fila(f"sin alerta | {modo}", casos(df, dvol, False, modo)))
    print("\nLectura: la alerta tiene valor si 'CON alerta' gana (medio > 0, IC > 0) y supera claramente a")
    print("'sin alerta' en los dos periodos. Recuerda: es una aproximación con el DVOL a 30 días.")


if __name__ == "__main__":
    dvols = {m: descargar_dvol(m) for m in ["BTC", "ETH"]}     # descarga visible por pantalla
    print("Calculando straddles (1-2 minutos)...")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(dvols)
    print(buf.getvalue())
    with open(os.path.join(CARPETA, "straddle_dvol_resultados.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Ejecutado: {pd.Timestamp.now():%Y-%m-%d %H:%M}\n\n" + buf.getvalue())
