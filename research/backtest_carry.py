"""
backtest_carry.py - Estrategia de CARRY DE FUNDING (neutral al precio).

Idea: comprar X en spot y vender X en el perpetuo por el mismo importe. El precio da igual
(lo que gana una pata lo pierde la otra) y se COBRA el funding mientras sea positivo.
Es la estrategia cuantitativa con más evidencia en cripto.

Reglas (fijadas antes de ver resultados):
  - Universo: monedas con spot Y perpetuo en Binance, >= 365 días de historial, >= 20 M$/día.
  - Entrar cuando el funding medio de 3 días supera el umbral de ENTRADA; salir cuando baja
    del umbral de SALIDA (histéresis para no entrar y salir cada día).
  - Máximo 5 posiciones; si hay más candidatas, las de más funding. Capital repartido a partes
    iguales: cada posición usa 1/5 del capital, la MITAD en spot y la mitad como margen del corto
    (corto a 1x: sin riesgo real de liquidación por movimientos normales).
  - Entrada y salida en la APERTURA de la vela siguiente a la decisión.
  - Funding cobrado vela a vela (tasa normalizada a 8h -> la mitad por vela de 4h).
  - El resultado incluye: funding cobrado + variación del basis (diferencia spot/perpetuo) - costes.
  - Costes: 4 órdenes por operación completa (2 al entrar, 2 al salir). Dos escenarios:
      TAKER (órdenes a mercado): 0,10 % + 0,05 % de deslizamiento por orden
      MAKER (órdenes limitadas): 0,02 % + 0,02 % por orden
  - El dinero no invertido no rinde nada (hipótesis conservadora).

Protocolo:
  1. Entrenamiento 2020-09 a 2024-12: se comparan dos variantes de umbrales (con costes TAKER)
     y se elige la de mayor Sharpe.
  2. Comprobación 2025-01 a hoy: la variante elegida, UNA vez, con los dos escenarios de costes.

Uso:  python backtest_carry.py   (usa la carpeta cache/)
Guarda: carry_operaciones.csv y carry_curva.csv
"""

import os
import glob
import numpy as np
import pandas as pd

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CACHE = os.path.join(CARPETA, "cache")

CAPITAL = 88_000
MAX_POS = 5
MIN_DIAS = 365
MIN_LIQUIDEZ = 20e6
TRAIN = (pd.Timestamp("2020-09-01"), pd.Timestamp("2025-01-01"))
TEST = (pd.Timestamp("2025-01-01"), None)
COSTES = {"TAKER": 0.0015, "MAKER": 0.0004}      # por orden
VARIANTES = {
    "A: entra >0,015 % | sale <0,005 %": (0.00015, 0.00005),
    "B: entra >0,010 % | sale <0,000 %": (0.00010, 0.0),
}


def cargar():
    ficheros = sorted(glob.glob(os.path.join(CACHE, "*.pkl")))
    if not ficheros:
        raise SystemExit("No hay caché: ejecuta antes backtest_senales.py o backtest.py")
    ultimo = max(os.path.basename(f).split("_")[1] for f in ficheros)
    filas = []
    for f in ficheros:
        if os.path.basename(f).split("_")[1] != ultimo:
            continue
        b = os.path.basename(f).split("_")[0]
        df = pd.read_pickle(f)
        if "s_close" not in df or df["s_close"].notna().sum() == 0:
            continue
        x = df[["t", "open", "close", "volume", "funding", "funding_3d", "s_open", "s_close"]].copy()
        x["base"] = b
        x["edad"] = (x["t"] - x["t"].iloc[0]).dt.days
        x["liquidez"] = (x["volume"] * x["close"]).rolling(180).mean() * 6
        x["apta"] = (x["edad"] >= MIN_DIAS) & (x["liquidez"] >= MIN_LIQUIDEZ) & x["s_close"].notna()
        filas.append(x)
    return pd.concat(filas, ignore_index=True).sort_values(["t", "base"])


