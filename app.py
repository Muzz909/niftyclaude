"""
NIFTY Live Sentiment Dashboard — v2.0
--------------------------------------
Fixes applied vs v1:
  1. VWAP resets per trading session (09:15 IST daily) — not a running 5-day cumsum
  2. RSI uses Wilder's smoothing (EMA-style), not simple rolling mean
  3. Breakout/breakdown uses rolling 20-bar high/low, not the previous single bar
  4. ATR low-vol threshold raised to 0.4% (realistic for NIFTY 5-min bars)
  5. PCR signal accounts for extreme readings (panic zone > 1.3, complacency < 0.7)
  6. Confidence denominator is the actual max possible score, not a hardcoded 6
  7. Cache TTL aligned to auto-refresh interval (30s live, 60s data)
  8. Entry price, Stop-Loss (ATR-based), and Target (1.5R) calculated for every signal
  9. Signal is the hero element — full-width coloured card at the top
 10. Chart is above the details section, annotated with VWAP/EMA labels + current price line
 11. Candle breakdown demoted to collapsible expander — not cluttering main view
 12. Silent bare except replaced with logged exceptions
 13. All indicator logic extracted into pure functions
 14. NSE scraper failure shows explicit warning, not silent N/A
 15. Page layout: Signal → Chart → Levels → Context → Reasons → Detail
"""

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, time
import pytz
import logging

IST = pytz.timezone("Asia/Kolkata")
now_ist = datetime.now(IST)

# ── optional NSE scraper (may fail — handled gracefully) ──────────────────────
try:
    from nsepython import nse_optionchain_scrapper
    NSE_AVAILABLE = True
