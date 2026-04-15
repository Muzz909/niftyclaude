# 📊 NIFTY Live Sentiment Dashboard — v2.0

A clean, signal-first market reading dashboard for NIFTY 50 intraday analysis.
Built with Streamlit. Designed for screen-only use during market hours.

---

## What it shows

| Section | What it tells you |
|---|---|
| **Signal card** | BUY / SELL / WAIT + confidence % + score |
| **Levels row** | Entry (CMP), Stop-Loss, Target, Risk:Reward (only when a signal fires) |
| **Chart** | 5-day / 5-min candlestick with EMA20, EMA50, VWAP, 20-bar high/low bands |
| **Metrics row** | NIFTY price, RSI, VWAP, EMA cross, ATR, PCR |
| **Reasons** | Colour-coded pills explaining exactly why the signal fired |
| **Candle detail** | Collapsed expander — open only if you want the micro detail |

---

## Setup (one-time)

### 1. Clone / download

```bash
git clone https://github.com/YOUR_USERNAME/nifty-dashboard.git
cd nifty-dashboard
```

Or just put `nifty_dashboard.py` and `requirements.txt` in the same folder.

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note on nsepython**: This library scrapes NSE's option chain for Put-Call Ratio.
> NSE occasionally rate-limits or changes their API. If PCR shows "N/A", the dashboard
> still works — PCR is simply excluded from the score. No action needed.

### 4. Run

```bash
streamlit run nifty_dashboard.py
```

The dashboard opens at `http://localhost:8501` in your browser.

---

## Running during market hours

- Best used **09:20 – 15:25 IST** (after the opening 5 minutes settle)
- Auto-refresh is ON by default (every 30 seconds)
- Use the **Force Refresh** button if data looks stale
- VWAP resets correctly at the start of each trading session

---

## Understanding the signal

### Scoring model (max ±5 or ±6 depending on PCR availability)

| Factor | Bullish | Bearish |
|---|---|---|
| EMA cross (20 vs 50) | +2 | -2 |
| RSI > 55 / < 45 | +1 | -1 |
| Price vs VWAP | +2 | -2 |
| PCR (when available) | +1 (1.15–1.3) | -1 (>1.3 or <0.7) |

### Gates (score must also pass these to fire a signal)

| Gate | Why |
|---|---|
| Regime must be TRENDING | Signals in sideways markets have no edge |
| ATR must be > 0.4% of price | Low-volatility bars → noise, not signal |
| Bullish score needs a 20-bar breakout | Confirmation that price is actually moving |
| Bearish score needs a 20-bar breakdown | Same — avoids fading into support |

### Levels

- **Entry**: Current market price (CMP) at signal time
- **Stop-Loss**: 1.5× ATR below entry (bullish) / above entry (bearish)
- **Target**: 2.25× ATR from entry (= 1.5R — reward is 1.5× the risk)
- **These are reference levels** — adjust to your own risk tolerance

---

## Fixes from v1

1. VWAP now resets per trading session — v1 ran a 5-day cumsum (wrong)
2. RSI uses Wilder's smoothing — v1 used a simple rolling average
3. Breakout detection uses 20-bar rolling high/low — v1 compared to the previous single bar
4. ATR low-vol filter is 0.4% — v1 used 0.2% (almost never triggered)
5. PCR ranges are calibrated (extreme readings flip bearish) — v1 treated high PCR as always bullish
6. Confidence denominator is actual max possible score — v1 hardcoded 6, so missing PCR inflated confidence
7. Cache TTL = 30s, matching the auto-refresh — v1 cached for 5 min while refreshing every 30s
8. Entry / SL / Target provided — v1 gave no actionable levels
9. Signal is a full-width coloured hero card — v1 used plain markdown text
10. Chart is near the top, annotated with current price line — v1 placed chart at the bottom with no annotations
11. Silent bare `except` replaced with logged exceptions
12. Candle breakdown demoted to collapsible expander

---

## Disclaimer

This dashboard is for **market reading and learning only**.
It is not financial advice. Do not trade real money based solely on automated signals
without understanding the underlying logic and testing it yourself first.