def simular(P, entra, sale, coste, ventana, etiqueta):
    ini, fin = ventana
    X = P[(P["t"] >= ini) & ((P["t"] < fin) if fin is not None else True)]
    cash, pos, pend_in, pend_out, trades, curva = float(CAPITAL), {}, {}, set(), [], []
    ultimo = {}

    def valor(p, r):
        return p["capital"] + p["q"] * (r.s_close - p["s0"]) - p["q"] * (r.close - p["p0"]) + p["funding"]

    for t, g in X.groupby("t", sort=True):
        filas = {r.base: r for r in g.itertuples(index=False)}
        for b, r in filas.items():
            ultimo[b] = r

        # salidas pendientes (a la apertura)
        for b in list(pend_out):
            if b in pos and b in filas:
                r, p = filas[b], pos.pop(b)
                s1, p1 = r.s_open, r.open
                if not (s1 == s1 and p1 == p1):
                    s1, p1 = ultimo[b].s_close, ultimo[b].close
                base_pnl = p["q"] * (s1 - p["s0"]) - p["q"] * (p1 - p["p0"])
                c_out = p["q"] * (s1 + p1) * coste
                cash += p["capital"] + base_pnl + p["funding"] - c_out
                trades.append({"prueba": etiqueta, "moneda": b, "entrada_t": p["t"], "salida_t": t,
                               "dias": (t - p["t"]).days, "invertido": p["capital"], "funding_usd": p["funding"],
                               "basis_usd": base_pnl, "costes_usd": p["c_in"] + c_out,
                               "resultado_usd": base_pnl + p["funding"] - p["c_in"] - c_out})
        pend_out = set()

        # entradas pendientes (a la apertura), por funding descendente
        eq = cash + sum(valor(p, ultimo[b]) for b, p in pos.items())
        for b in sorted(pend_in, key=lambda k: -pend_in[k]):
            if b in pos or b not in filas or len(pos) >= MAX_POS:
                continue
            r = filas[b]
            if not (r.s_open == r.s_open and r.open == r.open):
                continue
            capital = min(eq / MAX_POS, cash)
            if capital < 100:
                continue
            q = (capital / 2) / r.s_open
            c_in = q * (r.s_open + r.open) * coste
            cash -= capital
            pos[b] = {"capital": capital - c_in, "q": q, "s0": r.s_open, "p0": r.open, "t": t,
                      "funding": 0.0, "c_in": c_in}
        pend_in = {}

        # funding de esta vela y decisiones al cierre
        for b, p in pos.items():
            if b in filas and filas[b].funding == filas[b].funding:
                p["funding"] += p["q"] * filas[b].close * filas[b].funding / 2
        for b, r in filas.items():
            f3 = r.funding_3d
            if b in pos:
                if not (f3 == f3) or f3 < sale or not r.apta:
                    pend_out.add(b)
            elif r.apta and f3 == f3 and f3 > entra:
                pend_in[b] = f3

        eq = cash + sum(valor(p, ultimo[b]) for b, p in pos.items())
        curva.append({"prueba": etiqueta, "t": t, "capital": eq, "posiciones": len(pos)})

    for b, p in pos.items():            # cerrar al final a precio de cierre
        r = ultimo[b]
        base_pnl = p["q"] * (r.s_close - p["s0"]) - p["q"] * (r.close - p["p0"])
        c_out = p["q"] * (r.s_close + r.close) * coste
        cash += p["capital"] + base_pnl + p["funding"] - c_out
        trades.append({"prueba": etiqueta, "moneda": b, "entrada_t": p["t"], "salida_t": r.t,
                       "dias": (r.t - p["t"]).days, "invertido": p["capital"], "funding_usd": p["funding"],
                       "basis_usd": base_pnl, "costes_usd": p["c_in"] + c_out,
                       "resultado_usd": base_pnl + p["funding"] - p["c_in"] - c_out})
    curva[-1]["capital"] = cash
    return pd.DataFrame(trades), pd.DataFrame(curva)


