"""
UNI v3 - Estadística en velas de 4h con más variables (solo Uniswap).

Datos (todo público, sin cuenta):
  - Velas 4h de UNIUSDT desde 2020 (~13.000 velas) con volumen de compras agresivas (taker buy)
  - Funding rate de los futuros perpetuos UNIUSDT (cada 8h)

Variables:
  - Presión compradora 24h: % del volumen que fueron compras agresivas
  - Volumen: últimos 5 días vs media de 30 días
  - Funding medio de 3 días: negativo / normal / alto
  - Color de la última vela 4h
  - Escenario: rally previo fuerte y corrección moderada desde el máximo de 30 días

Qué mide después de cada vela:
  - Próxima vela 4h verde
  - Precio más arriba en 24h y en 7 días
  - Qué toca PRIMERO en 7 días: -8 % o +8 %

Y comprueba si cada señal SE SOSTIENE: calcula el efecto en 2020-2024 y lo verifica
en 2025-2026 (datos que la señal "no ha visto").

Uso:  pip install requests pandas numpy
      python uni_v3.py
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)
import time
import requests
import numpy as np
import pandas as pd

SPOT = "https://data-api.binance.vision/api/v3/klines"
FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"
SIMBOLO = "UNIUSDT"

X = 0.08            # umbral para "qué toca primero": -8 % / +8 %
HORIZONTE = 42      # 7 días en velas de 4h
CORTE = pd.Timestamp("2025-01-01")   # antes = entrenamiento, después = comprobación
VOL_SECO = 0.7
FUNDING_ALTO = 0.00015   # 0,015 % cada 8h (lo neutro es 0,01 %)


# ----------------------------------------------------------------- descarga
def velas(simbolo, intervalo="4h"):
    filas, inicio = [], 0
    while True:
        r = requests.get(SPOT, params={"symbol": simbolo, "interval": intervalo,
                                       "startTime": inicio, "limit": 1000}, timeout=30)
        r.raise_for_status()
        datos = r.json()
        if not datos:
            break
        filas.extend(datos)
        inicio = datos[-1][6] + 1
        if len(datos) < 1000:
            break
        time.sleep(0.2)
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "qav", "trades", "tbbav", "tbqav", "ignore"]
    df = pd.DataFrame(filas, columns=cols)
    for c in ["open", "high", "low", "close", "volume", "tbbav"]:
        df[c] = df[c].astype(float)
    df["t"] = pd.to_datetime(df["open_time"], unit="ms").astype("datetime64[ns]")
    df = df[df["close_time"] < int(time.time() * 1000)]      # fuera la vela en curso
    return df[["t", "open", "high", "low", "close", "volume", "tbbav"]].reset_index(drop=True)


def funding(simbolo):
    # con startTime=0 Binance devuelve solo los 1000 últimos registros: hay que empezar en una fecha real
    filas, inicio = [], int(pd.Timestamp("2020-09-01").timestamp() * 1000)
    while True:
        r = requests.get(FUNDING, params={"symbol": simbolo, "startTime": inicio, "limit": 1000}, timeout=30)
        r.raise_for_status()
        datos = r.json()
        if not datos:
            break
        filas.extend(datos)
        inicio = datos[-1]["fundingTime"] + 1
        if len(datos) < 1000:
            break
        time.sleep(0.2)
    f = pd.DataFrame(filas)
    f["t_f"] = pd.to_datetime(f["fundingTime"].astype("int64"), unit="ms").astype("datetime64[ns]")
    f["funding"] = f["fundingRate"].astype(float)
    return f[["t_f", "funding"]].sort_values("t_f")


# ----------------------------------------------------------------- variables
def preparar(df, fund):
    df["verde"] = df["close"] > df["open"]
    df["sig_verde"] = df["verde"].shift(-1)
    df["ret_24h"] = df["close"].shift(-6) / df["close"] - 1
    df["ret_7d"] = df["close"].shift(-HORIZONTE) / df["close"] - 1

    df["taker"] = df["tbbav"].rolling(6).sum() / df["volume"].rolling(6).sum()
    df["vol_rel"] = df["volume"].rolling(30).mean() / df["volume"].rolling(180).mean()
    df["max_30d"] = df["high"].rolling(180).max()
    df["min_60d"] = df["low"].rolling(360).min()
    df["subida_previa"] = df["max_30d"] / df["min_60d"] - 1
    df["caida_desde_max"] = df["close"] / df["max_30d"] - 1
    df["escenario"] = (df["subida_previa"] > PRM.RALLY_MIN) & df["caida_desde_max"].between(PRM.CAIDA_MIN, PRM.CAIDA_MAX)

    if fund is not None:
        df["t_cierre"] = (df["t"] + pd.Timedelta(hours=4)).astype("datetime64[ns]")
        df = pd.merge_asof(df.sort_values("t_cierre"), fund, left_on="t_cierre",
                           right_on="t_f", direction="backward").sort_values("t").reset_index(drop=True)
        df["funding_3d"] = df["funding"].rolling(18).mean()
    else:
        df["funding_3d"] = np.nan

    # qué toca primero en los próximos 7 días: -X o +X
    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    primero = np.full(len(df), None, dtype=object)
    for i in range(len(df) - HORIZONTE):
        up, dn = cl[i] * (1 + X), cl[i] * (1 - X)
        res = "ninguno"
        for j in range(i + 1, i + HORIZONTE + 1):
            a, b = hi[j] >= up, lo[j] <= dn
            if a and b:
                res = "ambos"
                break
            if a:
                res = "arriba"
                break
            if b:
                res = "abajo"
                break
        primero[i] = res
    df["primero"] = primero

    # grupos (los cortes de presión compradora se fijan SOLO con datos de entrenamiento)
    tr = df[df["t"] < CORTE]["taker"].dropna()
    q1, q2 = tr.quantile(1 / 3), tr.quantile(2 / 3)
    df["g_taker"] = np.select([df["taker"] < q1, df["taker"] > q2], ["vendedora", "compradora"], "neutra")
    df.loc[df["taker"].isna(), "g_taker"] = None
    df["g_vol"] = np.where(df["vol_rel"] < VOL_SECO, "secándose", "normal/alto")
    df.loc[df["vol_rel"].isna(), "g_vol"] = None
    df["g_fund"] = np.select([df["funding_3d"] < 0, df["funding_3d"] > FUNDING_ALTO],
                             ["negativo", "alto"], "normal")
    df.loc[df["funding_3d"].isna(), "g_fund"] = None
    df["g_vela"] = np.where(df["verde"], "verde", "roja")
    return df, (q1, q2)


# ----------------------------------------------------------------- informes
def cabecera():
    print(f"{'':<40}{'velas':>7}     {'4h verde':>10}   {'24h arriba':>10}   {'7d arriba (mediana)':>20}   {'primero -8% / +8%':>18}")


def fila(etiqueta, d):
    d = d.dropna(subset=["sig_verde"])
    n = len(d)
    if n == 0:
        print(f"{etiqueta:<40}{'sin casos':>7}")
        return
    p = d["sig_verde"].astype(bool).mean()
    m = 1.96 * np.sqrt(p * (1 - p) / n)
    r24, r7 = d["ret_24h"].dropna(), d["ret_7d"].dropna()
    pr = d["primero"].dropna()
    aviso = " (!)" if n < 300 else "    "
    s24 = f"{(r24 > 0).mean()*100:5.1f} %" if len(r24) else "   -   "
    s7 = f"{(r7 > 0).mean()*100:5.1f} % ({r7.median()*100:+5.1f} %)" if len(r7) else "        -        "
    sp = f"{(pr == 'abajo').mean()*100:5.1f} / {(pr == 'arriba').mean()*100:5.1f} %" if len(pr) else "   -   "
    print(f"{etiqueta:<40}{n:>7}{aviso} {p*100:5.1f}±{m*100:3.1f} %   {s24:>10}   {s7:>20}   {sp:>18}")


def bloque(titulo, d):
    print(f"\n--- {titulo} ---")
    cabecera()
    fila("Todas las velas del bloque", d)
    for col, nombre in [("g_vela", "Última vela"), ("g_taker", "Presión compradora"),
                        ("g_vol", "Volumen"), ("g_fund", "Funding")]:
        for valor in [v for v in d[col].dropna().unique()]:
            fila(f"  {nombre}: {valor}", d[d[col] == valor])


def estabilidad(titulo, d):
    """Efecto de cada grupo sobre '24h arriba' en 2020-24 vs 2025-26."""
    print(f"\n--- ¿SE SOSTIENE? {titulo}  (efecto sobre '24h arriba' vs la media del periodo) ---")
    print(f"{'':<40}{'2020-2024':>12}{'2025-2026':>12}   veredicto")
    tr, te = d[d["t"] < CORTE], d[d["t"] >= CORTE]
    base_tr = (tr["ret_24h"].dropna() > 0).mean()
    base_te = (te["ret_24h"].dropna() > 0).mean()
    for col, nombre in [("g_vela", "Última vela"), ("g_taker", "Presión compradora"),
                        ("g_vol", "Volumen"), ("g_fund", "Funding")]:
        for valor in [v for v in d[col].dropna().unique()]:
            a = tr[tr[col] == valor]["ret_24h"].dropna()
            b = te[te[col] == valor]["ret_24h"].dropna()
            etiqueta = f"  {nombre}: {valor}"
            if len(a) < 100 or len(b) < 100:
                print(f"{etiqueta:<40}{'muestra insuficiente':>24}")
                continue
            da, db = (a > 0).mean() - base_tr, (b > 0).mean() - base_te
            ok = np.sign(da) == np.sign(db) and abs(da) > 0.02 and abs(db) > 0.02
            print(f"{etiqueta:<40}{da*100:+9.1f} pts{db*100:+9.1f} pts   {'SE SOSTIENE' if ok else 'ruido'}")


def main():
    print("Descargando velas 4h de UNI...")
    uni = velas(SIMBOLO)
    try:
        print("Descargando funding de futuros...")
        fund = funding(SIMBOLO)
    except Exception as e:
        print(f"  (no se pudo descargar el funding: {e} -> sigo sin él)")
        fund = None

    df, (q1, q2) = preparar(uni, fund)
    print(f"\n{SIMBOLO}: {len(df)} velas de 4h, del {df['t'].iloc[0]:%Y-%m-%d} al {df['t'].iloc[-1]:%Y-%m-%d %H:%M} UTC")

    u = df.iloc[-1]
    print("\n==================== SITUACIÓN ACTUAL DE UNI (última vela 4h cerrada) ====================")
    print(f"Vela: {u['t']:%Y-%m-%d %H:%M} UTC  |  {u['g_vela']}  |  cierre {u['close']:.3f}")
    print(f"Escenario rally+corrección: {'SÍ' if u['escenario'] else 'NO'}  "
          f"(rally {u['subida_previa']*100:+.0f} %, caída desde máximo {u['caida_desde_max']*100:+.1f} %)")
    print(f"Presión compradora 24h: {u['taker']*100:.1f} % -> {u['g_taker']}  (cortes: {q1*100:.1f} % / {q2*100:.1f} %)")
    print(f"Volumen 5d vs 30d: {u['vol_rel']:.2f}x -> {u['g_vol']}")
    if pd.notna(u["funding_3d"]):
        print(f"Funding medio 3 días: {u['funding_3d']*100:.4f} % -> {u['g_fund']}")
    print(f"Niveles 'qué toca primero': -8 % = {u['close']*(1-X):.3f}  |  +8 % = {u['close']*(1+X):.3f}")

    print("\n==================== RESULTADOS ====================")
    print("(!) = menos de 300 velas, poco fiable.  El ± es el margen de error al 95 %.")
    bloque("TODAS LAS VELAS (tasa base de UNI)", df)
    esc = df[df["escenario"]]
    bloque("ESCENARIO: rally fuerte + corrección", esc)

    estabilidad("todas las velas", df)
    estabilidad("escenario", esc)

    print("\n==================== PERFIL EXACTO DE HOY ====================")
    cabecera()
    columnas = ["g_vela", "g_taker", "g_vol", "g_fund"]
    mismo = np.ones(len(df), dtype=bool)
    for c in columnas:
        if pd.notna(u[c]):
            mismo &= (df[c] == u[c]).values
    fila("Mismo perfil (todas las variables)", df[mismo])
    fila("Mismo perfil + escenario", df[mismo & df["escenario"].values])
    for c in columnas:          # quitando una variable cada vez, por si la muestra es pequeña
        m2 = np.ones(len(df), dtype=bool)
        for c2 in columnas:
            if c2 != c and pd.notna(u[c2]):
                m2 &= (df[c2] == u[c2]).values
        fila(f"  sin '{c[2:]}'", df[m2 & df["escenario"].values])
    print()


if __name__ == "__main__":
    main()