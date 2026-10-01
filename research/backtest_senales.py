"""
backtest_senales.py - SOFTWARE 1: ¿las señales tienen la estadística a favor?

No hay cartera, ni stops, ni tamaños: solo la calidad predictiva de cada señal.
Solo las señales que aprueban pasan al SOFTWARE 2 (backtest_cartera.py).

Método (estándar de "event study"):
  - Cada señal se convierte en EPISODIOS: primera activación y no se cuenta otra en esa
    moneda hasta que pase el horizonte (sin solapamiento -> sin inflar la muestra).
  - Entrada en la APERTURA de la vela siguiente. Costes de ida y vuelta descontados.
  - Se mide el rendimiento a 1, 3, 7 y 14 días y se compara con la BASE: entrar en la
    misma moneda, el mismo año, en cualquier momento (así no cuenta como ventaja que
    el mercado subiera ese año).
  - Rendimiento EN EXCESO = señal - base.  Intervalo de confianza al 95 % por bootstrap.
  - Desglose por año y por moneda, y peso de las 5 mejores operaciones.

Criterios para APROBAR una señal (horizonte principal 7 días):
  1. Exceso medio > 0 con el intervalo de confianza entero por encima de 0.
  2. Exceso mediano > 0 (que no dependa de unos pocos golpes de suerte).
  3. Exceso positivo en al menos el 60 % de los años con datos.
  4. Sigue positivo quitando las 5 mejores operaciones.
  5. Al menos 100 episodios.

Señales probadas:
  - Por umbral (catálogo original): funding alto / negativo, taker, basis, apalancamiento, volumen.
  - Por RANKING entre monedas (no dependen de un umbral fijo): cada vela, las 3 monedas con
    más funding relativo, las 3 con menos, las 3 con más momentum de 7 días y las 3 con menos.

Datos: usa la carpeta cache/ que crea backtest.py (o la descarga si no existe).
Guarda: senales_aprobadas.json  y  backtest_senales_episodios.csv
Uso:  python backtest_senales.py
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import glob
import json
import numpy as np
import pandas as pd
import uni_datos as ud

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CACHE = os.path.join(CARPETA, "cache")
SALIDA = os.path.join(CARPETA, "senales_aprobadas.json")

COSTE = 0.003                    # ida y vuelta: 0,1 % comisión x2 + deslizamiento
HORIZONTES = {"1d": 6, "3d": 18, "7d": 42, "14d": 84}
PRINCIPAL = "7d"
TOP = 3
N_MIN = 100
BOOT = 2000
rng = np.random.default_rng(42)


# ------------------------------------------------------------------ datos
def cargar():
    ficheros = sorted(glob.glob(os.path.join(CACHE, "*.pkl")))
    if ficheros:
        ultimo = max(os.path.basename(f).split("_")[1] for f in ficheros)
        d = {os.path.basename(f).split("_")[0]: pd.read_pickle(f)
             for f in ficheros if os.path.basename(f).split("_")[1] == ultimo}
        print(f"Datos: caché del {ultimo[:-4]} ({len(d)} monedas)")
        return d
    print("No hay caché: descargando el top 30 (5-10 min)...")
    os.makedirs(CACHE, exist_ok=True)
    hoy = pd.Timestamp.now().strftime("%Y%m%d")
    d = {}
    for m in ud.top_monedas(30):
        try:
            spot, perp, fund = ud.descargar_todo(m["spot"], perp_simbolo=m["perp"], factor=m["factor"], silencioso=True)
            df, _ = ud.construir(spot, perp, fund)
            df.to_pickle(os.path.join(CACHE, f"{m['base']}_{hoy}.pkl"))
            d[m["base"]] = df
            print(f"  {m['base']} ok")
        except Exception as e:
            print(f"  {m['base']} descartada: {e}")
    return d


def panel(d):
    filas = []
    for b, df in d.items():
        x = df[["t", "open", "close", "funding_3d", "taker_perp", "basis", "apalanc", "vol_rel"]].copy()
        x["moneda"] = b
        x["mom_7d"] = df["close"] / df["close"].shift(42) - 1
        filas.append(x)
    P = pd.concat(filas, ignore_index=True)
    # rankings entre monedas en cada vela (solo si hay al menos 10 monedas con dato)
    for col, nombre in [("funding_3d", "fund"), ("mom_7d", "mom")]:
        g = P.groupby("t")[col]
        n = g.transform("count")
        P[f"rk_{nombre}_alto"] = (g.rank(ascending=False, method="first") <= TOP) & (n >= 10)
        P[f"rk_{nombre}_bajo"] = (g.rank(ascending=True, method="first") <= TOP) & (n >= 10)
    return P


def definir_senales(P):
    q = lambda c, p: P[P["t"] < ud.CORTE][c].quantile(p)     # umbrales solo con 2020-2024
    return {
        "funding_alto":           P["funding_3d"] > ud.FUNDING_ALTO,
        "funding_negativo":       P["funding_3d"] < 0,
        "taker_perp_comprador":   P["taker_perp"] > q("taker_perp", 2 / 3),
        "taker_perp_vendedor":    P["taker_perp"] < q("taker_perp", 1 / 3),
        "basis_prima":            P["basis"] > q("basis", 0.8),
        "basis_descuento":        P["basis"] < q("basis", 0.2),
        "apalancamiento_alto":    P["apalanc"] > q("apalanc", 0.8),
        "volumen_seco":           P["vol_rel"] < ud.VOL_SECO,
        "ranking_funding_top3":   P["rk_fund_alto"],
        "ranking_funding_bottom3": P["rk_fund_bajo"],
        "ranking_momentum_top3":  P["rk_mom_alto"],
        "ranking_momentum_bottom3": P["rk_mom_bajo"],
    }


# ------------------------------------------------------------------ episodios y base
def episodios(P, mask, h):
    out = []
    for b, g in P.assign(_s=mask.fillna(False).astype(bool).values).groupby("moneda", sort=False):
        s, o, c, t = g["_s"].values, g["open"].values, g["close"].values, g["t"].values
        i, n = 0, len(g)
        while i < n - h - 1:
            if s[i]:
                e = o[i + 1]
                out.append({"moneda": b, "t": pd.Timestamp(t[i]), "r": c[i + h] / e - 1 - COSTE})
                i += h
            else:
                i += 1
    return pd.DataFrame(out)


def bases(P):
    """Rendimiento medio de entrar en cualquier momento: por moneda-año y por horizonte."""
    B = {}
    for k, h in HORIZONTES.items():
        filas = []
        for b, g in P.groupby("moneda", sort=False):
            r = g["close"].shift(-h) / g["open"].shift(-1) - 1 - COSTE
            filas.append(pd.DataFrame({"moneda": b, "anio": g["t"].dt.year, "r": r}))
        x = pd.concat(filas).dropna()
        B[k] = x.groupby(["moneda", "anio"])["r"].agg(["mean", "median"])
    return B


def ic(x):
    if len(x) < 2:
        return (np.nan, np.nan)
    m = rng.choice(x, size=(BOOT, len(x)), replace=True).mean(axis=1)
    return (np.percentile(m, 2.5), np.percentile(m, 97.5))


def evaluar(E, B):
    E = E.copy()
    E["anio"] = E["t"].dt.year
    idx = pd.MultiIndex.from_arrays([E["moneda"], E["anio"]])
    E["base"] = B["mean"].reindex(idx).values
    E["exceso"] = E["r"] - E["base"]
    E = E.dropna(subset=["exceso"])
    return E


def main():
    d = cargar()
    P = panel(d)
    S = definir_senales(P)
    B = bases(P)

    print(f"\nPeriodo: {P['t'].min():%Y-%m-%d} a {P['t'].max():%Y-%m-%d}  |  costes {COSTE*100:.1f} % ida y vuelta")
    print("Exceso = rendimiento de la señal - rendimiento de entrar en cualquier momento (misma moneda y año)\n")

    resumen, aprobadas, todos = [], [], []
    for sid, mask in S.items():
        fila = {"senal": sid}
        for k, h in HORIZONTES.items():
            E = evaluar(episodios(P, mask, h), B[k])
            fila[k] = E["exceso"].mean() if len(E) else np.nan
            if k == PRINCIPAL:
                E7 = E
        E = E7
        if len(E) == 0:
            continue
        ex = E["exceso"].values
        lo, hi = ic(ex)
        por_anio = E.groupby("anio")["exceso"].agg(["mean", "size"])
        anios_ok = (por_anio.loc[por_anio["size"] >= 10, "mean"] > 0)
        sin_top5 = np.sort(ex)[:-5].mean() if len(ex) > 10 else np.nan
        fila.update({
            "n": len(E), "acierto": (E["r"] > 0).mean(), "exc_media": ex.mean(), "exc_mediana": np.median(ex),
            "ic_lo": lo, "ic_hi": hi, "anios_ok": f"{anios_ok.sum()}/{len(anios_ok)}",
            "sin_top5": sin_top5, "por_anio": por_anio,
        })
        criterios = {
            "IC > 0": lo > 0,
            "mediana > 0": np.median(ex) > 0,
            "años >= 60 %": len(anios_ok) > 0 and anios_ok.mean() >= 0.6,
            "sin top5 > 0": sin_top5 > 0,
            f"n >= {N_MIN}": len(E) >= N_MIN,
        }
        # señal "inversa": si todo es negativo, podría servir para cortos
        criterios_corto = {
            "IC < 0": hi < 0, "mediana < 0": np.median(ex) < 0,
            "años >= 60 %": len(anios_ok) > 0 and (1 - anios_ok.mean()) >= 0.6,
            "sin top5 < 0": sin_top5 < 0 if not np.isnan(sin_top5) else False,
            f"n >= {N_MIN}": len(E) >= N_MIN,
        }
        if all(criterios.values()):
            fila["veredicto"], fila["direccion"] = "APROBADA LARGO", "alcista"
        elif all(criterios_corto.values()):
            fila["veredicto"], fila["direccion"] = "APROBADA CORTO", "bajista"
        elif [k for k, v in criterios.items() if not v] == ["mediana > 0"]:
            # decisión documentada: pasa todo menos la mediana (perfil momentum: pocas ganancias
            # grandes, muchas pérdidas pequeñas) -> se prueba en cartera, pero NO cuenta como aprobada
            fila["veredicto"], fila["direccion"] = "CANDIDATA CONDICIONAL (solo falla mediana)", "alcista"
            fila["condicional"] = True
        else:
            falla = [k for k, v in criterios.items() if not v]
            fila["veredicto"], fila["direccion"] = "rechazada (" + ", ".join(falla) + ")", None
        resumen.append(fila)
        todos.append(E.assign(senal=sid))

    print(f"{'señal':<26}{'n':>5}{'acierto':>8}{'exc 1d':>8}{'exc 3d':>8}{'exc 7d':>8}{'exc 14d':>8}"
          f"{'mediana':>8}{'IC 95 % (7d)':>18}{'años+':>7}{'sin top5':>9}  veredicto")
    for f in resumen:
        print(f"{f['senal']:<26}{f['n']:>5}{f['acierto']*100:>7.1f}%"
              + "".join(f"{f[k]*100:>+7.2f}%" for k in HORIZONTES)
              + f"{f['exc_mediana']*100:>+7.2f}%   [{f['ic_lo']*100:+5.2f}, {f['ic_hi']*100:+5.2f}]"
              f"{f['anios_ok']:>7}{f['sin_top5']*100:>+8.2f}%  {f['veredicto']}")

    print("\nExceso medio a 7 días por año (n episodios):")
    anios = sorted(P["t"].dt.year.unique())
    print(f"{'señal':<26}" + "".join(f"{a:>13}" for a in anios))
    for f in resumen:
        pa = f["por_anio"]
        print(f"{f['senal']:<26}" + "".join(
            f"{pa.loc[a,'mean']*100:>+7.1f}% ({int(pa.loc[a,'size']):>3})" if a in pa.index else f"{'-':>13}" for a in anios))

    for f in resumen:
        if f["direccion"]:
            aprobadas.append({"id": f["senal"], "direccion": f["direccion"], "n": int(f["n"]),
                              "estado": "condicional" if f.get("condicional") else "aprobada",
                              "exceso_7d": round(float(f["exc_media"]), 4),
                              "ic_95": [round(float(f["ic_lo"]), 4), round(float(f["ic_hi"]), 4)]})
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump({"generado": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"),
                   "horizonte": PRINCIPAL, "costes": COSTE, "senales": aprobadas}, fh, indent=2, ensure_ascii=False)
    pd.concat(todos).to_csv(os.path.join(CARPETA, "backtest_senales_episodios.csv"), index=False)

    print("\n==================== VEREDICTO ====================")
    if aprobadas:
        for a in aprobadas:
            print(f"  {a['estado'].upper()} [{a['direccion']}] {a['id']}: exceso 7d {a['exceso_7d']*100:+.2f} %, IC {a['ic_95']}")
        print("  -> Estas pasan al backtest de cartera (las condicionales, con cautela).")
    else:
        print("  Ninguna señal tiene la estadística a favor de forma robusta.")
        print("  -> No tiene sentido hacer backtest de cartera: no hay nada que gestionar.")
    print(f"\nGuardado: {os.path.basename(SALIDA)} y backtest_senales_episodios.csv\n")


if __name__ == "__main__":
    main()
