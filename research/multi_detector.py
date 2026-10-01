"""
multi_detector.py - Ejecutar CADA DÍA.  Revisa las ~30 criptos del catálogo y avisa
solo de las que tienen una señal validada activa.

  1. Descarga los últimos ~150 días de cada moneda (rápido: ~1 minuto en total).
  2. Comprueba las señales de senales_multi.json en la última vela 4h cerrada.
  3. Lista las oportunidades, ordenadas por lo bien que ha funcionado la señal EN ESA MONEDA.
  4. Apunta cada activación en  registro_multi.csv  y evalúa las pasadas a 7 días.
  5. Guarda open interest y long/short de todas en  registro_oi_multi.csv.

Uso:  python multi_detector.py
(Antes, al menos una vez:  python multi_investigacion.py)
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import json
import time
import pandas as pd
import uni_datos as ud

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CATALOGO = os.path.join(CARPETA, "senales_multi.json")
REGISTRO = os.path.join(CARPETA, "registro_multi.csv")
REGISTRO_OI = os.path.join(CARPETA, "registro_oi_multi.csv")
DIAS = 150
# calidad de una activación según la historia PROPIA de la moneda con esa señal
CALIDAD_EFECTO = 0.03   # +3 puntos o más en esa moneda
CALIDAD_N = 300         # con al menos 300 casos propios


def calidad(propio, direccion):
    if not propio:
        return "C", "sin historia propia suficiente"
    e = propio["efecto"] if direccion == "alcista" else -propio["efecto"]
    if e >= CALIDAD_EFECTO and propio["n"] >= CALIDAD_N:
        return "A", "funciona también en esta moneda"
    if e > 0:
        return "B", "a favor en esta moneda, pero débil o con poca muestra"
    return "C", "en esta moneda ha ido en contra o sin efecto"


def pct(x):
    return "-" if x is None or x != x else f"{x*100:.1f} %"


def guardar_oi(perp):
    filas = []
    for base, simbolo in perp.items():
        try:
            oi = ud._get(ud.FAPI + "/futures/data/openInterestHist", {"symbol": simbolo, "period": "4h", "limit": 500})
            ls = ud._get(ud.FAPI + "/futures/data/globalLongShortAccountRatio", {"symbol": simbolo, "period": "4h", "limit": 500})
            d = pd.DataFrame(oi)[["timestamp", "sumOpenInterest", "sumOpenInterestValue"]].merge(
                pd.DataFrame(ls)[["timestamp", "longShortRatio"]], on="timestamp", how="outer")
            d["moneda"] = base
            filas.append(d)
            time.sleep(0.1)
        except Exception:
            pass
    if not filas:
        print("\n(No se pudo guardar open interest)")
        return
    nuevo = pd.concat(filas)
    nuevo["fecha_utc"] = pd.to_datetime(nuevo["timestamp"].astype("int64"), unit="ms")
    if os.path.exists(REGISTRO_OI):
        nuevo = pd.concat([pd.read_csv(REGISTRO_OI), nuevo])
    nuevo = nuevo.drop_duplicates(["moneda", "timestamp"], keep="last").sort_values(["moneda", "timestamp"])
    nuevo.to_csv(REGISTRO_OI, index=False)
    dias = (nuevo["timestamp"].max() - nuevo["timestamp"].min()) / 86_400_000
    print(f"\nregistro_oi_multi.csv: {nuevo['moneda'].nunique()} monedas, {dias:.0f} días de histórico propio")


def main():
    if not os.path.exists(CATALOGO):
        print("No existe senales_multi.json. Ejecuta primero:  python multi_investigacion.py")
        return
    with open(CATALOGO, encoding="utf-8") as f:
        cat = json.load(f)
    desde = int((time.time() - DIAS * 86400) * 1000)

    print(f"Catálogo: {len(cat['senales'])} señales validadas, {len(cat['monedas'])} monedas (generado {cat['generado']})\n")
    print(f"{'moneda':<8}{'cierre':>12}  {'funding 3d':>10}  {'escenario':>9}  {'desde máx':>9}  señales activas")

    oportunidades, ultimas = [], {}
    for base, m in cat["monedas"].items():
        try:
            spot, perp, fund = ud.descargar_todo(m["spot"], perp_simbolo=m["perp"], factor=m["factor"],
                                                 desde_ms=desde, silencioso=True)
            df, u = ud.construir(spot, perp, fund, umbrales=m["umbrales"])
        except Exception as e:
            print(f"{base:<8}  error: {e}")
            continue
        sen, unis = ud.senales(df, u), ud.universos(df)
        i, r = df.index[-1], df.iloc[-1]
        ultimas[base] = df
        activas = []
        for s in cat["senales"]:
            if bool(unis[s["universo"]].loc[i]) and bool(sen[s["id"]][1].fillna(False).loc[i]):
                propio = s["por_moneda"].get(base)
                activas.append(s["id"])
                oportunidades.append({"moneda": base, "senal": s, "propio": propio, "fila": r})
        f3 = r["funding_3d"]
        print(f"{base:<8}{r['close']:>12.6g}  {'-' if f3 != f3 else f'{f3*100:.4f}%':>10}  "
              f"{'SÍ' if r['escenario'] else '-':>9}  {r['caida_desde_max']*100:+8.1f}%  "
              f"{', '.join(activas) if activas else ''}")

    print("\n==================== OPORTUNIDADES HOY ====================")
    if not oportunidades:
        print("Ninguna moneda tiene hoy una señal validada activa. Lo correcto es no hacer nada.")
    else:
        # primero las monedas donde la señal ha funcionado mejor históricamente
        for o in oportunidades:
            o["calidad"], o["motivo"] = calidad(o["propio"], o["senal"]["direccion"])
        oportunidades.sort(key=lambda o: (o["calidad"], -(o["propio"]["efecto"] if o["propio"] else -1)))
        n_a = sum(o["calidad"] == "A" for o in oportunidades)
        print(f"{n_a} de calidad A  |  {len(oportunidades) - n_a} de calidad B/C (informativas)")
        for o in oportunidades:
            s, p, r = o["senal"], o["propio"], o["fila"]
            print(f"\n>> [{o['calidad']}] {o['moneda']}  [{s['direccion'].upper()}]  {s['id']} ({s['universo']})  -  {s['descripcion']}")
            print(f"   Calidad {o['calidad']}: {o['motivo']}")
            print(f"   Cierre {r['close']:.6g}  |  rango 7d: soporte {r['rango_min']:.6g} / resistencia {r['rango_max']:.6g}  "
                  f"|  -8 % {r['close']*(1-ud.X):.6g} / +8 % {r['close']*(1+ud.X):.6g}")
            if p:
                print(f"   En {o['moneda']}: 7d arriba {pct(p['p_7d_arriba'])} (base de la moneda {pct(p['base_moneda'])}, "
                      f"efecto {p['efecto']*100:+.1f} pts, n={p['n']})")
            else:
                print(f"   En {o['moneda']}: pocos casos históricos propios -> fíate de la estadística conjunta")
            st = s["stats"]
            print(f"   Conjunto {len(cat['monedas'])} monedas: 7d arriba {pct(st['p_7d_arriba'])}, mediana {st['mediana_7d']*100:+.1f} %, "
                  f"primero -8 %/+8 %: {pct(st['primero_menos8'])} / {pct(st['primero_mas8'])}")

    # ---- registro en vivo
    cols = ["t", "moneda", "id", "universo", "direccion", "cierre", "calidad", "ret_7d"]
    reg = pd.read_csv(REGISTRO) if os.path.exists(REGISTRO) else pd.DataFrame(columns=cols)
    nuevas = [{"t": f"{o['fila']['t']:%Y-%m-%d %H:%M}", "moneda": o["moneda"], "id": o["senal"]["id"],
               "universo": o["senal"]["universo"], "direccion": o["senal"]["direccion"],
               "cierre": float(o["fila"]["close"]), "calidad": o["calidad"], "ret_7d": None} for o in oportunidades]
    if nuevas:
        reg = pd.concat([reg, pd.DataFrame(nuevas)]).drop_duplicates(["t", "moneda", "id", "universo"], keep="first")
    if len(reg):
        reg["ret_7d"] = pd.to_numeric(reg["ret_7d"], errors="coerce")
        for idx, fila in reg[reg["ret_7d"].isna()].iterrows():
            df = ultimas.get(fila["moneda"])
            if df is not None:
                v = df.set_index(df["t"].dt.strftime("%Y-%m-%d %H:%M"))["ret_7d"].get(fila["t"])
                if v is not None and v == v:
                    reg.loc[idx, "ret_7d"] = v
        reg.to_csv(REGISTRO, index=False)
        cerradas = reg.dropna(subset=["ret_7d"])
        print(f"\n--- Registro en vivo: {len(reg)} señales apuntadas, {len(cerradas)} con resultado a 7 días ---")
        if len(cerradas):
            ok = ((cerradas["direccion"] == "alcista") & (cerradas["ret_7d"] > 0)) | \
                 ((cerradas["direccion"] == "bajista") & (cerradas["ret_7d"] < 0))
            print(f"Aciertos: {ok.mean()*100:.1f} %  |  movimiento mediano a 7d: {cerradas['ret_7d'].median()*100:+.1f} %")
            if "calidad" in cerradas.columns:
                for q, g in cerradas.assign(ok=ok).groupby(cerradas["calidad"].fillna("-")):
                    print(f"   Calidad {q}: {g['ok'].mean()*100:.1f} % de {len(g)}")

    guardar_oi({b: m["perp"] for b, m in cat["monedas"].items()})
    print()


if __name__ == "__main__":
    main()