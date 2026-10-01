# The research journey

Crucible Quant did not start as a volatility product. It started with a simple question about one coin (Uniswap): *can the next move be predicted?* This document records every major step, including the dead ends, because the dead ends are what made the final system credible.

All results come from runs of the code in [`research/`](../research) on public Binance data (4h candles, September 2020 to September 2026). Raw outputs of key experiments are in [`research/results/`](../research/results).

---

## Phase 1 · Candles and regimes (UNI, then 15 large caps)

**Candlestick patterns carry no directional edge.** Across 40,000+ daily candles in 15 large-cap assets, the probability of a green next candle is **49.8%**. Conditioning on the previous candle's colour, red streaks or large red candles moved this by only 1 to 4 points, and nothing survived out-of-sample validation.
→ [`uni_velas.py`](../research/uni_velas.py)

**Regime predicts volatility, not direction.** After a strong rally followed by a pullback from the high, direction stays close to a coin flip, but the probability of a large move jumps:

| Condition | Touches −10% in 7 days | Touches +10% in 7 days |
|---|---|---|
| Any day (base rate) | 35.7% | 37.4% |
| Rally + pullback regime | **54.6%** | **50.0%** |

This was the first hint of what Crucible would become.
→ [`uni_escenario.py`](../research/uni_escenario.py), [`uni_v3.py`](../research/uni_v3.py)

---

## Phase 2 · Microstructure signals, single asset vs. many

**A single-asset "discovery" that did not generalise.** On UNI alone, 22 candidate signals were tested (funding, aggressive order flow, futures basis, leverage, volume). Only one passed: **negative funding** (shorts paying longs), +13.4 pts in 2020–24 and +11.8 pts in 2025–26 on "price higher in 7 days". Tested across 29 assets, the pooled effect collapsed to +2.0 / +1.5 pts and was rejected. Lesson: never trust a single-asset backtest.
→ [`uni_investigacion.py`](../research/uni_investigacion.py)

**A cross-asset momentum effect that passed statistically but not economically.** Across 29 assets (291,674 candles), high 3-day funding was followed by price up 7 days later 54.3% of the time vs. 48.9% base, consistent in 20 of 23 assets. However the effect was several times larger in 2025–26 than in 2020–24 (strong regime dependence).
→ [`multi_investigacion.py`](../research/multi_investigacion.py)

**Order-flow features alone are noise.** Aggressive buy share (spot and perpetual), futures basis and futures-to-spot volume ratio either flipped sign between periods or did not reach the threshold.

---

## Phase 3 · Turning signals into trades (and why it failed)

Hit rates are not profits. The surviving directional signals were turned into explicit trading rules with fees, slippage, stops, cooldowns and position sizing, on a time split (2020–2024 design, 2025–2026 test).

| Experiment | Idea | Verdict |
|---|---|---|
| Signal backtest | Trade every directional signal with realistic costs | No robust positive expectancy after costs |
| Portfolio backtest | Combine signals across 30 coins with risk management | Profits concentrated in 1–2 coins; failed the "remove the best coin" check |
| Carry (funding) | Collect funding when it is high, market-neutral | An on/off "carry alarm" added nothing: most carry profit came while the alarm was *off* |
| Breakout direction | After an alert, trade the first break of the 7-day range (with volume / taker-flow confirmation, 2:1 target/stop) | Not approved on the 2025–26 test |
| Direction lab | 6 independent ideas to call the direction of the alerted move (funding squeeze, BTC contagion, market breadth, position in 90-day range, weekend effect, walk-forward logistic regression), Bonferroni-corrected | None passed |
| Order bracket ("horquilla") | Buy-stop + sell-stop around the price when an alert fires | Negative expectancy, even with neutral assumptions |
| Move ignition | Does the speed / volume / aggressiveness of the first leg predict reaching 8%? | Not approved ([results](../research/results/arranque_resultados.txt)) |
| Buying straddles (DVOL proxy) | Buy volatility when an alert fires | Loses on average: options already price the volatility ([results](../research/results/straddle_dvol_resultados.txt)) |
| Selling volatility | Short straddle / iron butterfly, with and without alerts | The volatility premium exists, but the alert does not work as a filter ([results](../research/results/vender_volatilidad_resultados.txt)) |
| On-chain exchange flows | Net inflows to exchange wallets (BigQuery / Dune SQL) | Pipeline designed; not conclusively tested within data-access limits ([SQL](../research/onchain)) |

**Conclusion of Phase 3:** with price, derivatives and order-flow data, *direction* was not reliably predictable. Many ideas looked good in isolation; none survived costs, time splits and breadth checks together.

---

## Phase 4 · The pivot: predict *when*, not *where*

Every failed experiment had one thing in common: the alerts were good at finding **big moves**, they just could not tell the direction. So the target was changed to a direction-neutral one: *will price touch +8% or −8% within 7 days?*

Seven candidate volatility signals were tested with a stricter protocol ([`senales_volatilidad.py`](../senales_volatilidad.py)):

- non-overlapping episodes (max one per coin per 7 days),
- edge measured against the same coin's base rate in the same year,
- bootstrap 95% confidence intervals,
- approval only if the whole CI is above zero, the edge is positive in at least 60% of years, and n ≥ 100.

| Signal | Edge | Verdict |
|---|---|---|
| Volatility spike | +12.7 pts | ✅ approved |
| Volume surge | +11.5 pts | ✅ approved |
| Rally + pullback | +7.1 pts | ✅ approved |
| Extreme funding | +7.0 pts | ✅ approved |
| Volatility compression ("calm before the storm") | — | ❌ rejected |
| Narrow range | — | ❌ rejected |
| Drying volume | — | ❌ rejected |

Pairs of approved signals stack: up to **+16 pts**. In 2025–2026, **double alerts were followed by a ±8% move 88.8% of the time vs. 75.8%** for the same coins on a normal day, and the effect held in every year since 2020.

Interesting negative: "volatility compression" (the popular *calm before the storm* idea) was rejected. In crypto, volatility clusters: big moves follow big moves, not quiet periods.

---

## Phase 5 · From research to product

- **Daily monitor** with a live, self-checking track record (each alert verified after 7 days).
- **Telegram subscription bot** with Telegram Stars auto-renewing payments and a 30-day trial.
- **Weekly public results** on X using only closed alerts.
- **Deployment** on a Linux VPS with systemd and cron.

The live track record is the real test. Backtests can be wrong; a public, timestamped log of every alert cannot be cherry-picked.

---

## Lessons

1. **Single-asset results are anecdotes.** Breadth across many assets kills most "discoveries".
2. **Hit rate ≠ profit.** Costs, stops and concentration turned positive signals into zero.
3. **Asking a different question can unlock an edge.** The data could not answer *where*, but it answered *when* consistently.
4. **Popular intuitions deserve testing.** "Calm before the storm" failed; volatility clustering won.
5. **Publish the misses.** Credibility comes from the full record, not the highlights.