except ImportError:
    NSE_AVAILABLE = False

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NIFTY Sentiment Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS  — signal card colours, clean metrics
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Signal hero card */
.signal-card {
    padding: 1.4rem 1.8rem;
    border-radius: 14px;
    margin-bottom: 0.5rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.8rem;
}
.signal-card.bullish   { background: #0d3d1e; border: 1.5px solid #1a7a3a; }
.signal-card.bearish   { background: #3d0d0d; border: 1.5px solid #7a1a1a; }
.signal-card.neutral   { background: #1e1e2e; border: 1.5px solid #3a3a5a; }
.signal-label { font-size: 2rem; font-weight: 700; letter-spacing: -0.5px; }
.signal-label.bullish  { color: #3ddc84; }
.signal-label.bearish  { color: #ff6b6b; }
.signal-label.neutral  { color: #aaaacc; }
.signal-conf { font-size: 0.9rem; color: #aaaaaa; margin-top: 2px; }

/* Levels row */
.level-box {
    background: #111827;
    border: 0.5px solid #2a3040;
    border-radius: 10px;
    padding: 0.7rem 1.1rem;
    text-align: center;
    flex: 1;
    min-width: 110px;
}
.level-label { font-size: 0.72rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.06em; }
.level-value { font-size: 1.25rem; font-weight: 600; margin-top: 2px; }
.level-value.entry  { color: #e5e7eb; }
.level-value.sl     { color: #ff6b6b; }
.level-value.target { color: #3ddc84; }
.level-value.rr     { color: #facc15; }
.levels-row { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.8rem; }

/* Reason pills */
.reason-pill {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.78rem;
    margin: 3px 3px 3px 0;
    font-weight: 500;
}
.reason-pill.bull { background: #0d3d1e; color: #3ddc84; border: 0.5px solid #1a7a3a; }
.reason-pill.bear { background: #3d0d0d; color: #ff6b6b; border: 0.5px solid #7a1a1a; }
.reason-pill.neut { background: #1e1e2e; color: #aaaacc; border: 0.5px solid #3a3a5a; }

/* Score bar */
.score-bar-wrap { display:flex; align-items:center; gap:10px; margin: 0.4rem 0 0.8rem; }
.score-bar-bg { flex:1; height:8px; background:#1e1e2e; border-radius:4px; overflow:hidden; }
.score-bar-fill { height:100%; border-radius:4px; transition: width 0.4s; }
.score-bar-fill.bull { background: linear-gradient(90deg,#1a7a3a,#3ddc84); }
.score-bar-fill.bear { background: linear-gradient(90deg,#7a1a1a,#ff6b6b); }
.score-bar-fill.neut { background: #3a3a5a; }

/* Misc */
div[data-testid="metric-container"] label { font-size: 0.75rem !important; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# CONTROLS
# ─────────────────────────────────────────────────────────────────────────────
top_left, top_right = st.columns([7, 2])
with top_left:
    st.markdown("## 📊 NIFTY Live Sentiment Dashboard")
with top_right:
    market_open = time(9, 15)
    market_close = time(15, 30)

    is_market_hours = market_open <= now_ist.time() <= market_close

    auto = st.toggle(
        "Auto-refresh (30s)",
        value=is_market_hours,
        disabled=True  # user cannot override
    )
# with top_right:
#     auto = st.toggle("Auto-refresh (30s)", value=True)
    if st.button("⟳ Force refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

if auto:
    st_autorefresh(interval=30_000, key="autorefresh")


st.caption(f"Last updated: {now_ist.strftime('%d %b %Y  %H:%M:%S IST')}")
market_status = "🟢 Market Open" if is_market_hours else "🔴 Market Closed"
st.caption(f"{market_status} · Last updated: {now_ist.strftime('%d %b %Y  %H:%M:%S IST')}")

# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCH
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_ohlcv() -> pd.DataFrame:
    df = yf.download("^NSEI", period="8d", interval="5m", progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Close"])
    # Localise index to IST for session-aware calculations
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(IST)
    else:
        df.index = df.index.tz_convert(IST)
    return df

@st.cache_data(ttl=30)
def load_pcr() -> float | None:
    if not NSE_AVAILABLE:
        return None
    try:
        oc = nse_optionchain_scrapper("NIFTY")
        ce_oi = sum(
            item["CE"]["openInterest"]
            for item in oc["records"]["data"]
            if "CE" in item and "PE" in item
        )
        pe_oi = sum(
            item["PE"]["openInterest"]
            for item in oc["records"]["data"]
            if "CE" in item and "PE" in item
        )
        return pe_oi / ce_oi if ce_oi else None
    except Exception as exc:
        logger.warning("PCR fetch failed: %s", exc)
        return None

data = load_ohlcv()

if data.empty:
    st.error("❌ Could not fetch NIFTY data from Yahoo Finance. Check your internet connection.")
    st.stop()

if len(data) < 26:
    st.warning("⏳ Not enough bars to compute indicators yet. Waiting for market data…")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────────────────

def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def compute_rsi_wilder(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI — uses EMA-style smoothing (alpha = 1/period)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def compute_vwap_intraday(df: pd.DataFrame) -> pd.Series:
    """
    True intraday VWAP — resets at the start of each calendar date (09:15 IST).
    Returns a Series aligned to df.index.
    """
    df = df.copy()
    df["_date"] = df.index.date
    df["TP"] = (df["High"] + df["Low"] + df["Close"]) / 3
    df["TPV"] = df["TP"] * df["Volume"]

    vwap_vals = []
    for _, grp in df.groupby("_date", sort=True):
        cum_tpv = grp["TPV"].cumsum()
        cum_vol = grp["Volume"].cumsum()
        vwap_vals.append(cum_tpv / cum_vol.replace(0, np.nan))

    return pd.concat(vwap_vals).reindex(df.index)

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h_l   = df["High"] - df["Low"]
    h_pc  = (df["High"] - df["Close"].shift(1)).abs()
    l_pc  = (df["Low"]  - df["Close"].shift(1)).abs()
    tr    = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()

# Apply
data["EMA20"] = compute_ema(data["Close"], 20)
data["EMA50"] = compute_ema(data["Close"], 50)
data["RSI"]   = compute_rsi_wilder(data["Close"])
data["VWAP"]  = compute_vwap_intraday(data)
data["ATR"]   = compute_atr(data)

# Rolling 20-bar high / low (for proper breakout detection)
data["Roll20H"] = data["High"].rolling(20).max()
data["Roll20L"] = data["Low"].rolling(20).min()

# Drop rows where indicators aren't ready
# data = data.dropna(subset=["EMA20", "EMA50", "RSI", "VWAP", "ATR"])
data = data.dropna(subset=["EMA50"]).copy()

if len(data) < 3:
    st.warning("⏳ Indicators still warming up — needs a few more bars.")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# LATEST SNAPSHOT
# ─────────────────────────────────────────────────────────────────────────────
latest = data.iloc[-1]
prev   = data.iloc[-2]

price      = float(latest["Close"])
atr        = float(latest["ATR"])
rsi        = float(latest["RSI"])
ema20      = float(latest["EMA20"])
ema50      = float(latest["EMA50"])
vwap       = float(latest["VWAP"])
roll20h    = float(latest["Roll20H"])
roll20l    = float(latest["Roll20L"])

change_5m     = price - float(prev["Close"])
change_5m_pct = change_5m / float(prev["Close"]) * 100

# Regime: if price range of last 20 bars < 0.4% → sideways
recent_range_pct = (roll20h - roll20l) / price
regime = "SIDEWAYS / No Clear Direction" if recent_range_pct < 0.004 else "TRENDING"

# Breakout / breakdown vs. 20-bar rolling levels (exclude current bar)
roll20h_prev = float(data["Roll20H"].iloc[-2])
roll20l_prev = float(data["Roll20L"].iloc[-2])
bullish_breakout  = price > roll20h_prev
bearish_breakdown = price < roll20l_prev

# ─────────────────────────────────────────────────────────────────────────────
# PCR
# ─────────────────────────────────────────────────────────────────────────────
pcr = load_pcr()

# ─────────────────────────────────────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────────────────────────────────────
score   = 0
reasons = []          # (text, direction)  direction: "bull" | "bear" | "neut"
max_possible = 0

# 1. EMA trend  ±2
max_possible += 2
if ema20 > ema50:
    score += 2
    reasons.append(("EMA20 > EMA50 — uptrend", "bull"))
else:
    score -= 2
    reasons.append(("EMA20 < EMA50 — downtrend", "bear"))

# 2. RSI (Wilder)  ±1
max_possible += 1
if rsi > 55:
    score += 1
    reasons.append((f"RSI {rsi:.1f} — momentum strong", "bull"))
elif rsi < 45:
    score -= 1
    reasons.append((f"RSI {rsi:.1f} — momentum weak", "bear"))
else:
    reasons.append((f"RSI {rsi:.1f} — neutral zone", "neut"))

# 3. Price vs VWAP  ±2
max_possible += 2
if price > vwap:
    score += 2
    reasons.append(("Price above intraday VWAP", "bull"))
else:
    score -= 2
    reasons.append(("Price below intraday VWAP", "bear"))

# 4. PCR (calibrated bands for NIFTY)  ±1
max_possible += 1
if pcr is not None:
    if 0.85 <= pcr <= 1.15:
        # neutral healthy range
        reasons.append((f"PCR {pcr:.2f} — neutral", "neut"))
    elif pcr > 1.3:
        # extreme put buying — can be panic hedging (bearish market)
        score -= 1
        reasons.append((f"PCR {pcr:.2f} — extreme hedging (bearish signal)", "bear"))
    elif pcr > 1.15:
        score += 1
        reasons.append((f"PCR {pcr:.2f} — moderate bullish bias", "bull"))
    elif pcr < 0.7:
        # extreme call buying — complacency / possible top
        score -= 1
        reasons.append((f"PCR {pcr:.2f} — extreme call buying (bearish signal)", "bear"))
    else:
        score -= 1
        reasons.append((f"PCR {pcr:.2f} — bearish bias", "bear"))
else:
    max_possible -= 1  # don't penalise confidence for missing PCR

# 5. Breakout confirmation filter (not a score — a gate)
filters_passed = True
filter_notes   = []

if regime == "SIDEWAYS":
    filters_passed = False
    filter_notes.append(("Sideways regime — no directional edge", "neut"))

if atr < price * 0.004:   # 0.4% of price — realistic NIFTY threshold
    filters_passed = False
    filter_notes.append(("Low volatility (ATR < 0.4%) — avoid", "neut"))

if score > 0 and not bullish_breakout:
    filters_passed = False
    filter_notes.append(("Bullish score but no 20-bar breakout — wait", "neut"))

if score < 0 and not bearish_breakdown:
    filters_passed = False
    filter_notes.append(("Bearish score but no 20-bar breakdown — wait", "neut"))

reasons.extend(filter_notes)

# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL
# ─────────────────────────────────────────────────────────────────────────────
if not filters_passed:
    signal    = "⚪  WAIT"
    sig_class = "neutral"
elif score >= 4:
    signal    = "🟢  STRONG BUY"
    sig_class = "bullish"
elif score >= 2:
    signal    = "🟢  BUY"
    sig_class = "bullish"
elif score <= -4:
    signal    = "🔴  STRONG SELL"
    sig_class = "bearish"
elif score <= -2:
    signal    = "🔴  SELL"
    sig_class = "bearish"
else:
    signal    = "⚪  WAIT"
    sig_class = "neutral"

confidence = (abs(score) / max_possible * 100) if max_possible > 0 else 0



# ─────────────────────────────────────────────────────────────────────────────
# WHAT CHANGED INSIGHT
# ─────────────────────────────────────────────────────────────────────────────
what_changed = ""

if bullish_breakout and price > vwap:
    what_changed = "Breakout above recent highs + price above VWAP"
elif bearish_breakdown and price < vwap:
    what_changed = "Breakdown below recent lows + price below VWAP"
elif price > vwap:
    what_changed = "Price holding above VWAP (buyers active)"
elif price < vwap:
    what_changed = "Price below VWAP (sellers active)"

if what_changed:
    st.markdown(f"""
    <p style="font-size:0.9rem;color:#9ca3af;margin-top:-0.4rem;margin-bottom:0.6rem">
    🧠 <b>What changed:</b> {what_changed}
    </p>
    """, unsafe_allow_html=True)


# ── ACTION CONTEXT ───────────────────────────────────────────────────
action_note = ""

if sig_class == "bullish":
    action_note = "Momentum building — early entry opportunity"
elif sig_class == "bearish":
    action_note = "Downside pressure increasing — short setups favorable"
else:
    action_note = "No clear edge — avoid low-quality trades"

st.markdown(f"""
<p style="font-size:0.85rem;color:#6b7280;margin-top:-0.5rem;margin-bottom:0.8rem">
{action_note}
</p>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY / SL / TARGET (ATR-based, 1.5R)
# ─────────────────────────────────────────────────────────────────────────────
entry  = round(price, 2)
if sig_class == "bullish":
    sl     = round(price - 1.5 * atr, 2)
    target = round(price + 2.25 * atr, 2)   # 1.5R = reward 1.5× the risk
elif sig_class == "bearish":
    sl     = round(price + 1.5 * atr, 2)
    target = round(price - 2.25 * atr, 2)
else:
    sl     = None
    target = None

risk   = abs(entry - sl)   if sl     else None
reward = abs(target - entry) if target else None
rr_str = f"{reward / risk:.1f}R" if (risk and risk > 0) else "—"

# ─────────────────────────────────────────────────────────────────────────────
# CANDLE ANALYSIS (kept but demoted to expander)
# ─────────────────────────────────────────────────────────────────────────────
o, c, h, l_ = float(latest["Open"]), float(latest["Close"]), float(latest["High"]), float(latest["Low"])
body         = abs(c - o)
rng          = h - l_ if (h - l_) > 0 else 1e-9
upper_wick   = h - max(o, c)
lower_wick   = min(o, c) - l_

body_pct       = body / rng * 100
upper_wick_pct = upper_wick / rng * 100
lower_wick_pct = lower_wick / rng * 100

if body_pct < 20:
    candle_type = "Doji (indecision)"
elif c > o and body_pct > 60:
    candle_type = "Strong bullish"
elif c < o and body_pct > 60:
    candle_type = "Strong bearish"
elif lower_wick > body * 2 and upper_wick < body:
    candle_type = "Hammer"
elif upper_wick > body * 2 and lower_wick < body:
    candle_type = "Shooting star"
else:
    candle_type = "Normal"

prev_o, prev_c = float(prev["Open"]), float(prev["Close"])
if prev_c < prev_o and c > o and c > prev_o and o < prev_c:
    candle_pattern = "Bullish engulfing"
elif prev_c > prev_o and c < o and o > prev_c and c < prev_o:
    candle_pattern = "Bearish engulfing"
else:
    candle_pattern = None

# ─────────────────────────────────────────────────────────────────────────────
# CHART
# ─────────────────────────────────────────────────────────────────────────────
def build_chart(df: pd.DataFrame, price_now: float, vwap_now: float) -> go.Figure:
    fig = go.Figure()

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],  close=df["Close"],
        name="NIFTY",
        increasing_line_color="#3ddc84",
        decreasing_line_color="#ff6b6b",
        increasing_fillcolor="#0d3d1e",
        decreasing_fillcolor="#3d0d0d",
    ))

    # EMAs
    fig.add_trace(go.Scatter(
        x=df.index, y=df["EMA20"],
        line=dict(color="#60a5fa", width=1.2),
        name="EMA 20",
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["EMA50"],
        line=dict(color="#f59e0b", width=1.2),
        name="EMA 50",
    ))

    # VWAP
    fig.add_trace(go.Scatter(
        x=df.index, y=df["VWAP"],
        line=dict(color="#c084fc", width=1.4, dash="dot"),
        name="VWAP",
    ))

    # Current price horizontal line
    fig.add_hline(
        y=price_now,
        line=dict(color="#e5e7eb", width=0.8, dash="dash"),
        annotation_text=f"  {price_now:,.2f}",
        annotation_position="right",
        annotation_font=dict(color="#e5e7eb", size=11),
    )

    # 20-bar high/low bands (context for breakout)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Roll20H"],
        line=dict(color="#3ddc84", width=0.6, dash="dot"),
        name="20-bar High",
        opacity=0.5,
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Roll20L"],
        line=dict(color="#ff6b6b", width=0.6, dash="dot"),
        name="20-bar Low",
        opacity=0.5,
    ))

    fig.update_layout(
        height=420,
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font=dict(color="#e5e7eb", size=11),
        xaxis=dict(
            rangeslider=dict(visible=False),
            gridcolor="#1e2433",
            showgrid=True,
            type="date",
        ),
        yaxis=dict(
            gridcolor="#1e2433",
            showgrid=True,
            tickformat=",.0f",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.01,
            xanchor="right",  x=1,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=10),
        ),
        margin=dict(l=0, r=60, t=30, b=0),
        hovermode="x unified",
    )
    return fig

# ─────────────────────────────────────────────────────────────────────────────
# ██████████████████████  UI  ██████████████████████
# ─────────────────────────────────────────────────────────────────────────────

# ── 1. SIGNAL HERO CARD ──────────────────────────────────────────────────────
conf_bar_pct = min(int(confidence), 100)
bar_class = sig_class if sig_class != "neutral" else "neut"

st.markdown(f"""
<div class="signal-card {sig_class}">
  <div>
    <div class="signal-label {sig_class}">{signal}</div>
    <div class="signal-conf">Signal Strength: {confidence:.0f}% &nbsp;|&nbsp; Score: {score:+d} / {max_possible} &nbsp;|&nbsp; Market: {regime}</div>
    # <div class="signal-conf">Confidence: {confidence:.0f}% &nbsp;|&nbsp; Score: {score:+d} / {max_possible} &nbsp;|&nbsp; Regime: {regime}</div>
  </div>
  <div style="min-width:180px;">
    <div class="score-bar-wrap">
      <div class="score-bar-bg">
        <div class="score-bar-fill {bar_class}" style="width:{conf_bar_pct}%"></div>
      </div>
      <span style="font-size:0.8rem;color:#aaa;white-space:nowrap">{conf_bar_pct}%</span>
    </div>
    <div style="font-size:0.75rem;color:#6b7280;text-align:right">NIFTY {price:,.2f} &nbsp;
      {'▲' if change_5m >= 0 else '▼'} {change_5m:+.2f} ({change_5m_pct:+.2f}%) 5-min
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── 2. ENTRY / SL / TARGET LEVELS ────────────────────────────────────────────
if sig_class in ("bullish", "bearish"):
    st.markdown(f"""
    <div class="levels-row">
      <div class="level-box">
        <div class="level-label">Entry (CMP)</div>
        <div class="level-value entry">{entry:,.2f}</div>
      </div>
      <div class="level-box">
        <div class="level-label">Stop-Loss</div>
        <div class="level-value sl">{sl:,.2f}</div>
      </div>
      <div class="level-box">
        <div class="level-label">Target</div>
        <div class="level-value target">{target:,.2f}</div>
      </div>
      <div class="level-box">
        <div class="level-label">Risk / Reward</div>
        <div class="level-value rr">{rr_str}</div>
      </div>
      <div class="level-box">
        <div class="level-label">ATR (1 bar)</div>
        <div class="level-value entry">{atr:,.2f}</div>
      </div>
    </div>
    <p style="font-size:0.72rem;color:#6b7280;margin:-0.2rem 0 0.8rem">
      SL = 1.5× ATR from entry &nbsp;·&nbsp; Target = 1.5× risk (2.25× ATR) &nbsp;·&nbsp; Adjust per your own risk tolerance
    </p>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <p style="color:#6b7280;font-size:0.85rem;margin:0 0 0.8rem">
      No active signal — entry/SL/target levels will appear when a BUY or SELL triggers.
    </p>""", unsafe_allow_html=True)

# ── 3. CHART ─────────────────────────────────────────────────────────────────
st.plotly_chart(build_chart(data, price, vwap), use_container_width=True)

# ── 4. CONTEXT METRICS ROW ───────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("NIFTY", f"{price:,.2f}", f"{change_5m_pct:+.2f}%")
c2.metric("RSI (Wilder)", f"{rsi:.1f}", help="Overbought >70 · Oversold <30 · Signal uses 55/45")
c3.metric("VWAP", f"{vwap:,.2f}", f"{'Above ✓' if price > vwap else 'Below ✗'}")
c4.metric("EMA 20 / 50", f"{ema20:,.1f} / {ema50:,.1f}", f"{'Bull ✓' if ema20 > ema50 else 'Bear ✗'}")
c5.metric("ATR (5-min)", f"{atr:,.2f}", f"{atr/price*100:.2f}% of price")
pcr_display = f"{pcr:.2f}" if pcr else "N/A"
c6.metric("PCR", pcr_display, help="0.85–1.15 neutral · >1.3 panic hedge · <0.7 complacency")

if pcr is None:
    if not NSE_AVAILABLE:
        st.caption("⚠️ nsepython not installed — PCR unavailable. Run: `pip install nsepython`")
    else:
        st.caption("⚠️ NSE option chain unavailable right now — PCR excluded from score")

# ── 5. SIGNAL REASONS ────────────────────────────────────────────────────────
st.markdown("**Why this signal?**")
pills_html = ""
for text, direction in reasons:
    pills_html += f'<span class="reason-pill {direction}">{text}</span>'
st.markdown(pills_html, unsafe_allow_html=True)

st.markdown("<div style='margin-top:0.3rem'></div>", unsafe_allow_html=True)

# ── 6. CANDLE DETAIL (collapsed — for those who want it) ─────────────────────
with st.expander("🕯️ Last 5-min Candle Story Detail (click to expand)"):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Candle type", candle_type)
        st.metric("Pattern", candle_pattern or "None")
        st.metric("Body %", f"{body_pct:.1f}%")
    with col_b:
        st.metric("Upper wick %", f"{upper_wick_pct:.1f}%")
        st.metric("Lower wick %", f"{lower_wick_pct:.1f}%")
        st.metric("Candle range", f"{rng:.2f}")
    with col_c:
        st.metric("Open", f"{o:,.2f}")
        st.metric("High", f"{h:,.2f}")
        st.metric("Low", f"{l_:,.2f}")


def generate_day_summary(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["date"] = df.index.date

    today = df["date"].iloc[-1]
    yesterday = df["date"].iloc[-2]

    today_df = df[df["date"] == today]
    yest_df  = df[df["date"] == yesterday]

    # ── BASIC NUMBERS ─────────────────────────────────────────────
    open_price  = today_df["Open"].iloc[0]
    close_price = today_df["Close"].iloc[-1]
    high_price  = today_df["High"].max()
    low_price   = today_df["Low"].min()

    change_pct = (close_price - open_price) / open_price * 100
    range_pct  = (high_price - low_price) / close_price * 100

    # ── TREND ────────────────────────────────────────────────────
    if change_pct > 0.3:
        trend = "uptrend"
    elif change_pct < -0.3:
        trend = "downtrend"
    else:
        trend = "sideways"

    # ── VOLATILITY ───────────────────────────────────────────────
    if range_pct > 1.2:
        volatility = "high volatility"
    elif range_pct > 0.6:
        volatility = "moderate movement"
    else:
        volatility = "low volatility"

    # ── CONTROL (VWAP based) ─────────────────────────────────────
    last_close = today_df["Close"].iloc[-1]
    last_vwap  = today_df["VWAP"].iloc[-1]

    if last_close > last_vwap:
        control = "buyers in control"
    else:
        control = "sellers in control"

    # ── YESTERDAY COMPARISON ─────────────────────────────────────
    y_open  = yest_df["Open"].iloc[0]
    y_close = yest_df["Close"].iloc[-1]
    y_change = (y_close - y_open) / y_open * 100

    if (change_pct > 0 and y_change > 0) or (change_pct < 0 and y_change < 0):
        continuation = "trend continued from yesterday"
    else:
        continuation = "trend changed vs yesterday"

    # ── KEY MOVE (simple logic) ──────────────────────────────────
    if close_price > yest_df["High"].max():
        key_move = "strong breakout above yesterday’s high"
    elif close_price < yest_df["Low"].min():
        key_move = "breakdown below yesterday’s low"
    else:
        key_move = "no major breakout — range-bound behaviour"

    # ── TOMORROW CONTEXT ─────────────────────────────────────────
    if trend == "uptrend" and control == "buyers in control":
        outlook = "bullish bias — dips may get bought"
    elif trend == "downtrend" and control == "sellers in control":
        outlook = "bearish bias — rallies may get sold"
    else:
        outlook = "mixed signals — wait for clear direction"

    return {
        "trend": trend,
        "change_pct": change_pct,
        "range_pct": range_pct,
        "volatility": volatility,
        "control": control,
        "continuation": continuation,
        "key_move": key_move,
        "outlook": outlook,
        "high": high_price,
        "low": low_price,
        "close": close_price
    }


day_summary = generate_day_summary(data)


# ── Summary ─────────────────────────────────────────────────────────────────

# if not is_market_hours:
#     s = day_summary

#     st.markdown("### 🧾 Day Summary")

#     st.markdown(f"""
#     # <div style="background:#1f2937;padding:14px 18px;border-radius:12px;border:1px solid #2a3040">
#     <div style="background:#111827;padding:14px 18px;border-radius:12px;border:1px solid #2a3040;color:#ffffff;">

#     <b>📊 Market Behaviour:</b><br>
#     {s['trend'].capitalize()} ({s['change_pct']:.2f}%) · Range: {s['range_pct']:.2f}% · {s['volatility']}<br><br>

#     <b>⚡ Key Move:</b><br>
#     {s['key_move']}<br><br>

#     <b>🧠 Control:</b><br>
#     {s['control']} · Close: {s['close']:.0f} · Day High: {s['high']:.0f} · Day Low: {s['low']:.0f}<br><br>

#     <b>🔁 Context:</b><br>
#     {s['continuation']}<br><br>

#     <b>🔮 Tomorrow:</b><br>
#     {s['outlook']}

#     </div>
#     """, unsafe_allow_html=True)

if not is_market_hours:
    s = day_summary

    st.markdown("### 🧾 Market Summary (Trader View)")

    st.markdown(f"""
<div style="background:#111827;padding:16px 20px;border-radius:12px;border:1px solid #2a3040;color:#ffffff;line-height:1.7;font-size:1.02rem">

<b>📊 Day Structure:</b><br>
Closed {s['trend']} with {s['change_pct']:.2f}% move.  
Range: {s['range_pct']:.2f}% → {s['volatility']}.<br><br>

<b>⚡ Key Action:</b><br>
{s['key_move']} (compared to yesterday’s range).<br><br>

<b>🧠 Market Control:</b><br>
{s['control']}.  
Close at <b>{s['close']:.0f}</b> vs Day High <b>{s['high']:.0f}</b> / Low <b>{s['low']:.0f}</b>.<br><br>

<b>📍 Structure Context:</b><br>
{s['continuation']}.  
This confirms whether momentum carried from yesterday or flipped.<br><br>

<b>🔮 Tomorrow Setup:</b><br>
{s['outlook']}.

</div>
""", unsafe_allow_html=True)



# ── 7. FOOTER ────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "📌 For market reading only — not financial advice. "
    "Always paper-trade a setup before going live. "
    "Signals are based on 5-min bars; refresh lag is ≤30s."
)







