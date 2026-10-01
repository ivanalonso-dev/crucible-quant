"""
backtest_cartera.py - SOFTWARE 2 (v2): ¿se puede operar la señal con una cartera real?

Trabaja con las señales de backtest_senales.py (senales_aprobadas.json). Aquí se decide
CÓMO operarlas y se comprueba si las mejoras ayudan, con un protocolo fijado de antemano:

PROTOCOLO (anti-sobreajuste)
  1. Entrenamiento: 2020-09 a 2024-12.  Comprobación: 2025-01 hasta hoy. 88.000 $ en cada una.
  2. Cada mejora se prueba por separado sobre la BASE, SOLO en entrenamiento.
     Se queda si sube el Sharpe >= 0,10 y no empeora la caída máxima más de 5 puntos.
  3. Las mejoras que se quedan se combinan y se prueban UNA vez en comprobación. Sin retoques.

HIGIENE (siempre activa, no es una "mejora"):
  - Solo monedas con al menos 365 días de historial en el momento de operar.
  - Liquidez: volumen medio de futuros de 30 días >= 20 M$/día.
  - Informe de concentración: resultado sin la mejor moneda y peso de la mejor moneda.

BASE: señal funding_alto, 4 % del capital por posición, sin stop, máx. 5, salida a 7 días.

MEJORAS candidatas (con lógica de mercado):
  - Régimen: solo operar si BTC está por encima de su media de 200 días.
  - Confirmación: funding alto Y la moneda entre las 3 de más momentum de 7 días.
  - Tamaño por volatilidad: 4 % x (60 % / volatilidad anual de la moneda), entre 1 % y 8 %.

Costes: 0,1 % comisión + 0,05 % deslizamiento por lado. Entrada en la apertura siguiente.
Uso:  python backtest_cartera.py      Guarda cartera_operaciones.csv y cartera_curva.csv
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import glob
import numpy as np
import pandas as pd
import uni_datos as ud

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CACHE = os.path.join(CARPETA, "cache")

CAPITAL = 88_000
COMISION = 0.001
DESLIZ = 0.0005
H = ud.H7
TRAIN = (pd.Timestamp("2020-09-01"), pd.Timestamp("2025-01-01"))
TEST = (pd.Timestamp("2025-01-01"), None)
MIN_DIAS = 365
MIN_LIQUIDEZ = 20e6
SHARPE_MIN = 0.10
DD_MAX_PEOR = 0.05

BASE = {"peso": 0.04, "max": 5, "regimen": False, "confirmacion": False, "vol": False}
MEJORAS = {"regimen": "Régimen BTC > media 200d", "confirmacion": "Confirmación momentum top 3",
           "vol": "Tamaño por volatilidad"}


# ------------------------------------------------------------------ datos
def cargar():
    ficheros = sorted(glob.glob(os.path.join(CACHE, "*.pkl")))
    if not ficheros:
        raise SystemExit("No hay caché: ejecuta antes backtest_senales.py o backtest.py")
    ultimo = max(os.path.basename(f).split("_")[1] for f in ficheros)
    return {os.path.basename(f).split("_")[0]: pd.read_pickle(f)
            for f in ficheros if os.path.basename(f).split("_")[1] == ultimo}


def preparar(d):
    btc = d["BTC"][["t", "close"]].copy()
    btc["btc_ok"] = btc["close"] > btc["close"].rolling(1200).mean()        # 200 días en velas de 4h
    filas = []
    for b, df in d.items():
        x = df[["t", "open", "high", "low", "close", "volume", "funding_3d"]].copy()
        x["base"] = b
        x["edad"] = (x["t"] - x["t"].iloc[0]).dt.days
        x["liquidez"] = (x["volume"] * x["close"]).rolling(180).mean() * 6   # $/día, media 30 días
        x["vol_anual"] = np.log(x["close"]).diff().rolling(180).std() * np.sqrt(6 * 365)
        x["mom"] = x["close"] / x["close"].shift(42) - 1
        x["senal"] = x["funding_3d"] > ud.FUNDING_ALTO
        filas.append(x)
    P = pd.concat(filas, ignore_index=True)
    P = P.merge(btc[["t", "btc_ok"]], on="t", how="left")
    P["btc_ok"] = P["btc_ok"].fillna(False).astype(bool)
    g = P.groupby("t")["mom"]
    P["mom_top3"] = (g.rank(ascending=False, method="first") <= 3) & (g.transform("count") >= 10)
    P["apta"] = (P["edad"] >= MIN_DIAS) & (P["liquidez"] >= MIN_LIQUIDEZ)
    return P.sort_values(["t", "base"]).reset_index(drop=True)


# ------------------------------------------------------------------ simulación
def simular(P, cfg, ventana, etiqueta):
    ini, fin = ventana
    X = P[(P["t"] >= ini) & ((P["t"] < fin) if fin is not None else True)]
    act = X["senal"] & X["apta"]
    if cfg["regimen"]:
        act &= X["btc_ok"]
    if cfg["confirmacion"]:
        act &= X["mom_top3"]
    X = X.assign(activa=act.values)

    cash, abiertas, pendientes, ultimo = float(CAPITAL), {}, {}, {}
    trades, curva = [], []

    def equity():
        return cash + sum(p["qty"] * ultimo[b] for b, p in abiertas.items())

    for t, g in X.groupby("t", sort=True):
        filas = {r.base: r for r in g.itertuples(index=False)}
        for b, r in filas.items():
            ultimo[b] = r.close

        for b in sorted(pendientes, key=lambda k: -pendientes[k][0]):
            if b not in filas or b in abiertas or len(abiertas) >= cfg["max"]:
                continue
            peso = cfg["peso"]
            if cfg["vol"]:
                v = pendientes[b][1]
                peso = float(np.clip(cfg["peso"] * 0.60 / v, 0.01, 0.08)) if v == v and v > 0 else cfg["peso"]
            notional = min(equity() * peso, cash / (1 + COMISION))
            if notional < 50:
                continue
            precio = filas[b].open * (1 + DESLIZ)
            cash -= notional * (1 + COMISION)
            abiertas[b] = {"qty": notional / precio, "entrada": precio, "notional": notional, "t": t, "velas": 0}
        pendientes = {}

        for b in list(abiertas):
            if b not in filas:
                continue
            p = abiertas[b]
            p["velas"] += 1
            if p["velas"] >= H:
                salida = filas[b].close * (1 - DESLIZ)
                bruto = p["qty"] * salida * (1 - COMISION)
                cash += bruto
                neto = bruto - p["notional"] * (1 + COMISION)
                trades.append({"prueba": etiqueta, "moneda": b, "entrada_t": p["t"], "salida_t": t,
                               "precio_entrada": p["entrada"], "precio_salida": salida, "invertido": p["notional"],
                               "resultado_usd": neto, "resultado_pct": neto / p["notional"]})
                del abiertas[b]

        for b, r in filas.items():
            if r.activa and b not in abiertas:
                pendientes[b] = (r.funding_3d, r.vol_anual)

        curva.append({"prueba": etiqueta, "t": t, "capital": equity(), "posiciones": len(abiertas)})

    t_fin = X["t"].max()
    for b, p in abiertas.items():
        bruto = p["qty"] * ultimo[b] * (1 - DESLIZ) * (1 - COMISION)
        cash += bruto
        neto = bruto - p["notional"] * (1 + COMISION)
        trades.append({"prueba": etiqueta, "moneda": b, "entrada_t": p["t"], "salida_t": t_fin,
                       "precio_entrada": p["entrada"], "precio_salida": ultimo[b], "invertido": p["notional"],
                       "resultado_usd": neto, "resultado_pct": neto / p["notional"]})
    curva[-1]["capital"] = cash
    return pd.DataFrame(trades), pd.DataFrame(curva)


def metricas(tr, cv):
    s = cv.set_index("t")["capital"]
    dia = s.resample("1D").last().dropna()
    r = dia.pct_change().dropna()
    anios = max((dia.index[-1] - dia.index[0]).days / 365.25, 1 / 365)
    m = {"final": s.iloc[-1], "anual": (s.iloc[-1] / CAPITAL) ** (1 / anios) - 1,
         "dd": (s / s.cummax() - 1).min(), "sharpe": r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else 0.0,
         "n": len(tr), "invertido": (cv["posiciones"] > 0).mean(), "acierto": 0, "pf": 0,
         "sin_mejor": 0, "peso_mejor": 0, "mejor": "-"}
    if len(tr):
        g = tr.loc[tr.resultado_usd > 0, "resultado_usd"].sum()
        p = -tr.loc[tr.resultado_usd < 0, "resultado_usd"].sum()
        pm = tr.groupby("moneda")["resultado_usd"].sum().sort_values()
        total = tr["resultado_usd"].sum()
        m.update({"acierto": (tr.resultado_usd > 0).mean(), "pf": g / p if p > 0 else np.inf,
                  "sin_mejor": total - pm.iloc[-1], "mejor": pm.index[-1],
                  "peso_mejor": pm.iloc[-1] / total if total > 0 else np.nan})
    return m


def linea(nombre, m):
    pm = "   n/a" if m["peso_mejor"] != m["peso_mejor"] else f"{m['peso_mejor']*100:>5.0f}%"
    return (f"{nombre:<44}{m['final']:>10,.0f}${m['anual']*100:>+7.1f}%{m['dd']*100:>+8.1f}%{m['sharpe']:>7.2f}"
            f"{m['n']:>5}{m['acierto']*100:>7.1f}%{m['pf']:>6.2f}{m['invertido']*100:>6.0f}%"
            f"{m['sin_mejor']:>+11,.0f}$  {m['mejor']:<5}{pm}")


CAB = (f"{'prueba':<44}{'final':>11}{'anual':>8}{'c.máx':>9}{'Sharpe':>7}{'ops':>5}{'acierto':>8}{'PF':>6}"
       f"{'inv.':>7}{'sin mejor':>12}  mejor moneda (peso)")


def btc_hold(P, ventana):
    ini, fin = ventana
    x = P[(P["base"] == "BTC") & (P["t"] >= ini) & ((P["t"] < fin) if fin is not None else True)]
    s = pd.Series(CAPITAL * x["close"].values / x["open"].values[0], index=x["t"].values)
    anios = (s.index[-1] - s.index[0]).days / 365.25
    return s.iloc[-1], (s.iloc[-1] / CAPITAL) ** (1 / anios) - 1, (s / s.cummax() - 1).min()


def main():
    P = preparar(cargar())
    print("Higiene: >= 365 días de historial y >= 20 M$/día de liquidez en futuros.")
    todas_tr, todas_cv = [], []

    def correr(cfg, ventana, etiqueta):
        tr, cv = simular(P, cfg, ventana, etiqueta)
        todas_tr.append(tr)
        todas_cv.append(cv)
        return metricas(tr, cv)

    # ---------- paso 1: selección SOLO en entrenamiento
    print(f"\n==================== PASO 1 - ENTRENAMIENTO (2020-09 a 2024-12) ====================")
    print(CAB)
    mb = correr(BASE, TRAIN, "train: BASE")
    print(linea("BASE (funding alto, 4 %, sin stop, máx 5)", mb))
    elegidas = []
    for k, nombre in MEJORAS.items():
        m = correr({**BASE, k: True}, TRAIN, f"train: +{k}")
        ok = (m["sharpe"] - mb["sharpe"] >= SHARPE_MIN) and (m["dd"] >= mb["dd"] - DD_MAX_PEOR)
        print(linea(f"+ {nombre}", m) + ("   -> SE QUEDA" if ok else "   -> descartada"))
        if ok:
            elegidas.append(k)
    final = {**BASE, **{k: True for k in elegidas}}
    nombre_final = "FINAL: BASE" + "".join(f" + {MEJORAS[k]}" for k in elegidas)
    if len(elegidas) > 1:
        print(linea(nombre_final + " (entrenamiento)", correr(final, TRAIN, "train: FINAL")))
    b = btc_hold(P, TRAIN)
    print(f"{'Comprar BTC y mantener':<44}{b[0]:>10,.0f}${b[1]*100:>+7.1f}%{b[2]*100:>+8.1f}%")

    # ---------- paso 2: comprobación UNA vez
    print(f"\n==================== PASO 2 - COMPROBACIÓN (2025-01 a hoy), una sola vez ====================")
    print(CAB)
    print(linea(nombre_final, correr(final, TEST, "test: FINAL")))
    if elegidas:
        print(linea("(referencia) BASE sin mejoras", correr(BASE, TEST, "test: BASE")))
    b = btc_hold(P, TEST)
    print(f"{'Comprar BTC y mantener':<44}{b[0]:>10,.0f}${b[1]*100:>+7.1f}%{b[2]*100:>+8.1f}%")

    pd.concat(todas_tr).to_csv(os.path.join(CARPETA, "cartera_operaciones.csv"), index=False)
    pd.concat(todas_cv).to_csv(os.path.join(CARPETA, "cartera_curva.csv"), index=False)
    print("\n'sin mejor' = resultado total quitando la moneda que más ganó. Si es negativo, no es robusto.")
    print("Guardado: cartera_operaciones.csv y cartera_curva.csv\n")


if __name__ == "__main__":
    main()
