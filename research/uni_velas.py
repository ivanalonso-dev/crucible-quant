"""
Estadística de la siguiente vela diaria para UNI (o cualquier par de Binance).
Descarga todo el histórico diario y calcula qué % de veces la vela siguiente
fue verde o roja según distintas situaciones.

Uso:  python uni_velas.py
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)
import time
import requests
import pandas as pd

SIMBOLO = "UNIUSDT"   # cámbialo por BTCUSDT, ETHUSDT, etc.
URL = "https://data-api.binance.vision/api/v3/klines"  # datos públicos de Binance, sin clave


def descargar_diario(simbolo):
    filas = []
    inicio = 0
    while True:
        r = requests.get(
            URL,
            params={"symbol": simbolo, "interval": "1d", "startTime": inicio, "limit": 1000},
            timeout=30,
        )
        r.raise_for_status()
        datos = r.json()
        if not datos:
            break
        filas.extend(datos)
        inicio = datos[-1][6] + 1          # siguiente tras el close_time de la última vela
        if len(datos) < 1000:
            break
        time.sleep(0.3)

    columnas = ["open_time", "open", "high", "low", "close", "volume", "close_time",
                "qav", "trades", "tbbav", "tbqav", "ignore"]
    df = pd.DataFrame(filas, columns=columnas)
    df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["fecha"] = pd.to_datetime(df["open_time"], unit="ms").dt.date

    ahora_ms = int(time.time() * 1000)
    df = df[df["close_time"] < ahora_ms]   # quitamos la vela de hoy, que aún no ha cerrado
    return df.reset_index(drop=True)


def resultado(serie):
    n = len(serie)
    if n == 0:
        return "sin casos"
    verde = serie.mean() * 100
    aviso = "   <-- pocos casos, poco fiable" if n < 30 else ""
    return f"{verde:5.1f} % verde | {100 - verde:5.1f} % roja   (n={n}){aviso}"


def main():
    df = descargar_diario(SIMBOLO)
    print(f"\n{SIMBOLO}: {len(df)} velas diarias cerradas, del {df['fecha'].iloc[0]} al {df['fecha'].iloc[-1]}\n")

    # --- Variables ---
    df["verde"] = df["close"] > df["open"]
    df["cambio"] = df["close"] / df["open"] - 1
    df["siguiente_verde"] = df["verde"].shift(-1)

    racha, rachas = 0, []
    for v in df["verde"]:
        racha = 0 if v else racha + 1
        rachas.append(racha)
    df["rojas_seguidas"] = rachas

    df["max_30"] = df["high"].rolling(30).max()
    df["min_60"] = df["low"].rolling(60).min()
    df["subida_previa"] = df["max_30"] / df["min_60"] - 1          # tamaño del rally reciente
    df["caida_desde_max"] = df["close"] / df["max_30"] - 1          # cuánto ha corregido desde el techo

    # Solo filas donde ya conocemos la vela siguiente
    d = df.iloc[:-1].copy()
    d["siguiente_verde"] = d["siguiente_verde"].astype(bool)
    sig = d["siguiente_verde"]

    # --- Resultados ---
    print("1) Tasa base (cualquier día)")
    print("   ", resultado(sig))

    print("\n2) Según el color de la vela anterior")
    print("   Tras vela verde:        ", resultado(sig[d["verde"]]))
    print("   Tras vela roja:         ", resultado(sig[~d["verde"]]))

    print("\n3) Tras rachas de velas rojas")
    for k in [2, 3, 4]:
        print(f"   Tras {k}+ rojas seguidas:", resultado(sig[d["rojas_seguidas"] >= k]))

    print("\n4) Tras una vela roja fuerte")
    for x in [0.03, 0.05, 0.08]:
        print(f"   Tras roja de más de {x*100:.0f} %:", resultado(sig[d["cambio"] < -x]))

    print("\n5) Escenario parecido al actual")
    print("   (rally fuerte previo, corrección desde el máximo, vela roja)")
    escenario = (
        (d["subida_previa"] > 1.0)
        & (d["caida_desde_max"].between(PRM.CAIDA_MIN, -0.10))
        & (~d["verde"])
    )
    print("   ", resultado(sig[escenario]))

    # --- Situación de la última vela cerrada ---
    u = df.iloc[-1]
    print("\nÚltima vela cerrada:", u["fecha"])
    print(f"   Color: {'verde' if u['verde'] else 'roja'}  ({u['cambio']*100:+.2f} %)")
    print(f"   Rojas seguidas: {u['rojas_seguidas']}")
    print(f"   Subida previa: {u['subida_previa']*100:+.0f} %   Caída desde máximo 30d: {u['caida_desde_max']*100:+.1f} %")
    print()


if __name__ == "__main__":
    main()