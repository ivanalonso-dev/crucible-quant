"""
multi_investigacion.py - Valida las señales en las 30 criptos con más capitalización (+ UNI).

Qué hace:
  1. Saca el top 30 por capitalización (CoinGecko), sin stablecoins ni wrapped,
     y se queda con las que tienen perpetuo USDT en Binance (hace falta para el funding).
  2. Descarga el histórico 4h (spot + futuros + funding) de cada una.
  3. Para cada señal candidata, junta todas las monedas y exige TRES cosas para validarla:
       a) mismo signo en 2020-2024 y en 2025-2026, con efecto >= 3 puntos en ambos
       b) muestra suficiente en ambos periodos
       c) AMPLITUD: el efecto va en la misma dirección en al menos el 60 % de las monedas
          (así no la valida una sola moneda ni un único crash que arrastró a todas)
  4. Guarda el catálogo en  senales_multi.json  (lo usa multi_detector.py).

Tarda unos 5-10 minutos (descarga ~30 historiales completos).
Uso:  python multi_investigacion.py
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import json
import pandas as pd
import uni_datos as ud

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CATALOGO = os.path.join(CARPETA, "senales_multi.json")

N_TOP = 30
EFECTO_MIN = 0.03      # 3 puntos
N_MIN = 300            # velas con señal en cada periodo (sumando monedas)
N_MONEDA = 100         # velas con señal para contar una moneda en la amplitud
AMPLITUD_MIN = 0.60


def pct(x):
    return "  -  " if x is None or x != x else f"{x*100:5.1f}%"


def p7(d):
    d = d.dropna(subset=["ret_7d"])
    return (d["ret_7d"] > 0).mean() if len(d) else float("nan")


def main():
    monedas = ud.top_monedas(N_TOP)
    print(f"Universo ({len(monedas)}): " + ", ".join(m["base"] for m in monedas) + "\n")

    tablas, info_monedas, descs = [], {}, {}
    for k, m in enumerate(monedas, 1):
        print(f"[{k:>2}/{len(monedas)}] {m['base']:<6}", end=" ", flush=True)
        try:
            spot, perp, fund = ud.descargar_todo(m["spot"], perp_simbolo=m["perp"], factor=m["factor"], silencioso=True)
            df, u = ud.construir(spot, perp, fund)
            for sid, (desc, mask) in ud.senales(df, u).items():
                df["s_" + sid] = mask.fillna(False).astype(bool).values
                descs[sid] = desc
            df["moneda"] = m["base"]
            tablas.append(df)
            info_monedas[m["base"]] = {**m, "umbrales": u}
            print(f"{len(df):>6} velas desde {df['t'].iloc[0]:%Y-%m}  |  funding con datos: {df['funding_3d'].notna().mean()*100:.0f} %")
        except Exception as e:
            print(f"descartada ({e})")

    total = pd.concat(tablas, ignore_index=True)
    print(f"\nTotal: {len(total):,} velas de 4h en {len(tablas)} monedas")

    validadas = []
    universos = {"todas": total, "escenario": total[total["escenario"].astype(bool)]}
    for nombre_u, U in universos.items():
        tr_u, te_u = U[U["t"] < ud.CORTE], U[U["t"] >= ud.CORTE]
        base_tr, base_te = p7(tr_u), p7(te_u)
        base = ud.metricas(U)
        print(f"\n==================== UNIVERSO: {nombre_u.upper()} ====================")
        print(f"Base: n={base['n']:,}  7d arriba {pct(base.get('p_7d_arriba'))}  mediana {base.get('mediana_7d', 0)*100:+.1f}%  "
              f"| -8/+8 primero {pct(base.get('primero_menos8'))}/{pct(base.get('primero_mas8'))}")
        print(f"{'señal':<22}{'n':>8}  {'7d arr':>6} {'mediana':>8}  {'-8/+8 primero':>13}  "
              f"{'ef. 20-24':>9} {'ef. 25-26':>9}  {'amplitud':>9}  veredicto")

        for sid in descs:
            S = U[U["s_" + sid]]
            st = ud.metricas(S)
            if st["n"] == 0:
                print(f"{sid:<22}{0:>8}  sin casos")
                continue
            a, b = S[S["t"] < ud.CORTE].dropna(subset=["ret_7d"]), S[S["t"] >= ud.CORTE].dropna(subset=["ret_7d"])

            # amplitud: en cuántas monedas va en la misma dirección
            por_moneda = {}
            for mon, g in S.groupby("moneda"):
                g7 = g.dropna(subset=["ret_7d"])
                if len(g7) >= N_MONEDA:
                    pm, bm = p7(g7), p7(U[U["moneda"] == mon])
                    por_moneda[mon] = {"n": int(len(g7)), "p_7d_arriba": float(pm),
                                       "base_moneda": float(bm), "efecto": float(pm - bm)}

            if len(a) < N_MIN or len(b) < N_MIN:
                ea = eb = None
                veredicto, amp_txt = "muestra insuficiente", "-"
            else:
                ea, eb = p7(a) - base_tr, p7(b) - base_te
                misma = [v for v in por_moneda.values() if (v["efecto"] > 0) == (ea > 0)]
                amp = len(misma) / len(por_moneda) if por_moneda else 0
                amp_txt = f"{len(misma)}/{len(por_moneda)}"
                pasa = ((ea > 0) == (eb > 0) and abs(ea) >= EFECTO_MIN and abs(eb) >= EFECTO_MIN
                        and amp >= AMPLITUD_MIN)
                veredicto = ("VALIDADA " + ("ALCISTA" if ea > 0 else "BAJISTA")) if pasa else "ruido"
                if pasa:
                    validadas.append({
                        "id": sid, "universo": nombre_u, "descripcion": descs[sid],
                        "direccion": "alcista" if ea > 0 else "bajista",
                        "efecto_2020_2024": round(float(ea), 4), "efecto_2025_2026": round(float(eb), 4),
                        "amplitud": amp_txt, "base_universo": base, "stats": st, "por_moneda": por_moneda,
                    })

            s_ea = "     -   " if ea is None else f"{ea*100:+6.1f}pts"
            s_eb = "     -   " if eb is None else f"{eb*100:+6.1f}pts"
            print(f"{sid:<22}{st['n']:>8}  {pct(st.get('p_7d_arriba')):>6} {st.get('mediana_7d', 0)*100:+7.1f}%  "
                  f"{pct(st.get('primero_menos8'))}/{pct(st.get('primero_mas8'))}  "
                  f"{s_ea} {s_eb}  {amp_txt:>9}  {veredicto}")

    print("\n==================== CATÁLOGO ====================")
    if not validadas:
        print("  Ninguna señal ha pasado la validación.")
    for v in validadas:
        print(f"\n[{v['direccion'].upper()}] {v['id']} ({v['universo']}) - {v['descripcion']}")
        print(f"   Efecto: {v['efecto_2020_2024']*100:+.1f} pts (2020-24) / {v['efecto_2025_2026']*100:+.1f} pts (2025-26)  |  "
              f"amplitud {v['amplitud']} monedas  |  7d arriba {pct(v['stats']['p_7d_arriba'])} (base {pct(v['base_universo']['p_7d_arriba'])})")
        # estabilidad año a año: efecto frente a la base de ese mismo año
        U = universos[v["universo"]]
        S = U[U["s_" + v["id"]]]
        linea = []
        for anio in sorted(U["t"].dt.year.unique()):
            su, ss = U[U["t"].dt.year == anio], S[S["t"].dt.year == anio]
            n7 = len(ss.dropna(subset=["ret_7d"]))
            if n7 >= 100:
                e = p7(ss) - p7(su)
                v.setdefault("por_anio", {})[str(anio)] = {"n": int(n7), "efecto": round(float(e), 4)}
                linea.append(f"{anio}: {e*100:+.1f} (n={n7})")
            else:
                linea.append(f"{anio}: -")
        print("   Año a año: " + "  |  ".join(linea))
        print(f"   {'moneda':<8}{'n':>6}  {'7d arriba':>9}  {'base':>6}  {'efecto':>8}")
        for mon, d in sorted(v["por_moneda"].items(), key=lambda x: -x[1]["efecto"]):
            print(f"   {mon:<8}{d['n']:>6}  {pct(d['p_7d_arriba']):>9}  {pct(d['base_moneda']):>6}  {d['efecto']*100:+7.1f}pts")

    catalogo = {
        "generado": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"),
        "criterio": (f"mismo signo 2020-24 y 2025-26, efecto >= {EFECTO_MIN*100:.0f} pts, n >= {N_MIN} por periodo, "
                     f"amplitud >= {AMPLITUD_MIN*100:.0f} % de monedas"),
        "monedas": info_monedas,
        "senales": validadas,
    }
    with open(CATALOGO, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, indent=2, ensure_ascii=False)
    print(f"\nGuardado en {CATALOGO}\n")


if __name__ == "__main__":
    main()