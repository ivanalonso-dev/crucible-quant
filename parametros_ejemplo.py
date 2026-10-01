"""
parametros_ejemplo.py - PUBLIC PLACEHOLDER signal parameters.

The production thresholds and validated edges of Crucible Quant live in `parametros.py`,
which is intentionally NOT published (Crucible is a live, paid product).
These example values are illustrative only: the code runs end-to-end with them,
but they are NOT the validated production values.

To run with your own values: copy this file to `parametros.py` and edit it.
"""

# --- rally + pullback ("escenario") ---
RALLY_MIN = 1.5              # minimum prior rally (max 30d / min 60d - 1)
CAIDA_MIN, CAIDA_MAX = -0.30, -0.10   # pullback range from the 30-day high

# --- volatility spike ---
VOL_RATIO = 2.0              # 7-day vol / 90-day vol above this = spike

# --- extreme funding ---
FUND_PCT = 0.95              # |3-day funding| percentile within the last year

# --- volume surge ---
VOLUMEN_REL = 2.0            # 5-day volume / 30-day average above this = surge

# --- validated edge (probability points over each coin's base rate) ---
VENTAJA = {"escenario": 0.05, "volatilidad": 0.05, "funding": 0.05, "volumen": 0.05,
           ("escenario", "volatilidad"): 0.08, ("escenario", "funding"): 0.08,
           ("escenario", "volumen"): 0.08, ("volatilidad", "funding"): 0.08,
           ("volatilidad", "volumen"): 0.08, ("funding", "volumen"): 0.08}
