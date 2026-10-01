"""
direccion_onchain.py - SOFTWARE DE DIRECCIÓN (módulo 3): ¿los flujos on-chain anticipan
hacia dónde va el movimiento grande que predice la alerta de volatilidad?

Entrada: flujos_cex_4h.csv (de bigquery_flujos_2020.sql o dune_flujos_2020.sql)
         + la carpeta cache/ (precios y alertas).

Método:
  1. Alertas de volatilidad (las mismas de senales_volatilidad.py), a las 10:10,
     máx. 1 por moneda cada 7 días.
  2. En el momento de la alerta, con datos ANTERIORES a ella:
       - neto_z:    flujo neto a exchanges de las últimas 24h, normalizado (z-score frente
                    a los 90 días previos de esa moneda)
       - ballena:   el mayor depósito de las últimas 24h está en el 1 % más grande de su historia
  3. Predicción de dirección:
       neto_z >= +1,5  o  ballena   -> BAJISTA (entra oferta en los exchanges)
       neto_z <= -1,5                 -> ALCISTA (sale oferta de los exchanges)
       resto                          -> sin predicción
  4. Se comprueba contra lo que pasó: qué tocó primero, +8 % o -8 %.

LISTÓN (fijado ANTES de ver los datos):
  - Acierto de dirección >= 55 %
  - Intervalo de confianza al 95 % por encima del 50 %
  - Por encima del 50 % tanto en 2020-2024 como en 2025-2026
  - Al menos 60 predicciones

Uso:  python direccion_onchain.py
Guarda: direccion_onchain_resultados.txt
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import io
import glob
import contextlib
import numpy as np
import pandas as pd
import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CACHE = os.path.join(CARPETA, "cache")
FLUJOS = os.path.join(CARPETA, "flujos_cex_4h.csv")
CORTE = pd.Timestamp("2025-01-01")
Z = 1.5
TOKENS = {
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": "UNI",
    "0x514910771af9ca656af840dff83e8264ecf986ca": "LINK",
    "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": "AAVE",
    "0xfaba6f8e4a5e8ab82f62fe7c39859fa577269be3": "ONDO",
    "0x57e114b691db790c35207b2e685d4a43181e6061": "ENA",
    "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce": "SHIB",
}
rng = np.random.default_rng(3)


def cargar_flujos():
    if not os.path.exists(FLUJOS):
        raise SystemExit("Falta flujos_cex_4h.csv: ejecuta antes la query de BigQuery o de Dune.")
    f = pd.read_csv(FLUJOS)
    f["token_address"] = f["token_address"].astype(str).str.lower()
    f["moneda"] = f["token_address"].map(TOKENS)
    f = f.dropna(subset=["moneda"])
    f["t"] = pd.to_datetime(f["t4h"], utc=True).dt.tz_localize(None).astype("datetime64[ns]")
    return f


def preparar(f):
    salida = {}
    for mon, g in f.groupby("moneda"):
        ruta = sorted(glob.glob(os.path.join(CACHE, f"{mon}_*.pkl")))
        if not ruta:
            continue
        df = pd.read_pickle(ruta[-1]).reset_index(drop=True)
        g = g.set_index("t")[["neto_cex", "mayor_deposito"]]
        df = df.merge(g, left_on="t", right_index=True, how="left")
        df[["neto_cex", "mayor_deposito"]] = df[["neto_cex", "mayor_deposito"]].fillna(0)
        n24 = df["neto_cex"].rolling(6).sum()
        df["neto_z"] = (n24 - n24.rolling(540).mean()) / n24.rolling(540).std()
        dep24 = df["mayor_deposito"].rolling(6).max()
        df["ballena"] = dep24 >= df["mayor_deposito"].expanding(180).quantile(0.99).shift(6)
        lr = np.log(df["close"]).diff()
        fund_pct = df["funding_3d"].abs().rolling(2190, min_periods=540).rank(pct=True)
        df["alerta"] = (df["escenario"].astype(bool) | (lr.rolling(42).std() / lr.rolling(540).std() > PRM.VOL_RATIO)
                        | (fund_pct >= PRM.FUND_PCT) | (df["vol_rel"] > PRM.VOLUMEN_REL))
        salida[mon] = df
    return salida


def alertas(d):
    out = []
    for mon, df in d.items():
        ult = None
        for r in df[df["t"].dt.hour == 4].itertuples():
            if not r.alerta or r.primero_8 not in ("arriba", "abajo"):
                continue
            if ult is not None and (r.t - ult).days < 7:
                continue
            ult = r.t
            pred = "abajo" if (r.neto_z >= Z or r.ballena) else ("arriba" if r.neto_z <= -Z else None)
            out.append({"moneda": mon, "t": r.t, "real": r.primero_8, "pred": pred,
                        "neto_z": r.neto_z, "ballena": bool(r.ballena)})
    return pd.DataFrame(out)


def acierto(E):
    x = (E["pred"] == E["real"]).astype(float).values
    if len(x) == 0:
        return np.nan, np.nan, np.nan, 0
    b = rng.choice(x, size=(2000, len(x)), replace=True).mean(axis=1)
    return x.mean(), np.percentile(b, 2.5), np.percentile(b, 97.5), len(x)


def main():
    d = preparar(cargar_flujos())
    A = alertas(d)
    print(f"Monedas con flujos y precios: {', '.join(d)}")
    print(f"Alertas con movimiento grande: {len(A)}  |  con predicción on-chain: {A['pred'].notna().sum()}\n")
    P = A.dropna(subset=["pred"])

    print(f"{'grupo':<36}{'n':>5}{'acierto':>9}{'IC 95 %':>18}")
    filas = [("TODAS las predicciones", P),
             ("  2020-2024", P[P["t"] < CORTE]), ("  2025-2026", P[P["t"] >= CORTE]),
             ("  predicción BAJISTA", P[P["pred"] == "abajo"]), ("  predicción ALCISTA", P[P["pred"] == "arriba"]),
             ("  solo depósitos de ballena", P[P["ballena"]])]
    res = {}
    for n, g in filas:
        a, lo, hi, k = acierto(g)
        res[n] = (a, lo, hi, k)
        print(f"{n:<36}{k:>5}" + (f"{a*100:>8.1f}%   [{lo*100:5.1f}, {hi*100:5.1f}]" if k else "   sin casos"))
    print("\nPor moneda:")
    for mon, g in P.groupby("moneda"):
        a, lo, hi, k = acierto(g)
        print(f"  {mon:<8}{k:>5}{a*100:>8.1f}%")
    ref = (A["real"] == "abajo").mean()
    print(f"\nReferencia: el {ref*100:.1f} % de los movimientos grandes con alerta fueron bajistas.")

    a, lo, _, k = res["TODAS las predicciones"]
    tr, te = res["  2020-2024"][0], res["  2025-2026"][0]
    ok = k >= 60 and a >= 0.55 and lo > 0.5 and tr > 0.5 and te > 0.5
    print("\nLISTÓN: acierto >= 55 %, IC > 50 %, > 50 % en ambos periodos, n >= 60")
    print("VEREDICTO:", "APROBADO - los flujos on-chain anticipan la dirección" if ok else "NO APROBADO")


if __name__ == "__main__":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    print(buf.getvalue())
    with open(os.path.join(CARPETA, "direccion_onchain_resultados.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Ejecutado: {pd.Timestamp.now():%Y-%m-%d %H:%M}\n\n" + buf.getvalue())
