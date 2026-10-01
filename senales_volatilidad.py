"""
senales_volatilidad.py - Señales de MOVIMIENTO GRANDE (sin predecir la dirección).

Pregunta: "¿va a moverse esta moneda un ±8 % o más en los próximos 7 días?"
No dice si sube o baja: dice si viene un movimiento fuerte.

Objetivo medido: tocar +8 % o -8 % (cualquiera de los dos) en las 42 velas de 4h siguientes.

Señales candidatas (calculadas solo con datos disponibles en ese momento):
  - escenario           rally fuerte previo y corrección moderada desde el máximo
  - compresion_vol      volatilidad de 7 días < 0,6x la de 90 días (calma antes de la tormenta)
  - rango_estrecho      rango de 7 días entre el 20 % más estrecho del último año de esa moneda
  - vol_disparada       volatilidad de 7 días muy por encima de la de 90 días (la volatilidad se agrupa)
  - funding_extremo     funding de 3 días en la cola más extrema del último año (positivo o negativo)
  - volumen_explosivo   volumen de 5 días muy por encima de la media de 30
  - volumen_seco        volumen de 5 días < 0,7x la media de 30

Método (igual de estricto que backtest_senales.py):
  - Episodios sin solapamiento (una medición cada 7 días como mucho por moneda).
  - BASE = probabilidad de movimiento grande en esa misma moneda y año, en cualquier momento.
  - VENTAJA = probabilidad con señal - base.  Intervalo de confianza al 95 % por bootstrap.
  - APROBADA si: IC entero > 0, ventaja positiva en >= 60 % de los años, n >= 100.
  - Además se prueban COMBINACIONES de dos señales aprobadas.

Salida: tabla de validación + FOTO DE HOY: qué monedas tienen señales de movimiento activas
y la probabilidad histórica de movimiento grande en esas condiciones.
Guarda: senales_volatilidad.json
Uso:  python senales_volatilidad.py   (usa la carpeta cache/)
"""

import os
import glob
import json
import itertools
import numpy as np
import pandas as pd
import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)

CARPETA = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(CARPETA, "cache")
H = 42
X = 0.08
N_MIN = 100
BOOT = 2000
rng = np.random.default_rng(7)


def cargar():
    ficheros = sorted(glob.glob(os.path.join(CACHE, "*.pkl")))
    if not ficheros:
        raise SystemExit("No hay caché: ejecuta antes backtest_senales.py o backtest.py")
    ultimo = max(os.path.basename(f).split("_")[1] for f in ficheros)
    filas = []
    for f in ficheros:
        if os.path.basename(f).split("_")[1] != ultimo:
            continue
        df = pd.read_pickle(f)
        x = df[["t", "high", "low", "close", "funding_3d", "vol_rel", "escenario", "primero_8"]].copy()
        x["moneda"] = os.path.basename(f).split("_")[0]
        lr = np.log(x["close"]).diff()
        x["vol7"] = lr.rolling(42).std()
        x["vol90"] = lr.rolling(540).std()
        rango = (x["high"].rolling(42).max() - x["low"].rolling(42).min()) / x["close"]
        x["rango_pct"] = rango.rolling(2190, min_periods=540).rank(pct=True)
        fa = x["funding_3d"].abs()
        x["fund_pct"] = fa.rolling(2190, min_periods=540).rank(pct=True)
        x["grande"] = x["primero_8"].isin(["arriba", "abajo", "ambos"]).astype(float)
        x.loc[x["primero_8"].isna(), "grande"] = np.nan
        filas.append(x)
    return pd.concat(filas, ignore_index=True)


def senales(P):
    return {
        "escenario": P["escenario"].astype(bool),
        "compresion_vol": (P["vol7"] / P["vol90"]) < 0.6,
        "rango_estrecho": P["rango_pct"] <= 0.2,
        "vol_disparada": (P["vol7"] / P["vol90"]) > PRM.VOL_RATIO,
        "funding_extremo": P["fund_pct"] >= PRM.FUND_PCT,
        "volumen_explosivo": P["vol_rel"] > PRM.VOLUMEN_REL,
        "volumen_seco": P["vol_rel"] < 0.7,
    }


def episodios(P, mask):
    out = []
    for b, g in P.assign(_s=mask.fillna(False).astype(bool).values).groupby("moneda", sort=False):
        s, y, t = g["_s"].values, g["grande"].values, g["t"].values
        i = 0
        while i < len(g):
            if s[i] and y[i] == y[i]:
                out.append({"moneda": b, "t": pd.Timestamp(t[i]), "grande": y[i]})
                i += H
            else:
                i += 1
    return pd.DataFrame(out)


