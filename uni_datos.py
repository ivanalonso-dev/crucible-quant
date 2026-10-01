"""
uni_datos.py - Módulo común del sistema cuantitativo de UNI.
No se ejecuta directamente: lo usan uni_investigacion.py y uni_detector.py.

Descarga (todo público, sin cuenta):
  - Velas 4h spot UNIUSDT (Binance)
  - Velas 4h futuros perpetuos UNIUSDT (Binance Futures), con compras agresivas
  - Funding rate de los perpetuos
Construye las variables y define el catálogo de señales candidatas.
"""

import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)
import time
import requests
import numpy as np
import pandas as pd

SIMBOLO = "UNIUSDT"
SPOT = "https://data-api.binance.vision/api/v3/klines"
FAPI = "https://fapi.binance.com"
INICIO_MS = int(pd.Timestamp("2020-09-01").timestamp() * 1000)

CORTE = pd.Timestamp("2025-01-01")   # antes = entrenamiento, después = comprobación
H7 = 42                              # 7 días en velas de 4h
X = 0.08                             # umbral de "qué toca primero": -8 % / +8 %
VOL_SECO = 0.7
FUNDING_ALTO = 0.00015


# ------------------------------------------------------------------ descarga
def _get(url, params):
    for intento in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            if intento == 2:
                raise
            time.sleep(2)


def _fecha(ms):
    return pd.to_datetime(pd.Series(ms).astype("int64"), unit="ms").astype("datetime64[ns]").values


def velas(url, simbolo=SIMBOLO, intervalo="4h", limite=1000, desde_ms=INICIO_MS):
    filas, inicio = [], desde_ms
    while True:
        datos = _get(url, {"symbol": simbolo, "interval": intervalo, "startTime": inicio, "limit": limite})
        if not datos:
            break
        filas.extend(datos)
        inicio = int(datos[-1][6]) + 1
        if len(datos) < limite:
            break
        time.sleep(0.2)
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "qav", "trades", "tbbav", "tbqav", "ignore"]
    df = pd.DataFrame(filas, columns=cols)
    for c in ["open", "high", "low", "close", "volume", "tbbav"]:
        df[c] = df[c].astype(float)
    df["t"] = _fecha(df["open_time"])
    df = df[df["close_time"].astype("int64") < int(time.time() * 1000)]   # fuera la vela en curso
    return df[["t", "open", "high", "low", "close", "volume", "tbbav"]].drop_duplicates("t").reset_index(drop=True)


def velas_spot():
    return velas(SPOT)


def velas_perp():
    return velas(FAPI + "/fapi/v1/klines")


def funding(simbolo=SIMBOLO, desde_ms=INICIO_MS):
    filas, inicio = [], desde_ms
    while True:
        datos = _get(FAPI + "/fapi/v1/fundingRate", {"symbol": simbolo, "startTime": inicio, "limit": 1000})
        if not datos:
            break
        filas.extend(datos)
        inicio = int(datos[-1]["fundingTime"]) + 1
        if len(datos) < 1000:
            break
        time.sleep(0.2)
    if not filas:
        return pd.DataFrame({"t_f": pd.Series(dtype="datetime64[ns]"), "funding": pd.Series(dtype=float)})
    f = pd.DataFrame(filas)
    f["t_f"] = _fecha(f["fundingTime"])
    f = f.drop_duplicates("fundingTime").sort_values("fundingTime")
    f["funding_raw"] = f["fundingRate"].astype(float)
    # Binance cobra cada 8h, 4h o 1h según el contrato y la época: se normaliza a su equivalente en 8h
    horas = f["fundingTime"].astype("int64").diff() / 3_600_000
    horas = horas.round().clip(lower=1, upper=8).fillna(8)
    f["funding"] = f["funding_raw"] * 8 / horas
    return f[["t_f", "funding"]].drop_duplicates("t_f").sort_values("t_f").reset_index(drop=True)


def descargar_todo(simbolo=SIMBOLO, perp_simbolo=None, factor=1, desde_ms=INICIO_MS, silencioso=False):
    """spot + futuros + funding de una moneda. factor=1000 para contratos tipo 1000PEPEUSDT."""
    perp_simbolo = perp_simbolo or simbolo
    decir = (lambda *a: None) if silencioso else print
    decir(f"Descargando velas 4h de futuros de {perp_simbolo}...")
    perp = velas(FAPI + "/fapi/v1/klines", perp_simbolo, desde_ms=desde_ms)
    if factor != 1:                       # llevar el contrato a unidades de 1 moneda
        for c in ["open", "high", "low", "close"]:
            perp[c] = perp[c] / factor
        perp["volume"] *= factor
        perp["tbbav"] *= factor
    decir(f"Descargando velas 4h spot de {simbolo}...")
    try:
        spot = velas(SPOT, simbolo, desde_ms=desde_ms)
        if len(spot) == 0:
            raise ValueError("sin datos spot")
    except Exception:                     # sin spot en Binance: solo futuros
        spot = pd.DataFrame(columns=["t", "open", "high", "low", "close", "volume", "tbbav"])
    decir("Descargando funding...")
    fund = funding(perp_simbolo, desde_ms=desde_ms)
    return spot, perp, fund


