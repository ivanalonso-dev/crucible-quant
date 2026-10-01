"""
horquilla_ordenes.py - "Straddle" con órdenes en futuros: horquilla de dos lados con SL y TP.

Al saltar una alerta de volatilidad (10:10, máx. 1 por moneda cada 7 días), se colocan
DE ANTEMANO dos órdenes independientes sobre el precio de la alerta (P):
  - COMPRA stop en P x (1 + E)   ->  SL en P (vuelve al origen)   ->  TP en entrada x (1 + T)
  - VENTA  stop en P x (1 - E)   ->  SL en P                      ->  TP en entrada x (1 - T)
Las dos órdenes siguen vivas a la vez durante 7 días: si un lado salta por stop, el otro
puede activarse después. Lo que siga abierto a los 7 días se cierra a mercado.
Si en una vela se tocan SL y TP de un lado, cuenta el SL (pesimista).
Costes: 0,15 % por orden ejecutada (comisión + deslizamiento), es decir 0,3 % por lado operado.

Parámetros fijados de antemano (E = distancia de activación, T = objetivo):
  A: E = 3 %, T = 8 %     B: E = 2 %, T = 8 %     C: E = 3 %, T = 12 %
Protocolo: se elige en 2020-2024 la de mayor resultado medio; se comprueba UNA vez en 2025-hoy.
REFERENCIA: la misma horquilla SIN alerta (¿la alerta aporta algo?).

Resultado medido por alerta, en % del importe de UN lado (si opera los dos, se suman).
Uso:  python horquilla_ordenes.py   (usa cache/)
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
H = 42
COSTE = 0.0015
CORTE = pd.Timestamp("2025-01-01")
VARIANTES = {"A: activa ±3 %, TP 8 %": (0.03, 0.08), "B: activa ±2 %, TP 8 %": (0.02, 0.08),
             "C: activa ±3 %, TP 12 %": (0.03, 0.12)}
rng = np.random.default_rng(9)


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
        fa = df["funding_3d"].abs().rolling(2190, min_periods=540).rank(pct=True)
        df["alerta"] = (df["escenario"].astype(bool) | (lr.rolling(42).std() / lr.rolling(540).std() > PRM.VOL_RATIO)
                        | (fa >= PRM.FUND_PCT) | (df["vol_rel"] > PRM.VOLUMEN_REL))
        d[os.path.basename(f).split("_")[0]] = df
    return d


def lado(h, l, c, i, P, E, T, s):
    """Un lado de la horquilla desde la vela i+1. s=+1 compra, -1 venta. Devuelve (resultado, operado)."""
    act = P * (1 + s * E)
    entrada = None
    for k in range(i + 1, i + H + 1):
        if entrada is None:
            if (s > 0 and h[k] >= act) or (s < 0 and l[k] <= act):
                entrada, sl, tp = act, P, act * (1 + s * T)
                # misma vela: ¿toca también el SL o el TP tras activarse? (pesimista: SL primero)
                if (s > 0 and l[k] <= sl) or (s < 0 and h[k] >= sl):
                    return s * (sl / entrada - 1) - 2 * COSTE, True
                if (s > 0 and h[k] >= tp) or (s < 0 and l[k] <= tp):
                    return T - 2 * COSTE, True
            continue
        if (s > 0 and l[k] <= sl) or (s < 0 and h[k] >= sl):
            return s * (sl / entrada - 1) - 2 * COSTE, True
        if (s > 0 and h[k] >= tp) or (s < 0 and l[k] <= tp):
            return T - 2 * COSTE, True
    if entrada is None:
        return 0.0, False
    return s * (c[i + H] / entrada - 1) - 2 * COSTE, True


def simular(d, E, T, con_alerta=True):
    out = []
    for mon, df in d.items():
        h, l, c, a = df["high"].values, df["low"].values, df["close"].values, df["alerta"].fillna(False).values
        hora4 = (df["t"].dt.hour == 4).values
        i = 540
        while i < len(df) - H - 1:
            if hora4[i] and (a[i] if con_alerta else True):
                P = c[i]
                rc, oc = lado(h, l, c, i, P, E, T, +1)
                rv, ov = lado(h, l, c, i, P, E, T, -1)
                out.append({"moneda": mon, "t": df["t"].iloc[i], "r": rc + rv, "lados": int(oc) + int(ov),
                            "ganadora": (rc + rv) > 0})
                i += H
            else:
                i += 1
    return pd.DataFrame(out)


def fila(n, E):
    if len(E) == 0:
        return f"{n:<40} sin casos"
    b = rng.choice(E["r"].values, size=(3000, len(E)), replace=True).mean(axis=1)
    return (f"{n:<40}{len(E):>6}{E['ganadora'].mean()*100:>9.1f}%{E['r'].mean()*100:>+9.2f}%"
            f"   [{np.percentile(b, 2.5)*100:+5.2f}, {np.percentile(b, 97.5)*100:+5.2f}]"
            f"{(E['lados'] == 2).mean()*100:>9.0f}%{(E['lados'] == 0).mean()*100:>9.0f}%")


CAB = f"{'prueba':<40}{'alertas':>6}{'ganadoras':>10}{'medio':>9}{'IC 95 %':>20}{'2 lados':>9}{'ninguno':>9}"


def main():
    d = cargar()
    print("Resultado medio por alerta en % del importe de un lado. '2 lados' = se activaron las dos órdenes.\n")
    print("==================== ENTRENAMIENTO (2020-2024) ====================")
    print(CAB)
    datos, mejor, mejor_r = {}, None, -9
    for n, (E, T) in VARIANTES.items():
        X = simular(d, E, T)
        datos[n] = X
        tr = X[X["t"] < CORTE]
        print(fila(n, tr))
        if tr["r"].mean() > mejor_r:
            mejor, mejor_r = n, tr["r"].mean()
    E, T = VARIANTES[mejor]
    R0 = simular(d, E, T, con_alerta=False)
    print(fila(f"(ref.) {mejor[:2]} SIN alerta", R0[R0["t"] < CORTE]))
    print(f"-> Elegida: {mejor}")

    print("\n==================== COMPROBACIÓN (2025-hoy), una vez ====================")
    print(CAB)
    te = datos[mejor][datos[mejor]["t"] >= CORTE]
    print(fila(f"ELEGIDA {mejor}", te))
    print(fila(f"(ref.) {mejor[:2]} SIN alerta", R0[R0["t"] >= CORTE]))
    b = rng.choice(te["r"].values, size=(3000, len(te)), replace=True).mean(axis=1)
    ok = len(te) >= 60 and np.percentile(b, 2.5) > 0
    print("\nVEREDICTO:", "APROBADA - la horquilla gana tras las alertas" if ok else "NO APROBADA")
    todo = datos[mejor].assign(anio=lambda x: x["t"].dt.year)
    print("Por año (elegida): " + "  |  ".join(f"{a}: {g['r'].mean()*100:+.2f}% (n={len(g)})"
                                               for a, g in todo.groupby("anio")))


if __name__ == "__main__":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    print(buf.getvalue())
    with open(os.path.join(CARPETA, "horquilla_ordenes_resultados.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Ejecutado: {pd.Timestamp.now():%Y-%m-%d %H:%M}\n\n" + buf.getvalue())
