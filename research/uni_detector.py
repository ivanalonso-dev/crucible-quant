"""
uni_detector.py - Ejecutar CADA DÍA.

  1. Descarga los datos al momento y comprueba qué señales del catálogo
     (senales_validadas.json) están activas en la última vela 4h cerrada.
  2. Da el veredicto del día: señal alcista / bajista / en conflicto / sin ventaja.
  3. Apunta las señales activas en  registro_senales.csv  y evalúa las pasadas
     (¿acertaron a 7 días?) -> así sabes si el sistema funciona en vivo.
  4. Guarda open interest y ratio long/short en  registro_oi.csv
     (Binance solo da 30 días: ejecutándolo a diario se acumula histórico propio).

Uso:  python uni_detector.py
(Antes, al menos una vez:  python uni_investigacion.py)
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import json
import pandas as pd
import uni_datos as ud

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CATALOGO = os.path.join(CARPETA, "senales_validadas.json")
REGISTRO = os.path.join(CARPETA, "registro_senales.csv")
REGISTRO_OI = os.path.join(CARPETA, "registro_oi.csv")


def pct(x):
    return "-" if x is None else f"{x*100:.1f} %"


def guardar_oi():
    try:
        oi = pd.DataFrame(ud._get(ud.FAPI + "/futures/data/openInterestHist",
                                  {"symbol": ud.SIMBOLO, "period": "4h", "limit": 500}))
        ls = pd.DataFrame(ud._get(ud.FAPI + "/futures/data/globalLongShortAccountRatio",
                                  {"symbol": ud.SIMBOLO, "period": "4h", "limit": 500}))
        oi = oi[["timestamp", "sumOpenInterest", "sumOpenInterestValue"]]
        ls = ls[["timestamp", "longShortRatio", "longAccount", "shortAccount"]]
        nuevo = oi.merge(ls, on="timestamp", how="outer")
        nuevo["fecha_utc"] = pd.to_datetime(nuevo["timestamp"].astype("int64"), unit="ms")
        if os.path.exists(REGISTRO_OI):
            viejo = pd.read_csv(REGISTRO_OI)
            nuevo = pd.concat([viejo, nuevo]).drop_duplicates("timestamp", keep="last")
        nuevo = nuevo.sort_values("timestamp")
        nuevo.to_csv(REGISTRO_OI, index=False)
        dias = (nuevo["timestamp"].max() - nuevo["timestamp"].min()) / 86_400_000
        u = nuevo.iloc[-1]
        print(f"\nOpen interest: {float(u['sumOpenInterest']):,.0f} UNI (${float(u['sumOpenInterestValue']):,.0f})  "
              f"|  long/short cuentas: {float(u['longShortRatio']):.2f}")
        print(f"registro_oi.csv: {len(nuevo)} filas, {dias:.0f} días de histórico propio")
    except Exception as e:
        print(f"\n(No se pudo guardar open interest / long-short: {e})")


def main():
    if not os.path.exists(CATALOGO):
        print("No existe senales_validadas.json. Ejecuta primero:  python uni_investigacion.py")
        return
    with open(CATALOGO, encoding="utf-8") as f:
        cat = json.load(f)

    spot, perp, fund = ud.descargar_todo()
    df, umbrales = ud.construir(spot, perp, fund, umbrales=cat["umbrales"])
    sen = ud.senales(df, umbrales)
    unis = ud.universos(df)
    i = df.index[-1]
    u = df.iloc[-1]

    print("\n==================== UNI HOY ====================")
    print(f"Última vela 4h cerrada: {u['t']:%Y-%m-%d %H:%M} UTC  |  cierre {u['close']:.3f}")
    print(f"Escenario rally+corrección: {'SÍ' if u['escenario'] else 'NO'}  "
          f"(rally {u['subida_previa']*100:+.0f} %, desde máximo {u['caida_desde_max']*100:+.1f} %)")
    print(f"Funding 3d: {u['funding_3d']*100:.4f} %  |  basis: {u['basis']*100:+.3f} %  |  "
          f"taker futuros: {u['taker_perp']*100:.1f} %  |  futuros/spot: {u['apalanc']:.1f}x  |  volumen: {u['vol_rel']:.2f}x")
    print(f"Rango 7 días: soporte {u['rango_min']:.3f}  |  resistencia {u['rango_max']:.3f}  "
          f"|  -8 % = {u['close']*(1-ud.X):.3f}  +8 % = {u['close']*(1+ud.X):.3f}")
    print(f"Catálogo: {len(cat['senales'])} señales validadas (generado {cat['generado']})")

    activas = []
    print("\n--- Señales del catálogo ---")
    for s in cat["senales"]:
        activa = bool(unis[s["universo"]].loc[i]) and bool(sen[s["id"]][1].fillna(False).loc[i])
        marca = ">> ACTIVA" if activa else "   inactiva"
        print(f"{marca}  [{s['direccion']:8}] {s['id']:<22} ({s['universo']})  {s['descripcion']}")
        if activa:
            activas.append(s)
            st, b = s["stats"], s["base_universo"]
            print(f"             Histórico: 7d arriba {pct(st['p_7d_arriba'])} (base {pct(b['p_7d_arriba'])}), "
                  f"mediana {st['mediana_7d']*100:+.1f} %, rango habitual {st['p25_7d']*100:+.1f} % a {st['p75_7d']*100:+.1f} %")
            print(f"             Primero -8 %/+8 %: {pct(st['primero_menos8'])} / {pct(st['primero_mas8'])}  |  "
                  f"rompe soporte/resistencia: {pct(st['rompe_soporte'])} / {pct(st['rompe_resistencia'])}  (n={st['n']})")

    alc = [s for s in activas if s["direccion"] == "alcista"]
    baj = [s for s in activas if s["direccion"] == "bajista"]
    print("\n==================== VEREDICTO ====================")
    if not activas:
        print("SIN SEÑAL: hoy no hay ninguna ventaja estadística validada. Lo correcto es no hacer nada.")
    elif alc and baj:
        print(f"CONFLICTO: {len(alc)} alcista(s) y {len(baj)} bajista(s) activas a la vez. Sin ventaja clara.")
    elif alc:
        print(f"SESGO ALCISTA a 7 días: {len(alc)} señal(es) validada(s) activa(s).")
    else:
        print(f"SESGO BAJISTA a 7 días: {len(baj)} señal(es) validada(s) activa(s).")

    # ---- registro de señales en vivo
    filas = [{"t": f"{u['t']:%Y-%m-%d %H:%M}", "id": s["id"], "universo": s["universo"],
              "direccion": s["direccion"], "cierre": float(u["close"])} for s in activas]
    reg = pd.read_csv(REGISTRO) if os.path.exists(REGISTRO) else pd.DataFrame(columns=["t", "id", "universo", "direccion", "cierre"])
    if filas:
        reg = pd.concat([reg, pd.DataFrame(filas)]).drop_duplicates(["t", "id", "universo"], keep="last")
        reg.to_csv(REGISTRO, index=False)

    if len(reg):
        ret7 = df.set_index(df["t"].dt.strftime("%Y-%m-%d %H:%M"))["ret_7d"]
        reg["ret_7d"] = reg["t"].map(ret7)
        cerradas = reg.dropna(subset=["ret_7d"])
        print(f"\n--- Registro en vivo: {len(reg)} señales apuntadas, {len(cerradas)} ya con resultado a 7 días ---")
        if len(cerradas):
            acierto = ((cerradas["direccion"] == "alcista") & (cerradas["ret_7d"] > 0)) | \
                      ((cerradas["direccion"] == "bajista") & (cerradas["ret_7d"] < 0))
            print(f"Aciertos: {acierto.mean()*100:.1f} %  (mediana del movimiento a 7d: {cerradas['ret_7d'].median()*100:+.1f} %)")
            for sid, g in cerradas.assign(ok=acierto).groupby("id"):
                print(f"   {sid:<22} {g['ok'].mean()*100:5.1f} % de {len(g)}")

    guardar_oi()
    print()


if __name__ == "__main__":
    main()