# ------------------------------------------------------------------ universo top por capitalización
EXCLUIR = {"USDT", "USDC", "DAI", "USDE", "USDS", "FDUSD", "TUSD", "PYUSD", "USD1", "BUIDL", "USDTB",
           "WBTC", "WETH", "STETH", "WSTETH", "WEETH", "CBBTC", "WBETH", "RETH", "METH", "EZETH",
           "SUSDE", "SUSDS", "BSC-USD", "RLUSD", "XAUT", "PAXG", "LEO", "BTCB", "SOLVBTC", "LBTC",
           "JITOSOL", "MSOL", "BNSOL", "SAVAX", "OSETH", "RSETH", "CLBTC", "TBTC"}
RESERVA = ["BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "ADA", "TRX", "LINK", "AVAX", "SUI", "XLM",
           "TON", "HBAR", "BCH", "LTC", "DOT", "UNI", "NEAR", "AAVE", "APT", "ICP", "ETC", "PEPE",
           "SHIB", "HYPE", "ONDO", "ARB", "OP", "FIL", "ATOM", "INJ", "TAO", "ENA", "WLD"]


def top_monedas(n=30, incluir=("UNI",)):
    """Top n por capitalización (CoinGecko) que tengan perpetuo USDT en Binance."""
    info = _get(FAPI + "/fapi/v1/exchangeInfo", {})
    perps = {x["symbol"] for x in info["symbols"]
             if x.get("contractType") == "PERPETUAL" and x.get("quoteAsset") == "USDT" and x.get("status") == "TRADING"}
    try:
        cg = _get("https://api.coingecko.com/api/v3/coins/markets",
                  {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 150, "page": 1})
        orden = [c["symbol"].upper() for c in cg]
        print(f"Ranking por capitalización: CoinGecko ({len(orden)} monedas)")
    except Exception as e:
        print(f"CoinGecko no disponible ({e}); uso lista de reserva")
        orden = RESERVA

    def mapear(base):
        for f in (1, 1000, 1_000_000):
            p = f"{'' if f == 1 else f}{base}USDT"
            if p in perps:
                return {"base": base, "spot": f"{base}USDT", "perp": p, "factor": f}
        return None

    salida, vistos = [], set()
    for base in orden:
        if len(salida) >= n:
            break
        if base in vistos or base in EXCLUIR or "USD" in base:
            continue
        vistos.add(base)
        m = mapear(base)
        if m:
            salida.append(m)
    for base in incluir:
        if base not in {m["base"] for m in salida}:
            m = mapear(base)
            if m:
                salida.append(m)
    return salida


# ------------------------------------------------------------------ variables
def _primero(hi, lo, cl, arriba, abajo):
    """Para cada vela: qué nivel se toca primero en las 42 velas siguientes."""
    n = len(cl)
    res = np.full(n, None, dtype=object)
    for i in range(n - H7):
        r = "ninguno"
        for j in range(i + 1, i + H7 + 1):
            a, b = hi[j] > arriba[i], lo[j] < abajo[i]
            if a and b:
                r = "ambos"
                break
            if a:
                r = "arriba"
                break
            if b:
                r = "abajo"
                break
        res[i] = r
    return res