def metricas(tr, cv):
    s = cv.set_index("t")["capital"]
    dia = s.resample("1D").last().dropna()
    r = dia.pct_change().dropna()
    anios = max((dia.index[-1] - dia.index[0]).days / 365.25, 1 / 365)
    m = {"final": s.iloc[-1], "anual": (s.iloc[-1] / CAPITAL) ** (1 / anios) - 1, "dd": (s / s.cummax() - 1).min(),
         "sharpe": r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else 0.0, "n": len(tr),
         "inv": (cv["posiciones"] > 0).mean(), "fund": 0, "basis": 0, "costes": 0, "acierto": 0, "dias": 0,
         "sin_mejor": 0, "mejor": "-"}
    if len(tr):
        pm = tr.groupby("moneda")["resultado_usd"].sum().sort_values()
        m.update({"fund": tr.funding_usd.sum(), "basis": tr.basis_usd.sum(), "costes": tr.costes_usd.sum(),
                  "acierto": (tr.resultado_usd > 0).mean(), "dias": tr.dias.median(),
                  "sin_mejor": tr.resultado_usd.sum() - pm.iloc[-1], "mejor": pm.index[-1]})
    anual, ini = {}, CAPITAL
    for a in sorted(s.index.year.unique()):
        fin = s[s.index.year == a].iloc[-1]
        anual[a] = fin / ini - 1
        ini = fin
    m["por_anio"] = anual
    return m


CAB = (f"{'prueba':<46}{'final':>10}{'anual':>8}{'c.máx':>8}{'Sharpe':>7}{'ops':>5}{'días':>5}{'acierto':>8}"
       f"{'inv.':>6}{'funding':>10}{'basis':>9}{'costes':>9}{'sin mejor':>11}")


def linea(n, m):
    return (f"{n:<46}{m['final']:>9,.0f}${m['anual']*100:>+7.1f}%{m['dd']*100:>+7.1f}%{m['sharpe']:>7.2f}"
            f"{m['n']:>5}{m['dias']:>5.0f}{m['acierto']*100:>7.0f}%{m['inv']*100:>5.0f}%"
            f"{m['fund']:>+10,.0f}{m['basis']:>+9,.0f}{-m['costes']:>+9,.0f}{m['sin_mejor']:>+11,.0f}")


def main():
    P = cargar()
    print(f"Monedas con spot y perpetuo: {P['base'].nunique()}  |  capital {CAPITAL:,.0f} $  |  máx {MAX_POS} posiciones")
    tt, cc = [], []

    print("\n==================== PASO 1 - ENTRENAMIENTO (2020-09 a 2024-12), costes TAKER ====================")
    print(CAB)
    mejor, mejor_s = None, -9
    for nombre, (e, s) in VARIANTES.items():
        tr, cv = simular(P, e, s, COSTES["TAKER"], TRAIN, f"train {nombre}")
        tt.append(tr); cc.append(cv)
        m = metricas(tr, cv)
        print(linea(nombre, m))
        print(f"{'':<46}" + "  ".join(f"{a}: {v*100:+.1f}%" for a, v in m["por_anio"].items()))
        if m["sharpe"] > mejor_s:
            mejor, mejor_s = nombre, m["sharpe"]
    print(f"-> Elegida: {mejor}")

    print(f"\n==================== PASO 2 - COMPROBACIÓN (2025-01 a hoy), una vez ====================")
    print(CAB)
    e, s = VARIANTES[mejor]
    for c_nombre, c in COSTES.items():
        tr, cv = simular(P, e, s, c, TEST, f"test {mejor} {c_nombre}")
        tt.append(tr); cc.append(cv)
        m = metricas(tr, cv)
        print(linea(f"{mejor[:3]} costes {c_nombre}", m))
        print(f"{'':<46}" + "  ".join(f"{a}: {v*100:+.1f}%" for a, v in m["por_anio"].items()))

    pd.concat(tt).to_csv(os.path.join(CARPETA, "carry_operaciones.csv"), index=False)
    pd.concat(cc).to_csv(os.path.join(CARPETA, "carry_curva.csv"), index=False)
    print("\nfunding/basis/costes en $ acumulados.  Referencia sin riesgo: letras/USDC ~4 % anual.")
    print("Guardado: carry_operaciones.csv y carry_curva.csv\n")


if __name__ == "__main__":
    main()