def evaluar(P, mask, base):
    E = episodios(P, mask)
    if len(E) == 0:
        return None
    E["anio"] = E["t"].dt.year
    E["base"] = base.reindex(pd.MultiIndex.from_arrays([E["moneda"], E["anio"]])).values
    E = E.dropna(subset=["base"])
    v = (E["grande"] - E["base"]).values
    boot = rng.choice(v, size=(BOOT, len(v)), replace=True).mean(axis=1)
    pa = E.assign(v=v).groupby("anio")["v"].agg(["mean", "size"])
    pa_ok = pa.loc[pa["size"] >= 10, "mean"] > 0
    return {"n": len(E), "p": E["grande"].mean(), "base": E["base"].mean(), "ventaja": v.mean(),
            "lo": np.percentile(boot, 2.5), "hi": np.percentile(boot, 97.5),
            "anios": f"{int(pa_ok.sum())}/{len(pa_ok)}", "anios_ok": pa_ok.mean() if len(pa_ok) else 0,
            "por_anio": pa}


def main():
    P = cargar()
    base = P.dropna(subset=["grande"]).groupby(["moneda", P["t"].dt.year])["grande"].mean()
    base.index.names = [None, None]
    S = senales(P)
    print(f"Objetivo: tocar +{X*100:.0f} % o -{X*100:.0f} % en 7 días  |  {P['moneda'].nunique()} monedas  |  "
          f"probabilidad base media: {P['grande'].mean()*100:.1f} %\n")
    cab = f"{'señal':<40}{'n':>6}{'prob.':>8}{'base':>8}{'ventaja':>9}{'IC 95 %':>18}{'años+':>7}  veredicto"
    print(cab)

    res, aprobadas = {}, []

    def mostrar(nombre, r):
        ok = r["lo"] > 0 and r["anios_ok"] >= 0.6 and r["n"] >= N_MIN
        print(f"{nombre:<40}{r['n']:>6}{r['p']*100:>7.1f}%{r['base']*100:>7.1f}%{r['ventaja']*100:>+8.1f}p"
              f"   [{r['lo']*100:+5.1f}, {r['hi']*100:+5.1f}]{r['anios']:>7}  {'APROBADA' if ok else 'rechazada'}")
        return ok

    for sid, m in S.items():
        r = evaluar(P, m, base)
        if r is None:
            continue
        res[sid] = r
        if mostrar(sid, r):
            aprobadas.append(sid)

    combos = {}
    if len(aprobadas) >= 2:
        print("\nCombinaciones de señales aprobadas:")
        for a, b in itertools.combinations(aprobadas, 2):
            r = evaluar(P, S[a] & S[b], base)
            if r is None:
                continue
            nombre = f"{a} + {b}"
            res[nombre] = r
            if mostrar(nombre, r):
                combos[nombre] = (a, b)

    catalogo = [{"id": k, "prob": round(float(res[k]["p"]), 4), "base": round(float(res[k]["base"]), 4),
                 "ventaja": round(float(res[k]["ventaja"]), 4), "n": int(res[k]["n"])}
                for k in aprobadas + list(combos)]
    with open(os.path.join(CARPETA, "senales_volatilidad.json"), "w", encoding="utf-8") as f:
        json.dump({"objetivo": f"tocar +/-{X*100:.0f}% en 7 dias", "senales": catalogo}, f, indent=2, ensure_ascii=False)

    # ---------------- foto de hoy
    ult = P.sort_values("t").groupby("moneda").tail(1).set_index("moneda")
    print(f"\n==================== HOY (última vela {P['t'].max():%Y-%m-%d %H:%M} UTC) ====================")
    print(f"{'moneda':<8}{'precio':>12}{'base moneda':>13}{'prob. hoy':>11}   señales de movimiento activas")
    filas = []
    for mon, r in ult.iterrows():
        idx = P.index[(P["moneda"] == mon) & (P["t"] == r["t"])][0]
        activas = [k for k in aprobadas if bool(S[k].fillna(False).loc[idx])]
        activas += [k for k, (a, b) in combos.items() if bool(S[a].fillna(False).loc[idx]) and bool(S[b].fillna(False).loc[idx])]
        bm = base.get((mon, r["t"].year), np.nan)
        # probabilidad para ESTA moneda = su base + la ventaja de la señal activa más fuerte
        vent = max([res[k]["ventaja"] for k in activas], default=np.nan)
        prob = min(bm + vent, 0.99) if vent == vent and bm == bm else np.nan
        filas.append((mon, r["close"], bm, prob, activas))
    filas.sort(key=lambda x: -((x[3] - x[2]) if x[3] == x[3] else -1))
    for mon, precio, bm, prob, activas in filas:
        p = f"{prob*100:>9.0f}%" if prob == prob else f"{'-':>10}"
        print(f"{mon:<8}{precio:>12.6g}{bm*100:>12.0f}%{p}   {', '.join(activas) if activas else ''}")
    print("\n'prob. hoy' = base de la moneda + ventaja de su señal activa más fuerte (tocar +/-8 % en 7 días).")
    print("No indica dirección. Guardado: senales_volatilidad.json\n")


if __name__ == "__main__":
    main()
