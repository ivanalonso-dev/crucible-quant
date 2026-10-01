"""
¿Qué suele pasar después de una situación como la actual de UNI?

Situación actual (se detecta sola con los datos):
  - rally fuerte previo (~60 días)
  - corrección moderada desde el máximo de 30 días
Además separa por VOLUMEN (si el volumen se está secando o no).

Para tener muestra suficiente, busca ese mismo escenario en 15 criptos grandes
(UNI sola tiene muy pocos casos) y da:
  - % de veces que la vela de mañana fue verde
  - % de veces que el precio estaba más arriba a 1, 3, 7 y 14 días
  - movimiento típico (mediana y rango habitual)
  - probabilidad de tocar -10 % o +10 % en los 7 días siguientes

Uso:  pip install requests pandas
      python uni_escenario.py
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import params as PRM  # umbrales: privados (parametros.py) o de ejemplo (parametros_ejemplo.py)
import time
import requests
import pandas as pd

URL = "https://data-api.binance.vision/api/v3/klines"   # datos públicos de Binance, sin clave
MONEDAS = ["UNIUSDT", "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
           "DOGEUSDT", "LINKUSDT", "AAVEUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT", "ATOMUSDT", "NEARUSDT"]

SUBIDA_MIN = PRM.RALLY_MIN          # rally previo mínimo (parámetro privado)
CAIDA_MIN, CAIDA_MAX = PRM.CAIDA_MIN, PRM.CAIDA_MAX   # corrección desde el máximo de 30 días
VOL_SECO = 0.7               # volumen 5d / volumen 30d por debajo de esto = volumen secándose


def descargar(simbolo):
    filas, inicio = [], 0
    while True:
        r = requests.get(URL, params={"symbol": simbolo, "interval": "1d",
                                      "startTime": inicio, "limit": 1000}, timeout=30)
        r.raise_for_status()
        datos = r.json()
        if not datos:
            break
        filas.extend(datos)
        inicio = datos[-1][6] + 1
        if len(datos) < 1000:
            break
        time.sleep(0.3)
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "qav", "trades", "tbbav", "tbqav", "ignore"]
    df = pd.DataFrame(filas, columns=cols)[["open_time", "open", "high", "low", "close",
                                             "volume", "close_time"]]
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["fecha"] = pd.to_datetime(df["open_time"], unit="ms").dt.date
    df = df[df["close_time"] < int(time.time() * 1000)]   # fuera la vela de hoy (sin cerrar)
    return df.reset_index(drop=True)


def preparar(df):
    df["verde"] = df["close"] > df["open"]
    df["siguiente_verde"] = df["verde"].shift(-1)
    df["max_30"] = df["high"].rolling(30).max()
    df["min_60"] = df["low"].rolling(60).min()
    df["subida_previa"] = df["max_30"] / df["min_60"] - 1
    df["caida_desde_max"] = df["close"] / df["max_30"] - 1
    df["vol_rel"] = df["volume"].rolling(5).mean() / df["volume"].rolling(30).mean()

    for k in [1, 3, 7, 14]:
        df[f"ret_{k}"] = df["close"].shift(-k) / df["close"] - 1

    # mínimo y máximo de los 7 días siguientes (t+1 .. t+7) respecto al cierre de hoy
    df["min_fut7"] = df["low"][::-1].rolling(7).min()[::-1].shift(-1) / df["close"] - 1
    df["max_fut7"] = df["high"][::-1].rolling(7).max()[::-1].shift(-1) / df["close"] - 1
    return df


def es_escenario(d):
    return (d["subida_previa"] > SUBIDA_MIN) & d["caida_desde_max"].between(CAIDA_MIN, CAIDA_MAX)


def informe(titulo, d):
    d = d.dropna(subset=["ret_1"])
    print(f"\n{titulo}")
    if len(d) == 0:
        print("   sin casos")
        return
    # días consecutivos del mismo episodio cuentan como un solo episodio
    episodios = int((d.groupby("moneda").apply(lambda g: (g.index.to_series().diff() > 5).sum() + 1)).sum())
    print(f"   días que cumplen: {len(d)}  |  episodios distintos: {episodios}"
          + ("   <-- pocos, poco fiable" if episodios < 15 else ""))
    print(f"   Vela de mañana verde:   {d['siguiente_verde'].astype(bool).mean()*100:5.1f} %")
    for k in [1, 3, 7, 14]:
        r = d[f"ret_{k}"].dropna()
        if len(r):
            print(f"   A {k:>2} días más arriba:  {(r > 0).mean()*100:5.1f} %   "
                  f"mediana {r.median()*100:+5.1f} %   rango habitual {r.quantile(.25)*100:+5.1f} % a {r.quantile(.75)*100:+5.1f} %")
    m = d.dropna(subset=["min_fut7", "max_fut7"])
    if len(m):
        print(f"   Toca -10 % en 7 días:   {(m['min_fut7'] < -0.10).mean()*100:5.1f} %")
        print(f"   Toca +10 % en 7 días:   {(m['max_fut7'] > 0.10).mean()*100:5.1f} %")


def main():
    todas = []
    for s in MONEDAS:
        try:
            df = preparar(descargar(s))
            df["moneda"] = s
            todas.append(df)
            print(f"descargado {s}: {len(df)} días")
        except Exception as e:
            print(f"no se pudo {s}: {e}")

    uni = next(df for df in todas if df["moneda"].iloc[0] == "UNIUSDT")
    u = uni.iloc[-1]
    print("\n==================== SITUACIÓN ACTUAL DE UNI ====================")
    print(f"Última vela cerrada: {u['fecha']}  ({'verde' if u['verde'] else 'roja'}, cierre {u['close']:.3f})")
    print(f"Rally previo: {u['subida_previa']*100:+.0f} %   |   Caída desde máximo 30d: {u['caida_desde_max']*100:+.1f} %")
    print(f"Volumen últimos 5 días vs media 30 días: {u['vol_rel']:.2f}x "
          f"({'secándose' if u['vol_rel'] < VOL_SECO else 'normal/alto'})")
    print(f"¿Cumple el escenario? {'SÍ' if bool(es_escenario(uni.iloc[[-1]]).iloc[0]) else 'NO (ajusta los parámetros de arriba)'}")

    total = pd.concat(todas)   # conserva el índice original de cada moneda
    print("\n==================== REFERENCIA: CUALQUIER DÍA ====================")
    informe("Todas las monedas, todos los días (tasa base)", total)

    esc = total[es_escenario(total)]
    print("\n==================== ESCENARIO ACTUAL ====================")
    informe("Todas las monedas - escenario (rally fuerte + corrección)", esc)
    informe("   ...con volumen SECÁNDOSE", esc[esc["vol_rel"] < VOL_SECO])
    informe("   ...con volumen normal/alto", esc[esc["vol_rel"] >= VOL_SECO])
    informe("   ...y además la última vela fue ROJA", esc[~esc["verde"].astype(bool)])
    informe("   ...y además la última vela fue VERDE", esc[esc["verde"].astype(bool)])
    verde = esc["verde"].astype(bool)
    informe(">>> CRUCE: vela VERDE + volumen normal/alto  (= UNI hoy)", esc[verde & (esc["vol_rel"] >= VOL_SECO)])
    informe(">>> CRUCE: vela VERDE + volumen SECÁNDOSE  (si el volumen sigue cayendo)", esc[verde & (esc["vol_rel"] < VOL_SECO)])
    informe("Solo UNI - escenario", esc[esc["moneda"] == "UNIUSDT"])
    print()


if __name__ == "__main__":
    main()