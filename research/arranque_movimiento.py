"""
arranque_movimiento.py - ¿Se puede detectar el ARRANQUE del movimiento grande por su fuerza?

Idea: no adivinamos la dirección antes. Tras una alerta de volatilidad, vigilamos hora a hora.
Cuando el precio se aleja un 2,5 % del precio de la alerta (hacia cualquier lado), medimos la
FUERZA de ese arranque en esa hora:
  - volumen:      volumen de la hora / volumen horario medio de la semana anterior a la alerta
  - operaciones:  nº de operaciones de la hora / media de la semana anterior
  - velocidad:    cuánto se ha movido el precio en las últimas 3 horas
  - agresividad:  % del volumen que empuja en la dirección del arranque (compras si sube, ventas si baja)
Entramos en la dirección del arranque en la apertura de la hora siguiente:
  - OBJETIVO: que llegue al 8 % desde el precio de la alerta
  - STOP: que vuelva al precio de la alerta (el arranque era falso)
  - Límite: los 7 días de la alerta. Si en una vela se tocan los dos, cuenta el STOP. Costes 0,3 %.

Pregunta: los arranques CON MÁS FUERZA ¿llegan al 8 % más a menudo que los flojos?
Se mide en terciles de "intensidad" (media de los rangos de volumen, operaciones y velocidad).
Los cortes de los terciles se fijan SOLO con 2021-2024.

LISTÓN (fijado antes de ver los datos):
  - El tercio MÁS INTENSO gana dinero (esperanza > 0 con IC 95 % > 0) en 2021-2024 Y en 2025-hoy
  - y gana más que el tercio más flojo en los dos periodos.
REFERENCIA: los mismos arranques sin alerta de volatilidad.

Datos: descarga velas de 1 hora de los futuros de Binance (con nº de operaciones y compras
agresivas) para las monedas de tu cache/ -> cache/1h_<MONEDA>.pkl. Primera vez: 5-10 minutos.
Uso (en tu ordenador):  python arranque_movimiento.py
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import io
import glob
import time
import contextlib
import requests
import numpy as np
import pandas as pd
import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CACHE = os.path.join(CARPETA, "cache")
FAPI = "https://fapi.binance.com/fapi/v1/klines"
INICIO_MS = int(pd.Timestamp("2021-01-01").timestamp() * 1000)
CORTE = pd.Timestamp("2025-01-01")
DISPARO, OBJ, COSTE = 0.025, 0.08, 0.003
rng = np.random.default_rng(8)


# ------------------------------------------------------------------ datos
def bajar_1h(base):
    ruta = os.path.join(CACHE, f"1h_{base}.pkl")
    if os.path.exists(ruta) and time.time() - os.path.getmtime(ruta) < 24 * 3600:
        return pd.read_pickle(ruta)
    for simbolo in (f"{base}USDT", f"1000{base}USDT", f"1000000{base}USDT"):
        filas, inicio = [], INICIO_MS
        try:
            while True:
                r = requests.get(FAPI, params={"symbol": simbolo, "interval": "1h", "startTime": inicio,
                                               "limit": 1500}, timeout=30)
                if r.status_code == 400:
                    raise ValueError("símbolo no existe")
                r.raise_for_status()
                datos = r.json()
                if not datos:
                    break
                filas.extend(datos)
                inicio = int(datos[-1][6]) + 1
                if len(datos) < 1500:
                    break
                time.sleep(0.15)
        except ValueError:
            continue
        if not filas:
            continue
        df = pd.DataFrame(filas).iloc[:, :11]
        df.columns = ["ot", "open", "high", "low", "close", "volume", "ct", "qv", "trades", "tbb", "tbq"]
        for c in ["open", "high", "low", "close", "volume", "trades", "tbb"]:
            df[c] = df[c].astype(float)
        df["t"] = pd.to_datetime(df["ot"].astype("int64"), unit="ms").astype("datetime64[ns]")
        df = df[["t", "open", "high", "low", "close", "volume", "trades", "tbb"]].drop_duplicates("t").reset_index(drop=True)
        df.to_pickle(ruta)
        return df
    return None


def alertas_4h(base):
    f = sorted(glob.glob(os.path.join(CACHE, f"{base}_2*.pkl")))
    if not f:
        return None
    df = pd.read_pickle(f[-1]).reset_index(drop=True)
    lr = np.log(df["close"]).diff()
    fa = df["funding_3d"].abs().rolling(2190, min_periods=540).rank(pct=True)
    df["alerta"] = (df["escenario"].astype(bool) | (lr.rolling(42).std() / lr.rolling(540).std() > PRM.VOL_RATIO)
                    | (fa >= PRM.FUND_PCT) | (df["vol_rel"] > PRM.VOLUMEN_REL))
    return df


# ------------------------------------------------------------------ arranques
def arranques(h1, a4, con_alerta=True):
    """Devuelve una fila por arranque detectado."""
    h1 = h1.set_index("t")
    o, hi, lo, c = h1["open"].values, h1["high"].values, h1["low"].values, h1["close"].values
    v, n, tb = h1["volume"].values, h1["trades"].values, h1["tbb"].values
    idx = h1.index
    out, ult = [], None
    cand = a4[(a4["t"].dt.hour == 4) & (a4["t"] >= pd.Timestamp("2021-01-15"))]
    for r in cand.itertuples():
        if con_alerta and not r.alerta:
            continue
        if ult is not None and (r.t - ult).days < 7:
            continue
        t0 = r.t + pd.Timedelta(hours=4)                 # la alerta se conoce al cierre de la vela 4h
        i0 = idx.searchsorted(t0)
        if i0 < 168 or i0 + 170 >= len(idx):
            continue
        ult = r.t
        P0 = r.close
        vmed, nmed = v[i0 - 168:i0].mean(), n[i0 - 168:i0].mean()
        fin = i0 + 168
        for k in range(i0, fin - 1):
            m = c[k] / P0 - 1
            if abs(m) >= DISPARO:
                s = 1 if m > 0 else -1
                agres = tb[k] / v[k] if v[k] > 0 else 0.5
                fila = {"t": r.t, "lado": s, "horas": k - i0 + 1,
                        "volumen": v[k] / vmed if vmed > 0 else np.nan,
                        "operaciones": n[k] / nmed if nmed > 0 else np.nan,
                        "velocidad": abs(c[k] / c[k - 3] - 1),
                        "agresividad": agres if s > 0 else 1 - agres}
                e = o[k + 1]
                objetivo, stop = P0 * (1 + s * OBJ), P0
                riesgo = abs(e / stop - 1)
                res = None
                for j in range(k + 1, fin):
                    if (s > 0 and lo[j] <= stop) or (s < 0 and hi[j] >= stop):
                        res = s * (stop / e - 1) - COSTE
                        break
                    if (s > 0 and hi[j] >= objetivo) or (s < 0 and lo[j] <= objetivo):
                        res = s * (objetivo / e - 1) - COSTE
                        fila["llega"] = 1
                        break
                if res is None:
                    res = s * (c[fin - 1] / e - 1) - COSTE
                fila.setdefault("llega", 0)
                fila["r"] = res
                fila["R"] = res / max(riesgo, 0.005)
                out.append(fila)
                break
    return pd.DataFrame(out)


# ------------------------------------------------------------------ informe
def stats(E):
    if len(E) < 5:
        return None
    b = rng.choice(E["R"].values, size=(3000, len(E)), replace=True).mean(axis=1)
    return len(E), E["llega"].mean(), E["R"].mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)


def linea(n, E):
    s = stats(E)
    if s is None:
        return f"{n:<34} pocos casos"
    return f"{n:<34}{s[0]:>6}{s[1]*100:>9.1f}%{s[2]:>+9.2f}R   [{s[3]:+.2f}, {s[4]:+.2f}]"


def main(A, A0):
    for X in (A, A0):
        X["intensidad"] = X[["volumen", "operaciones", "velocidad"]].rank(pct=True).mean(axis=1)
    tr = A[A["t"] < CORTE]
    cortes = {c: tr[c].quantile([1 / 3, 2 / 3]).values for c in ["intensidad", "volumen", "operaciones", "velocidad", "agresividad"]}
    print(f"Arranques tras alerta: {len(A)}  |  sin alerta (referencia): {len(A0)}")
    print(f"Disparo: ±{DISPARO*100:.1f} % desde el precio de la alerta | objetivo: {OBJ*100:.0f} % | stop: vuelta al origen\n")
    cab = f"{'grupo':<34}{'n':>6}{'llega 8%':>10}{'esper.':>10}{'IC 95 %':>18}"
    veredicto = {}
    for nombre, (ini, fin) in {"2021-2024": (pd.Timestamp("2000"), CORTE), "2025-hoy": (CORTE, pd.Timestamp("2100"))}.items():
        P = A[(A["t"] >= ini) & (A["t"] < fin)]
        P0 = A0[(A0["t"] >= ini) & (A0["t"] < fin)]
        print(f"==================== {nombre} ====================")
        print(cab)
        print(linea("TODOS los arranques (con alerta)", P))
        print(linea("(ref.) todos, SIN alerta", P0))
        for col in ["intensidad", "volumen", "operaciones", "velocidad", "agresividad"]:
            q1, q2 = cortes[col]
            print(linea(f"  {col}: tercio FLOJO", P[P[col] <= q1]))
            print(linea(f"  {col}: tercio FUERTE", P[P[col] > q2]))
        fuerte, flojo = stats(P[P["intensidad"] > cortes["intensidad"][1]]), stats(P[P["intensidad"] <= cortes["intensidad"][0]])
        veredicto[nombre] = fuerte is not None and flojo is not None and fuerte[3] > 0 and fuerte[2] > flojo[2]
        print()
    ok = all(veredicto.values())
    print("LISTÓN: tercio de intensidad FUERTE con esperanza > 0 (IC > 0) y mejor que el FLOJO, en los dos periodos")
    print("VEREDICTO:", "APROBADO - la fuerza del arranque anticipa la continuación" if ok else "NO APROBADO")


if __name__ == "__main__":
    bases = sorted({os.path.basename(f).split("_")[0] for f in glob.glob(os.path.join(CACHE, "*_2*.pkl"))})
    todos, todos0 = [], []
    for b in bases:
        a4 = alertas_4h(b)
        print(f"{b}: descargando / leyendo velas de 1 hora...", flush=True)
        h1 = bajar_1h(b)
        if h1 is None or a4 is None:
            print("   sin datos, se omite")
            continue
        todos.append(arranques(h1, a4, True).assign(moneda=b))
        todos0.append(arranques(h1, a4, False).assign(moneda=b))
    A, A0 = pd.concat(todos, ignore_index=True), pd.concat(todos0, ignore_index=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(A, A0)
    print("\n" + buf.getvalue())
    A.to_csv(os.path.join(CARPETA, "arranque_operaciones.csv"), index=False)
    with open(os.path.join(CARPETA, "arranque_resultados.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Ejecutado: {pd.Timestamp.now():%Y-%m-%d %H:%M}\n\n" + buf.getvalue())
