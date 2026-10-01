"""
direccion_ruptura.py - SOFTWARE DE DIRECCIÓN (módulo 1): seguir la ruptura.

Trabaja ENCIMA de las alertas de volatilidad (senales_volatilidad.py):
  1. Alerta de volatilidad a las 10:10 (vela que abre 04:00 UTC), máx. 1 por moneda cada 7 días.
  2. Durante los 7 días siguientes se espera la PRIMERA RUPTURA:
       - "rango": cierre por encima del máximo / por debajo del mínimo de los 7 días previos a la alerta
       - "3pct":  cierre un +3 % / -3 % respecto al precio de la alerta
  3. Se entra en la dirección de la ruptura en la APERTURA de la vela siguiente
     (largo si rompe hacia arriba, corto si rompe hacia abajo).
  4. Resultado: carrera entre OBJETIVO +8 % a favor y STOP -4 % en contra durante 7 días
     (si no toca ninguno, se sale a los 7 días). Relación 2:1 -> hace falta acertar > 33 %
     para ganar dinero. Si en una vela se tocan los dos, cuenta el STOP (pesimista).
  5. Filtros de confirmación en la vela de ruptura (flujo de órdenes de futuros):
       - volumen: volumen de la vela >= 2x su media de 30 días
       - taker:   compras agresivas >= 55 % (ruptura alcista) o <= 45 % (bajista)
  Costes: 0,3 % ida y vuelta.

REFERENCIA: las mismas rupturas SIN alerta de volatilidad (¿la alerta aporta algo?).

PROTOCOLO (anti-sobreajuste):
  - Entrenamiento 2020-2024: se prueban 2 rupturas x 4 filtros y se elige la combinación con
    mayor esperanza (en R) con n >= 100.
  - Comprobación 2025-hoy: la elegida, UNA vez. Aprobada si esperanza > 0 con IC 95 % > 0.

Uso:  python direccion_ruptura.py   (usa cache/)
Guarda: direccion_ruptura_resultados.txt y direccion_ruptura_operaciones.csv
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
OBJ, STOP, COSTE = 0.08, 0.04, 0.003
CORTE = pd.Timestamp("2025-01-01")
BOOT = 2000
rng = np.random.default_rng(11)


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
        v7, v90 = lr.rolling(42).std(), lr.rolling(540).std()
        fund_pct = df["funding_3d"].abs().rolling(2190, min_periods=540).rank(pct=True)
        df["alerta"] = (df["escenario"].astype(bool) | (v7 / v90 > PRM.VOL_RATIO) | (fund_pct >= PRM.FUND_PCT) | (df["vol_rel"] > PRM.VOLUMEN_REL))
        df["vol_x"] = df["volume"] / df["volume"].rolling(180).mean()
        df["taker_vela"] = df["tbbav"] / df["volume"]
        df["rmax_prev"] = df["high"].rolling(42).max()
        df["rmin_prev"] = df["low"].rolling(42).min()
        d[os.path.basename(f).split("_")[0]] = df
    return d


def carrera(df, j, lado):
    """Entrada en la apertura de j. Devuelve (resultado neto %, motivo)."""
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    e = o[j]
    for k in range(j, min(j + H, len(df))):
        if lado > 0:
            if l[k] <= e * (1 - STOP):
                return -STOP - COSTE, "stop"
            if h[k] >= e * (1 + OBJ):
                return OBJ - COSTE, "objetivo"
        else:
            if h[k] >= e * (1 + STOP):
                return -STOP - COSTE, "stop"
            if l[k] <= e * (1 - OBJ):
                return OBJ - COSTE, "objetivo"
    k = min(j + H, len(df)) - 1
    return lado * (c[k] / e - 1) - COSTE, "7 días"


def operaciones(d, tipo, con_alerta=True):
    out = []
    for b, df in d.items():
        t, c, a = df["t"], df["close"].values, df["alerta"].fillna(False).values
        hora4 = (t.dt.hour == 4).values
        i, n = 540, len(df)
        while i < n - 2 * H - 2:
            disparo = hora4[i] and (a[i] if con_alerta else True)
            if not disparo:
                i += 1
                continue
            ref, hi, lo = c[i], df["rmax_prev"].values[i], df["rmin_prev"].values[i]
            ruptura = None
            for k in range(i + 1, i + H + 1):
                up = c[k] > hi if tipo == "rango" else c[k] >= ref * 1.03
                dn = c[k] < lo if tipo == "rango" else c[k] <= ref * 0.97
                if up or dn:
                    ruptura = (k, 1 if up else -1)
                    break
            if ruptura:
                k, lado = ruptura
                r, motivo = carrera(df, k + 1, lado)
                out.append({"moneda": b, "t_alerta": t.iloc[i], "t_ruptura": t.iloc[k], "lado": lado,
                            "vol_x": df["vol_x"].values[k], "taker": df["taker_vela"].values[k],
                            "r": r, "motivo": motivo})
            i += H          # siguiente alerta posible a los 7 días
    E = pd.DataFrame(out)
    if len(E):
        E["R"] = E["r"] / STOP
        E["f_volumen"] = E["vol_x"] >= 2
        E["f_taker"] = np.where(E["lado"] > 0, E["taker"] >= 0.55, E["taker"] <= 0.45)
    return E


FILTROS = {"sin filtro": lambda E: E, "volumen": lambda E: E[E["f_volumen"]],
           "taker": lambda E: E[E["f_taker"]], "volumen + taker": lambda E: E[E["f_volumen"] & E["f_taker"]]}


def resumen(E):
    if len(E) == 0:
        return {"n": 0}
    R = E["R"].values
    b = rng.choice(R, size=(BOOT, len(R)), replace=True).mean(axis=1)
    return {"n": len(E), "obj": (E["motivo"] == "objetivo").mean(), "stop": (E["motivo"] == "stop").mean(),
            "ER": R.mean(), "lo": np.percentile(b, 2.5), "hi": np.percentile(b, 97.5),
            "largos": (E["lado"] > 0).mean(),
            "ER_L": E.loc[E["lado"] > 0, "R"].mean(), "ER_C": E.loc[E["lado"] < 0, "R"].mean()}


def fila(nombre, s):
    if s["n"] == 0:
        return f"{nombre:<38} sin operaciones"
    return (f"{nombre:<38}{s['n']:>6}{s['obj']*100:>9.1f}%{s['stop']*100:>7.1f}%{s['ER']:>+8.2f}R"
            f"   [{s['lo']:+.2f}, {s['hi']:+.2f}]{s['ER_L']:>+8.2f}R{s['ER_C']:>+8.2f}R")


CAB = (f"{'prueba':<38}{'ops':>6}{'objetivo':>10}{'stop':>8}{'esper.':>9}{'IC 95 %':>18}{'largos':>9}{'cortos':>9}")


def main():
    d = cargar()
    print(f"Monedas: {len(d)} | objetivo +{OBJ*100:.0f} % vs stop -{STOP*100:.0f} % en 7 días | costes {COSTE*100:.1f} %")
    print("Esperanza en R: +2R si toca objetivo, -1R si toca stop. > 0 = gana dinero. (Azar puro ~ 0R menos costes)\n")
    todas = []

    print("==================== PASO 1 - ENTRENAMIENTO (2020-2024) ====================")
    print(CAB)
    mejor, mejor_er = None, -9
    datos = {}
    for tipo in ["rango", "3pct"]:
        E = operaciones(d, tipo, True)
        datos[tipo] = E
        tr = E[E["t_alerta"] < CORTE]
        for fn, f in FILTROS.items():
            s = resumen(f(tr))
            print(fila(f"alerta + ruptura {tipo} | {fn}", s))
            if s["n"] >= 100 and s["ER"] > mejor_er:
                mejor, mejor_er = (tipo, fn), s["ER"]
    print("\nReferencia: mismas rupturas SIN alerta de volatilidad (entrenamiento):")
    ref = {}
    for tipo in ["rango", "3pct"]:
        R0 = operaciones(d, tipo, False)
        ref[tipo] = R0
        print(fila(f"sin alerta + ruptura {tipo}", resumen(R0[R0["t_alerta"] < CORTE])))
    print(f"\n-> Elegida en entrenamiento: ruptura {mejor[0]} | filtro {mejor[1]}")

    print("\n==================== PASO 2 - COMPROBACIÓN (2025-hoy), una vez ====================")
    print(CAB)
    tipo, fn = mejor
    te = FILTROS[fn](datos[tipo][datos[tipo]["t_alerta"] >= CORTE])
    s = resumen(te)
    print(fila(f"ELEGIDA: ruptura {tipo} | {fn}", s))
    R0 = ref[tipo]
    print(fila(f"(ref.) sin alerta, ruptura {tipo}", resumen(FILTROS[fn](R0[R0["t_alerta"] >= CORTE]))))
    aprobada = s["n"] >= 30 and s["lo"] > 0
    print(f"\nVEREDICTO: {'APROBADA - la ruptura tras una alerta tiene ventaja de dirección' if aprobada else 'NO APROBADA en comprobación'}")

    if s["n"]:
        te = te.assign(anio=te["t_alerta"].dt.year)
        print("\nComprobación por año:  " + "  |  ".join(
            f"{a}: {g['R'].mean():+.2f}R (n={len(g)})" for a, g in te.groupby("anio")))
        print("Por año, TODO el histórico (misma configuración):")
        full = FILTROS[fn](datos[tipo]).assign(anio=lambda x: x["t_alerta"].dt.year)
        print("  " + "  |  ".join(f"{a}: {g['R'].mean():+.2f}R (n={len(g)})" for a, g in full.groupby("anio")))

    for tipo, E in datos.items():
        todas.append(E.assign(ruptura=tipo, con_alerta=True))
    pd.concat(todas).to_csv(os.path.join(CARPETA, "direccion_ruptura_operaciones.csv"), index=False)


if __name__ == "__main__":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    texto = buf.getvalue()
    print(texto)
    with open(os.path.join(CARPETA, "direccion_ruptura_resultados.txt"), "w", encoding="utf-8") as f:
        f.write(f"Ejecutado: {pd.Timestamp.now():%Y-%m-%d %H:%M}\n\n" + texto)
