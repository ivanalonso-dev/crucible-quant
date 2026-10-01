"""
Textos públicos del bot Crucible Quant (en inglés).
Los usa publicar_info.py. Edítalos aquí si quieres cambiar algo.
Datos de contacto ya completados.
"""

# @BotFather -> /setabouttext  (máx. 120 caracteres; se ve en el perfil del bot)
ABOUT = "Daily volatility alerts for the top 30 cryptos by market cap. Risk information only, not financial advice."

# @BotFather -> /setdescription  (máx. 512 caracteres; se ve antes de pulsar Iniciar)
DESCRIPTION = (
    "Crucible Quant flags which of the top 30 cryptocurrencies by market cap are statistically likely "
    "to move ±8% within the next 7 days.\n\n"
    "One summary every day at 10:10 (Madrid time). No buy/sell calls: the alerts tell you WHEN a big "
    "move is likely, not in which direction.\n\n"
    "30-day free trial, then a monthly subscription (~USD 30) paid with Telegram Stars. Not financial advice."
)

README = """📌 README — What Crucible Quant does

Crucible Quant sends ONE summary every day at 10:10 (Madrid time) with volatility alerts for the top 30 cryptocurrencies by market capitalization.

🔎 What an alert means
An alert means the coin is statistically likely to move at least ±8% (up OR down) within the next 7 days, compared with its usual behaviour.
Example: "LINK · 84% (usual 70%)" = historically, in similar conditions, LINK moved ±8% within 7 days 84% of the time, versus 70% on a normal day.

🔴 Double alert = two or more signals at the same time (the most reliable).
🟠 Single alert = one signal.

📐 Signals used
• Volatility spike — short-term volatility far above its 90-day level
• Volume surge — trading volume far above its 30-day average
• Extreme funding — perpetual futures funding at an extreme level
• Rally + pullback — strong prior rally followed by a correction

📊 How it was built
Every signal was validated on historical data since 2020 across 30 coins, tested out of sample and required to hold in almost every year. In the 2025–2026 backtest, double alerts were followed by a ±8% move about 89% of the time (vs. ~76% usual).
Every summary also shows the LIVE track record: each alert is checked 7 days later and the real hit rate is reported. Past and backtested results do not guarantee future results.

⚠️ What it does NOT do
It does not tell you whether the move will be up or down, and it does not tell you what to buy or sell.

💡 How people use it
As risk information: avoid tight stops or high leverage before a likely big move, size positions more carefully, or simply know where the action is likely to be this week."""

DISCLAIMER = """⚖️ DISCLAIMER — Not financial advice

• Crucible Quant provides statistical information about market volatility. It is NOT financial, investment, legal or tax advice, and it is not a recommendation to buy, sell or hold any asset.
• We do not tell you where, when or how much to invest.
• We monitor the top 30 cryptocurrencies by market capitalization, but the alerts do NOT say whether a move will be bullish, bearish or sideways. They only estimate the probability of a large move in either direction.
• Probabilities come from historical data and backtests. Markets change and past results do not guarantee future results. Alerts can be wrong.
• Cryptocurrencies are highly volatile and you can lose all the money you invest. Any decision you make is your own responsibility. If you need advice, consult a licensed professional.
• Crucible Quant is not affiliated with any exchange or cryptocurrency project."""

PRIVACY = """🔒 PRIVACY POLICY — Crucible Quant
Last updated: 30 September 2026

1. Who we are
Crucible Quant is operated by Ivan Alonso, Barcelona, Spain ("we"). Contact: ivanalonso.dev@gmail.com.

2. What data we collect
• Your Telegram user ID, chat ID and public username, needed to send you the alerts.
• Your trial start and end dates.
• If you subscribe: the payment confirmation that Telegram sends us (amount in Telegram Stars, payment ID and subscription end date).
We never see or store your card, bank or wallet details, and we do not collect your phone number, contacts, location or messages beyond the commands you send to the bot.

3. Payments
Subscriptions are paid with Telegram Stars, directly inside Telegram. Stars are purchased and processed by Telegram (and, on mobile, by Apple or Google) under their own terms and privacy policies. We only receive the confirmation that a payment was made.

4. Why we use your data
Only to provide the service you requested: sending the daily volatility alerts and managing your free trial and subscription. Legal basis: performance of the service you request (GDPR Art. 6(1)(b)) and, for billing records, our legal obligations (Art. 6(1)(c)).

5. Sharing
We do NOT sell, rent or share your data with third parties for marketing or any other purpose. The only external service involved is Telegram, which delivers the messages and processes the payments.

6. Retention
We keep your data while you use the bot. If you stop using it or ask us to, it is deleted within 30 days, except payment records that the law requires us to keep.

7. Your rights
You can request access, correction, deletion or a copy of your data, or object to its use, by writing to ivanalonso.dev@gmail.com. You can also file a complaint with the Spanish Data Protection Agency (AEPD).

8. Changes
We may update this policy. The latest version is always available with /privacy."""

PRICING = """💳 PLANS & PRICING

🎁 Free trial: your first 30 days are free, with full access to the daily alerts. No payment details needed.

⭐ After the trial: monthly subscription paid with Telegram Stars (equivalent to about USD 30/month).
• Paid inside Telegram with Stars (buy them with card, Apple Pay or Google Pay).
• Renews automatically every 30 days — no need to pay by hand each month.
• Cancel anytime with /cancel or in Telegram: Settings → My Stars → Subscriptions. You keep access until the end of the paid period.
• If you do not subscribe after the trial, alerts simply stop. Nothing is charged automatically unless you subscribe.

Tap the button below to subscribe."""

SECCIONES = [("README", README), ("DISCLAIMER", DISCLAIMER), ("PRIVACY", PRIVACY), ("PRICING", PRICING)]

if __name__ == "__main__":
    print(f"ABOUT: {len(ABOUT)}/120 caracteres")
    print(f"DESCRIPTION: {len(DESCRIPTION)}/512 caracteres")
    for n, t in SECCIONES:
        print(f"{n}: {len(t)}/4096 caracteres")
