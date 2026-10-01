"""
uni_investigacion.py - Busca y valida señales para UNI (se ejecuta de vez en cuando, p. ej. 1 vez al mes).

Para cada señal candidata, en dos universos (todas las velas / escenario rally+corrección):
  1. Mide qué pasa después: 7 días más arriba, mediana, -8 %/+8 % primero,
     y si rompe antes el soporte o la resistencia del rango de 7 días.
  2. Prueba de validación: efecto en 2020-2024 y en 2025-2026 por separado.
     Solo pasa si el efecto tiene el MISMO signo en los dos periodos, es de al menos
     3 puntos en ambos y hay muestra suficiente en ambos.
  3. Guarda las señales que pasan en  senales_validadas.json  (lo usa el detector diario).

Uso:  python uni_investigacion.py
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import json
import pandas as pd
import uni_datos as ud

CARPETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del repo
CATALOGO = os.path.join(CARPETA, "senales_validadas.json")

EFECTO_MIN = 0.03     # 3 puntos
N_MIN = 150           # velas mínimas en cada periodo


def pct(x):
    return "   -  " if x is None else f"{x*100:5.1f}%"


def main():
    spot, perp, fund = ud.descargar_todo()
    df, umbrales = ud.construir(spot, perp, fund)
    print(f"\n{ud.SIMBOLO}: {len(df)} velas de 4h con spot + futuros, "
          f"del {df['t'].iloc[0]:%Y-%m-%d} al {df['t'].iloc[-1]:%Y-%m-%d %H:%M} UTC")
    print(f"Entrenamiento: hasta {ud.CORTE:%Y-%m-%d}  |  Comprobación: desde {ud.CORTE:%Y-%m-%d}")

    sen = ud.senales(df, umbrales)
    validadas = []

    for nombre_u, umask in ud.universos(df).items():
        base = ud.metricas(df[umask])
        tr_u = df[umask & (df["t"] < ud.CORTE)].dropna(subset=["ret_7d"])
        te_u = df[umask & (df["t"] >= ud.CORTE)].dropna(subset=["ret_7d"])
        base_tr = (tr_u["ret_7d"] > 0).mean() if len(tr_u) else float("nan")
        base_te = (te_u["ret_7d"] > 0).mean() if len(te_u) else float("nan")

        print(f"\n==================== UNIVERSO: {nombre_u.upper()} ====================")
        print(f"Base: n={base['n']}  7d arriba {pct(base.get('p_7d_arriba'))}  "
              f"mediana {base.get('mediana_7d', 0)*100:+.1f}%  "
              f"| -8%/+8% primero {pct(base.get('primero_menos8'))}/{pct(base.get('primero_mas8'))}  "
              f"| rompe soporte/resistencia {pct(base.get('rompe_soporte'))}/{pct(base.get('rompe_resistencia'))}")
        print(f"{'señal':<24}{'n':>6}  {'7d arr':>7} {'mediana':>8}  {'-8/+8 primero':>14}  "
              f"{'sop/res primero':>16}  {'efecto 20-24':>12} {'efecto 25-26':>12}  veredicto")

        for sid, (desc, smask) in sen.items():
            m = umask & smask.fillna(False).astype(bool)
            st = ud.metricas(df[m])
            a = df[m & (df["t"] < ud.CORTE)].dropna(subset=["ret_7d"])
            b = df[m & (df["t"] >= ud.CORTE)].dropna(subset=["ret_7d"])
            if st["n"] == 0:
                print(f"{sid:<24}{0:>6}  sin casos")
                continue

            if len(a) < N_MIN or len(b) < N_MIN:
                ea = eb = None
                veredicto = "muestra insuficiente"
            else:
                ea = (a["ret_7d"] > 0).mean() - base_tr
                eb = (b["ret_7d"] > 0).mean() - base_te
                pasa = (ea > 0) == (eb > 0) and abs(ea) >= EFECTO_MIN and abs(eb) >= EFECTO_MIN
                veredicto = ("VALIDADA " + ("ALCISTA" if ea > 0 else "BAJISTA")) if pasa else "ruido"
                if pasa:
                    validadas.append({
                        "id": sid, "universo": nombre_u, "descripcion": desc,
                        "direccion": "alcista" if ea > 0 else "bajista",
                        "efecto_2020_2024": round(float(ea), 4), "efecto_2025_2026": round(float(eb), 4),
                        "base_universo": base, "stats": st,
                    })

            s_ea = "      -     " if ea is None else f"{ea*100:+9.1f}pts"
            s_eb = "      -     " if eb is None else f"{eb*100:+9.1f}pts"
            print(f"{sid:<24}{st['n']:>6}  {pct(st.get('p_7d_arriba')):>7} {st.get('mediana_7d', 0)*100:+7.1f}%  "
                  f"{pct(st.get('primero_menos8'))}/{pct(st.get('primero_mas8'))}  "
                  f"{pct(st.get('rompe_soporte'))}/{pct(st.get('rompe_resistencia'))}   "
                  f"{s_ea} {s_eb}  {veredicto}")

    catalogo = {
        "generado": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "datos_hasta": f"{df['t'].iloc[-1]:%Y-%m-%d %H:%M}",
        "umbrales": umbrales,
        "criterio": f"mismo signo en 2020-24 y 2025-26, efecto >= {EFECTO_MIN*100:.0f} pts y n >= {N_MIN} en ambos",
        "senales": validadas,
    }
    with open(CATALOGO, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, indent=2, ensure_ascii=False)

    print("\n==================== CATÁLOGO ====================")
    if validadas:
        for v in validadas:
            print(f"  [{v['direccion'].upper():8}] {v['id']:<22} ({v['universo']})  {v['descripcion']}")
    else:
        print("  Ninguna señal ha pasado la validación.")
    print(f"\nGuardado en {CATALOGO}")
    print("Aviso: con ~22 pruebas es normal que 1 salga 'validada' por azar. Fíate más de las que tienen lógica de mercado.\n")


if __name__ == "__main__":
    main()