def construir(spot, perp, fund, umbrales=None):
    # base = futuros perpetuos (historial completo y siempre vivo); spot como complemento cuando existe
    s = spot.rename(columns={c: f"s_{c}" for c in ["open", "high", "low", "close", "volume", "tbbav"]})
    s["t"] = pd.to_datetime(s["t"]).astype("datetime64[ns]")
    for c in ["s_open", "s_high", "s_low", "s_close", "s_volume", "s_tbbav"]:
        s[c] = pd.to_numeric(s[c], errors="coerce")
    df = perp.merge(s, on="t", how="left").sort_values("t").reset_index(drop=True)

    df["verde"] = df["close"] > df["open"]
    df["sig_verde"] = df["verde"].shift(-1)
    df["ret_24h"] = df["close"].shift(-6) / df["close"] - 1
    df["ret_7d"] = df["close"].shift(-H7) / df["close"] - 1

    df["taker_spot"] = df["s_tbbav"].rolling(6).sum() / df["s_volume"].rolling(6).sum()
    df["taker_perp"] = df["tbbav"].rolling(6).sum() / df["volume"].rolling(6).sum()
    df["basis"] = (df["close"] / df["s_close"] - 1).rolling(6).mean()
    df["apalanc"] = df["volume"].rolling(6).sum() / df["s_volume"].rolling(6).sum()
    vt = df["volume"] + df["s_volume"].fillna(0)
    df["vol_rel"] = vt.rolling(30).mean() / vt.rolling(180).mean()

    df["max_30d"] = df["high"].rolling(180).max()
    df["min_60d"] = df["low"].rolling(360).min()
    df["subida_previa"] = df["max_30d"] / df["min_60d"] - 1
    df["caida_desde_max"] = df["close"] / df["max_30d"] - 1
    df["escenario"] = (df["subida_previa"] > PRM.RALLY_MIN) & df["caida_desde_max"].between(PRM.CAIDA_MIN, PRM.CAIDA_MAX)

    df["t_cierre"] = (df["t"] + pd.Timedelta(hours=4)).astype("datetime64[ns]")
    df = pd.merge_asof(df.sort_values("t_cierre"), fund, left_on="t_cierre", right_on="t_f",
                       direction="backward").sort_values("t").reset_index(drop=True)
    df["funding_3d"] = df["funding"].rolling(18, min_periods=6).mean()

    # rango de los últimos 7 días (soporte y resistencia dinámicos)
    df["rango_min"] = df["low"].rolling(H7).min()
    df["rango_max"] = df["high"].rolling(H7).max()

    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    df["primero_8"] = _primero(hi, lo, cl, cl * (1 + X), cl * (1 - X))
    df["primero_rango"] = _primero(hi, lo, cl, df["rango_max"].values, df["rango_min"].values)
    df.loc[df["rango_min"].isna(), "primero_rango"] = None

    if umbrales is None:          # cortes fijados SOLO con datos de entrenamiento
        tr = df[df["t"] < CORTE]
        umbrales = {
            "taker_perp_q33": float(tr["taker_perp"].quantile(1 / 3)),
            "taker_perp_q67": float(tr["taker_perp"].quantile(2 / 3)),
            "basis_q20": float(tr["basis"].quantile(0.2)),
            "basis_q80": float(tr["basis"].quantile(0.8)),
            "apalanc_q20": float(tr["apalanc"].quantile(0.2)),
            "apalanc_q80": float(tr["apalanc"].quantile(0.8)),
        }
    return df, umbrales


# ------------------------------------------------------------------ señales candidatas
def senales(df, u):
    return {
        "funding_negativo":     ("Funding 3 días negativo (cortos pagando)", df["funding_3d"] < 0),
        "funding_alto":         ("Funding 3 días alto (largos apalancados pagando)", df["funding_3d"] > FUNDING_ALTO),
        "taker_perp_comprador": ("Compras agresivas en futuros: tercio alto", df["taker_perp"] > u["taker_perp_q67"]),
        "taker_perp_vendedor":  ("Compras agresivas en futuros: tercio bajo", df["taker_perp"] < u["taker_perp_q33"]),
        "basis_descuento":      ("Futuros con descuento fuerte frente al spot", df["basis"] < u["basis_q20"]),
        "basis_prima":          ("Futuros con prima fuerte frente al spot", df["basis"] > u["basis_q80"]),
        "apalancamiento_alto":  ("Volumen de futuros muy superior al spot", df["apalanc"] > u["apalanc_q80"]),
        "apalancamiento_bajo":  ("Volumen de futuros bajo frente al spot", df["apalanc"] < u["apalanc_q20"]),
        "volumen_seco":         ("Volumen 5 días < 0,7x la media de 30", df["vol_rel"] < VOL_SECO),
        "vela_roja":            ("Última vela 4h roja", ~df["verde"].astype(bool)),
        "vela_verde":           ("Última vela 4h verde", df["verde"].astype(bool)),
    }


def universos(df):
    return {
        "todas": pd.Series(True, index=df.index),
        "escenario": df["escenario"].astype(bool),
    }


def metricas(d):
    d7 = d.dropna(subset=["ret_7d"])
    out = {"n": int(len(d7))}
    if len(d7) == 0:
        return out
    p8 = d7["primero_8"].dropna()
    pr = d7["primero_rango"].dropna()
    out.update({
        "p_4h_verde": float(d7["sig_verde"].astype(bool).mean()),
        "p_24h_arriba": float((d7["ret_24h"] > 0).mean()),
        "p_7d_arriba": float((d7["ret_7d"] > 0).mean()),
        "mediana_7d": float(d7["ret_7d"].median()),
        "p25_7d": float(d7["ret_7d"].quantile(0.25)),
        "p75_7d": float(d7["ret_7d"].quantile(0.75)),
        "primero_menos8": float((p8 == "abajo").mean()) if len(p8) else None,
        "primero_mas8": float((p8 == "arriba").mean()) if len(p8) else None,
        "rompe_soporte": float((pr == "abajo").mean()) if len(pr) else None,
        "rompe_resistencia": float((pr == "arriba").mean()) if len(pr) else None,
    })
    return out