"""
laboratorio_direccion.py - Prueba de UNA VEZ varias ideas para adivinar HACIA DÓNDE va el
movimiento grande que anticipa la alerta de volatilidad.

Casos: alertas de volatilidad (10:10, máx. 1 por moneda cada 7 días) que acabaron en
movimiento grande. Pregunta: ¿tocó primero +8 % (ARRIBA) o -8 % (ABAJO)?
Todo se calcula con datos ANTERIORES a la alerta.

Ideas (cada una predice solo cuando su condición es clara; si no, se abstiene):
  1. squeeze_funding   funding de 3 días en su 20 % más alto -> ABAJO (largos atrapados)
                       en su 20 % más bajo -> ARRIBA (cortos atrapados)
  2. contagio_btc      BTC se ha movido > +3 % en 3 días -> ARRIBA; < -3 % -> ABAJO
  3. contagio_mercado  > 70 % de las monedas en positivo en 3 días -> ARRIBA; < 30 % -> ABAJO
  4. aire_rango        precio en el 10 % superior de su rango de 90 días -> ARRIBA;
                       en el 10 % inferior -> ABAJO
  5. momento_semana    alerta en fin de semana: predice la dirección mayoritaria que tuvieron
                       los fines de semana en ENTRENAMIENTO (aprendida solo con 2020-2024)
  6. modelo_combinado  regresión logística con todas las variables, reentrenada cada año
                       SOLO con los años anteriores (walk-forward). Predice si prob > 55 % o < 45 %.

LISTÓN (fijado antes de ver los datos):
  - acierto >= 55 % con n >= 60
  - intervalo de confianza por encima del 50 %, CORREGIDO por pruebas múltiples
    (6 ideas -> IC al 99,2 % en lugar del 95 %, corrección de Bonferroni)
  - por encima del 50 % en entrenamiento (2020-2024) Y en comprobación (2025-hoy)

Uso:  python laboratorio_direccion.py   (usa cache/)
Guarda: laboratorio_direccion_resultados.txt
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)
import os
import io
import glob
import contextlib
import numpy as np
import pandas as pd

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CACHE = os.path.join(CARPETA, "cache")
CORTE = pd.Timestamp("2025-01-01")
N_IDEAS = 6
ALFA = 0.05 / N_IDEAS
rng = np.random.default_rng(5)


def cargar():
    ficheros = sorted(glob.glob(os.path.join(CACHE, "*.pkl")))
    if not ficheros:
        raise SystemExit("No hay caché: ejecuta antes backtest_senales.py")
    ultimo = max(os.path.basename(f).split("_")[1] for f in ficheros)
    d = {}
    for f in ficheros:
        if os.path.basename(f).split("_")[1] != ultimo:
            continue
        df = pd.read_pickle(f).reset_index(drop=True)
        lr = np.log(df["close"]).diff()
        fund_abs = df["funding_3d"].abs().rolling(2190, min_periods=540).rank(pct=True)
        df["alerta"] = (df["escenario"].astype(bool) | (lr.rolling(42).std() / lr.rolling(540).std() > PRM.VOL_RATIO)
                        | (fund_abs >= PRM.FUND_PCT) | (df["vol_rel"] > PRM.VOLUMEN_REL))
        df["fund_pct"] = df["funding_3d"].rolling(2190, min_periods=540).rank(pct=True)
        df["ret3d"] = df["close"] / df["close"].shift(18) - 1
        df["mom7d"] = df["close"] / df["close"].shift(42) - 1
        hi, lo = df["high"].rolling(540).max(), df["low"].rolling(540).min()
        df["pos_rango"] = (df["close"] - lo) / (hi - lo)
        df["taker24"] = df["tbbav"].rolling(6).sum() / df["volume"].rolling(6).sum()
        df["moneda"] = os.path.basename(f).split("_")[0]
        d[df["moneda"].iloc[0]] = df
    return d


def casos(d):
    P = pd.concat(d.values(), ignore_index=True)
    btc = d["BTC"].set_index("t")["ret3d"].rename("btc3d")
    amplitud = P.groupby("t")["ret3d"].apply(lambda s: (s > 0).mean() if s.notna().sum() >= 10 else np.nan).rename("amplitud")
    out = []
    for mon, df in d.items():
        ult = None
        for r in df[df["t"].dt.hour == 4].itertuples():
            if not r.alerta or r.primero_8 not in ("arriba", "abajo"):
                continue
            if ult is not None and (r.t - ult).days < 7:
                continue
            ult = r.t
            out.append({"moneda": mon, "t": r.t, "arriba": int(r.primero_8 == "arriba"),
                        "fund_pct": r.fund_pct, "ret3d": r.ret3d, "mom7d": r.mom7d, "pos_rango": r.pos_rango,
                        "taker24": r.taker24, "basis": r.basis, "finde": int(r.t.dayofweek >= 5)})
    C = pd.DataFrame(out)
    C = C.join(btc, on="t").join(amplitud, on="t")
    C["anio"] = C["t"].dt.year
    return C


def reglas(C):
    p = {}
    p["1. squeeze_funding"] = np.select([C["fund_pct"] >= 0.8, C["fund_pct"] <= 0.2], [0, 1], -1)
    p["2. contagio_btc"] = np.select([C["btc3d"] > 0.03, C["btc3d"] < -0.03], [1, 0], -1)
    p["3. contagio_mercado"] = np.select([C["amplitud"] > 0.7, C["amplitud"] < 0.3], [1, 0], -1)
    p["4. aire_rango"] = np.select([C["pos_rango"] >= 0.9, C["pos_rango"] <= 0.1], [1, 0], -1)
    tr = C[(C["t"] < CORTE) & (C["finde"] == 1)]
    mayoria = int(tr["arriba"].mean() >= 0.5) if len(tr) else 1
    p["5. momento_semana"] = np.where(C["finde"] == 1, mayoria, -1)

    # 6. modelo combinado walk-forward
    from sklearn.linear_model import LogisticRegression
    X_cols = ["fund_pct", "ret3d", "mom7d", "pos_rango", "taker24", "basis", "finde", "btc3d", "amplitud"]
    pred = np.full(len(C), -1)
    for anio in sorted(C["anio"].unique()):
        tr = C[C["anio"] < anio].dropna(subset=X_cols)
        te_idx = C.index[(C["anio"] == anio) & C[X_cols].notna().all(axis=1)]
        if len(tr) < 200 or len(te_idx) == 0:
            continue
        mu, sd = tr[X_cols].mean(), tr[X_cols].std().replace(0, 1)
        m = LogisticRegression(C=0.5, max_iter=1000).fit((tr[X_cols] - mu) / sd, tr["arriba"])
        pr = m.predict_proba((C.loc[te_idx, X_cols] - mu) / sd)[:, 1]
        pred[te_idx] = np.select([pr > 0.55, pr < 0.45], [1, 0], -1)
    p["6. modelo_combinado"] = pred
    return p, mayoria


def evaluar(C, pred):
    m = pred >= 0
    ok = (pred[m] == C["arriba"].values[m]).astype(float)
    if len(ok) == 0:
        return None
    b = rng.choice(ok, size=(5000, len(ok)), replace=True).mean(axis=1)
    t = C["t"].values[m]
    tr, te = ok[t < np.datetime64(CORTE)], ok[t >= np.datetime64(CORTE)]
    return {"n": len(ok), "acierto": ok.mean(), "lo": np.percentile(b, 100 * ALFA / 2),
            "hi": np.percentile(b, 100 * (1 - ALFA / 2)), "n_tr": len(tr), "tr": tr.mean() if len(tr) else np.nan,
            "n_te": len(te), "te": te.mean() if len(te) else np.nan,
            "cobertura": m.mean()}


def main():
    d = cargar()
    C = casos(d)
    print(f"Casos (alerta + movimiento grande): {len(C)}  |  subieron primero: {C['arriba'].mean()*100:.1f} %")
    print(f"Listón: acierto >= 55 %, n >= 60, IC {100*(1-ALFA):.1f} % > 50 % (Bonferroni, {N_IDEAS} ideas), "
          f"> 50 % en entrenamiento y comprobación\n")
    P, mayoria = reglas(C)
    print(f"{'idea':<22}{'n':>6}{'cobert.':>9}{'acierto':>9}{'IC corregido':>18}{'2020-24':>14}{'2025-hoy':>14}  veredicto")
    for nombre, pred in P.items():
        r = evaluar(C, pred)
        if r is None:
            print(f"{nombre:<22} sin predicciones")
            continue
        ok = r["n"] >= 60 and r["acierto"] >= 0.55 and r["lo"] > 0.5 and r["tr"] > 0.5 and r["te"] > 0.5
        inversa = r["n"] >= 60 and r["hi"] < 0.5
        v = "APROBADA" if ok else ("funciona AL REVÉS (revisar)" if inversa else "no")
        print(f"{nombre:<22}{r['n']:>6}{r['cobertura']*100:>8.0f}%{r['acierto']*100:>8.1f}%"
              f"   [{r['lo']*100:5.1f}, {r['hi']*100:5.1f}]{r['tr']*100:>8.1f}% ({r['n_tr']:>3}){r['te']*100:>8.1f}% ({r['n_te']:>3})  {v}")
    print(f"\n(momento_semana: en entrenamiento los fines de semana fueron mayoritariamente "
          f"{'ARRIBA' if mayoria else 'ABAJO'})")
    print("'cobertura' = % de alertas en las que la idea se atreve a predecir.")


if __name__ == "__main__":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    print(buf.getvalue())
    with open(os.path.join(CARPETA, "laboratorio_direccion_resultados.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Ejecutado: {pd.Timestamp.now():%Y-%m-%d %H:%M}\n\n" + buf.getvalue())
