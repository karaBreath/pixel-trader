"""
dashboard.py — หน้าเว็บ Dashboard สไตล์ pixel agent (ฟรี ไม่ใช้ API key)
แสดงผลร่อนหุ้น + ข้อมูลรายตัว + กราฟ บนเบราว์เซอร์

วิธีเปิด:
    "d:\\coword trader\\TradingAgents\\.venv\\Scripts\\streamlit.exe" run dashboard.py
    (หรือใช้: python -m streamlit run dashboard.py)
แล้วเปิดเบราว์เซอร์ที่ http://localhost:8501

หมายเหตุ: ส่วน "วิเคราะห์เชิงลึกหลาย AI" ทำผ่าน Claude (พิมพ์ /analyze TICKER ในแชต)
Dashboard นี้ทำส่วนข้อมูล+ร่อนหุ้น+กราฟ
"""

import shutil
import subprocess
import warnings
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from stockstats import wrap as ss_wrap

from patterns import technical_report_th

try:
    from deep_translator import GoogleTranslator
    _HAS_TR = True
except Exception:
    _HAS_TR = False


def build_deep_prompt(ticker, d):
    """ประกอบ prompt ส่งให้ Claude วิเคราะห์เชิงลึกหลายมุม"""
    hist, info, news = d["hist"], d["info"], d["news"]
    close = float(hist["Close"].iloc[-1])
    stock = ss_wrap(hist.copy())

    def g(c):
        v = ind(stock, c)
        return f"{v:.2f}" if v is not None else "n/a"

    heads = []
    for it in news[:8]:
        c = it.get("content", it)
        ti = c.get("title") or it.get("title")
        if ti:
            heads.append(f"- {ti}")
    news_txt = "\n".join(heads) or "(ไม่มีข่าว)"

    def f(v, suf=""):
        return f"{v}{suf}" if v not in (None, "") else "n/a"

    return f"""คุณคือทีมนักวิเคราะห์การลงทุน วิเคราะห์ {info.get('shortName', ticker)} ({ticker}) จากข้อมูลจริงด้านล่าง
โดยสวม 4 บทบาทคิดแยกกัน แล้วสรุปเป็นคำตัดสินสุดท้าย ตอบเป็นภาษาไทยทั้งหมด

[ข้อมูลราคา/เทคนิค]
- ราคาล่าสุด: {close:.2f} {info.get('currency','')}
- ช่วง 52 สัปดาห์: {hist['Close'].min():.2f} - {hist['Close'].max():.2f}
- SMA50={g('close_50_sma')} SMA200={g('close_200_sma')} EMA10={g('close_10_ema')}
- RSI(14)={g('rsi_14')} MACD={g('macd')} MACD Signal={g('macds')} Hist={g('macdh')}
- Bollinger: บน={g('boll_ub')} กลาง={g('boll')} ล่าง={g('boll_lb')} ATR={g('atr')}

[ปัจจัยพื้นฐาน]
- P/E={f(info.get('trailingPE'))} Forward P/E={f(info.get('forwardPE'))} P/B={f(info.get('priceToBook'))}
- EPS={f(info.get('trailingEps'))} อัตรากำไรสุทธิ={f(info.get('profitMargins'))} ROE={f(info.get('returnOnEquity'))}
- การเติบโตรายได้={f(info.get('revenueGrowth'))} หนี้/ทุน={f(info.get('debtToEquity'))}
- เป้านักวิเคราะห์={f(info.get('targetMeanPrice'))} คำแนะนำ={f(info.get('recommendationKey'))}

[สัญญาณเทคนิคขั้นสูง]
{technical_report_th(hist)}

[ข่าวล่าสุด]
{news_txt}

ให้ผลลัพธ์รูปแบบนี้ (กระชับ):
## 👥 4 มุมมอง
- 🔵 เทคนิค: ... (จบด้วย ซื้อ/รอ/ขาย)
- 🟢 พื้นฐาน: ... (จบด้วย น่าลงทุน/กลางๆ/แพงเกิน)
- 🟡 ข่าว/อารมณ์: ... (จบด้วย บวก/กลาง/ลบ)
- 🔴 ฝ่ายค้าน: ... (ความเสี่ยงร้ายแรงสุด 1 ข้อ)
## ⭐ คำตัดสินสุดท้าย
- เรตติ้ง: ซื้อ / ทยอยสะสม / ถือ-รอ / ขาย
- ระดับราคา: แนวรับ ... / แนวต้าน ... / จุดตัดขาดทุน ... / เป้า ...
- สรุป 1-2 บรรทัด
ปิดท้าย: "⚠️ เพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน"
อย่าแต่งตัวเลขเกินจากที่ให้"""


def run_claude(prompt, timeout=300):
    """เรียก Claude Code headless (ฟรี ใช้ล็อกอินเดิม) คืนผลวิเคราะห์"""
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-p"], input=prompt, capture_output=True,
                           text=True, encoding="utf-8", timeout=timeout)
        return r.stdout.strip() or None
    except Exception:
        return None


def reco_gauge(sellness):
    """วาดหน้าปัดแบบมาตรวัดรถ — ซ้าย=ซื้อ กลาง=ถือ ขวา=ขาย (เข็มชี้ที่ sellness 0-100)"""
    fig = go.Figure(go.Indicator(
        mode="gauge",
        value=sellness,
        gauge={
            "axis": {"range": [0, 100], "tickvals": [10, 50, 90],
                     "ticktext": ["ซื้อ", "ถือ", "ขาย"],
                     "tickfont": {"size": 18, "color": "#e0e0ff"}},
            "bar": {"color": "rgba(0,0,0,0)"},  # ซ่อนแถบ ใช้เข็มแทน
            "borderwidth": 0,
            "steps": [
                {"range": [0, 33], "color": "#2ecc71"},    # เขียว = ซื้อ
                {"range": [33, 66], "color": "#f1c40f"},    # เหลือง = ถือ
                {"range": [66, 100], "color": "#e74c3c"},   # แดง = ขาย
            ],
            "threshold": {"line": {"color": "#ffffff", "width": 7},
                          "thickness": 1, "value": sellness},
        },
    ))
    fig.update_layout(height=250, margin=dict(t=20, b=10, l=40, r=40),
                      paper_bgcolor="rgba(0,0,0,0)", font={"color": "#e0e0ff"})
    return fig


def gauge_label(sellness):
    if sellness < 30:
        return "🟢 ซื้อ / ทยอยสะสม"
    if sellness < 45:
        return "🟢 เอนไปทางซื้อ"
    if sellness < 55:
        return "🟡 ถือ / รอจังหวะ"
    if sellness < 70:
        return "🟠 ระวัง / ทยอยลดได้"
    return "🔴 ขาย / หลีกเลี่ยง"


def _get_secret(name):
    """อ่าน secret อย่างปลอดภัย (ไม่พังถ้าไม่มีไฟล์ secrets)"""
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def call_gemini(prompt):
    """เรียก Google Gemini (free tier) — ใช้ st.secrets['GEMINI_API_KEY'] บนคลาวด์"""
    key = _get_secret("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return (resp.text or "").strip() or None
    except Exception:
        return None


def rule_based_analysis(ticker, d):
    """สรุปอัตโนมัติจากตัวเลข (ไม่ใช้ AI) — ใช้บนคลาวด์/เครื่องที่ไม่มี Claude"""
    hist, info = d["hist"], d["info"]
    close = float(hist["Close"].iloc[-1])
    stock = ss_wrap(hist.copy())
    sma50, sma200 = ind(stock, "close_50_sma"), ind(stock, "close_200_sma")
    ema10, rsi = ind(stock, "close_10_ema"), ind(stock, "rsi_14")
    macdh = ind(stock, "macdh")
    hi, lo = float(hist["Close"].max()), float(hist["Close"].min())

    pos = 0  # นับคะแนนบวกรวมเพื่อสรุปเรตติ้ง

    # 🔵 เทคนิค
    above = sum(1 for x in (sma50, sma200) if x and close > x)
    if above == 2:
        tech, tsig = "ราคาเหนือ SMA50 และ SMA200 = แนวโน้มขาขึ้น", "ซื้อ/ตามเทรนด์"; pos += 1
    elif above == 0:
        tech, tsig = "ราคาต่ำกว่าเส้นค่าเฉลี่ย = แนวโน้มขาลง", "ขาย/หลีกเลี่ยง"; pos -= 1
    else:
        tech, tsig = "ราคาก้ำกึ่งเส้นค่าเฉลี่ย", "รอ"
    if rsi is not None:
        tech += f" · RSI {rsi:.0f}" + (" (สูง-ระวัง)" if rsi > 70 else " (ต่ำ-อาจ oversold)" if rsi < 30 else " (ปกติ)")
    if ema10 and close < ema10:
        tech += " · ระยะสั้นอ่อนแรง (ใต้ EMA10)"
    if macdh is not None and macdh < 0:
        tech += " · MACD โมเมนตัมลบ"

    # 🟢 พื้นฐาน
    fpe = info.get("forwardPE") or info.get("trailingPE")
    rg = info.get("revenueGrowth")
    roe = info.get("returnOnEquity")
    tgt = info.get("targetMeanPrice")
    upside = ((tgt - close) / close * 100) if tgt else None
    fund = []
    if fpe and fpe < 0:
        fund.append("⚠️ Forward P/E ติดลบ (ตลาดคาดขาดทุน)"); pos -= 1
    elif fpe:
        fund.append(f"P/E {fpe:.0f}" + (" (ถูก)" if fpe < 20 else " (สูง)" if fpe > 40 else " (กลางๆ)"))
        if fpe < 25: pos += 1
        if fpe > 50: pos -= 1
    if rg is not None:
        fund.append(f"รายได้โต {rg*100:.0f}%")
        if rg > 0.2: pos += 1
    if roe is not None:
        fund.append(f"ROE {roe*100:.0f}%")
        if roe > 0.2: pos += 1
    if upside is not None:
        fund.append(f"เป้านักวิเคราะห์ห่าง {upside:+.0f}%")
        if upside > 15: pos += 1
        if upside < -5: pos -= 1
    fund_txt = " · ".join(fund) or "ข้อมูลพื้นฐานจำกัด (อาจเป็นคริปโต/ทอง)"

    # 🔴 ความเสี่ยง
    risks = []
    if fpe and (fpe > 50 or fpe < 0): risks.append("มูลค่าแพง/กำไรไม่ชัด")
    if close > hi * 0.97: risks.append("ใกล้จุดสูงสุด 52 สัปดาห์ (อัพไซด์อาจจำกัด)")
    if close < lo * 1.05: risks.append("ใกล้จุดต่ำสุด 52 สัปดาห์ (เสี่ยงลงต่อ)")
    atr = ind(stock, "atr")
    if atr and atr / close > 0.06: risks.append(f"ผันผวนสูง (ATR {atr/close*100:.0f}% ของราคา)")
    risk_txt = " · ".join(risks) or "ไม่พบความเสี่ยงเด่นจากตัวเลข"

    # ⭐ เรตติ้ง
    if pos >= 3: rating = "ทยอยสะสม / ซื้อ"
    elif pos >= 1: rating = "ถือ-รอจังหวะ (เอนบวก)"
    elif pos <= -2: rating = "หลีกเลี่ยง / ขาย"
    else: rating = "ถือ-รอ (ก้ำกึ่ง)"

    support = f"{sma50:.2f}" if sma50 else "—"
    support2 = f"{sma200:.2f}" if sma200 else "—"
    resist = f"{ema10:.2f}" if ema10 else "—"

    return f"""## 👥 สรุปหลายมุม (อัตโนมัติจากตัวเลข)
- 🔵 **เทคนิค:** {tech} → _{tsig}_
- 🟢 **พื้นฐาน:** {fund_txt}
- 🔴 **ความเสี่ยง:** {risk_txt}

## ⭐ คำตัดสิน (rule-based)
- **เรตติ้ง: {rating}**
- ระดับราคา: แนวรับ {support} → {support2} / แนวต้าน {resist} / จุดสูงสุด52สัปดาห์ {hi:.2f}
- ราคาปัจจุบัน {close:.2f}

> 📊 นี่คือ "สรุปอัตโนมัติตามสูตร" (ไม่ใช่ AI คิดเอง) — เปิดในเครื่องที่ล็อกอิน Claude Code จะได้ AI วิเคราะห์เชิงลึกจริง
> ⚠️ เพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน"""

# ---------- จักรวาลหุ้น + น้ำหนักสไตล์ (ตรงกับ screen.py) ----------
UNIVERSE = {
    "us": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "PLTR",
           "AMD", "AVGO", "ORCL", "NFLX", "CRM", "JPM", "JNJ", "KO", "PG",
           "XOM", "CVX", "WMT", "HD", "VZ", "PFE", "INTC", "COST", "ABBV"],
    "th": ["PTT.BK", "KBANK.BK", "CPALL.BK", "AOT.BK", "SCB.BK", "ADVANC.BK",
           "GULF.BK", "DELTA.BK", "BDMS.BK", "PTTEP.BK", "SCC.BK", "BBL.BK"],
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD"],
    "gold": ["GLD", "IAU", "GC=F", "SLV"],
}
STYLE_WEIGHTS = {
    "สมดุล":     (0.25, 0.15, 0.20, 0.20, 0.20, 0.00),
    "เติบโต":    (0.25, 0.00, 0.35, 0.20, 0.20, 0.00),
    "มูลค่า/ถูก": (0.20, 0.35, 0.00, 0.20, 0.25, 0.00),
    "โมเมนตัม":  (0.65, 0.00, 0.15, 0.20, 0.00, 0.00),
    "ปันผล":     (0.10, 0.20, 0.00, 0.00, 0.30, 0.40),
}


def score_band(x, bands):
    if x is None:
        return None
    for th, pts in bands:
        if x >= th:
            return pts
    return bands[-1][1]


def ind(stock, col):
    try:
        v = stock[col].iloc[-1]
        return None if v != v else float(v)
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def analyze(ticker):
    """ดึง+ให้คะแนน 1 ตัว (cache 15 นาที)"""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y", auto_adjust=True)
        if hist is None or hist.empty or len(hist) < 30:
            return None
        close = float(hist["Close"].iloc[-1])
        stock = ss_wrap(hist.copy())
        sma50, sma200 = ind(stock, "close_50_sma"), ind(stock, "close_200_sma")
        ema10, rsi = ind(stock, "close_10_ema"), ind(stock, "rsi_14")
        mom3 = None
        if len(hist) > 63:
            past = float(hist["Close"].iloc[-63])
            mom3 = (close - past) / past * 100 if past else None

        parts = []
        if ema10 is not None: parts.append(100 if close > ema10 else 0)
        if sma50 is not None: parts.append(100 if close > sma50 else 0)
        if sma200 is not None: parts.append(100 if close > sma200 else 0)
        if sma50 and sma200: parts.append(100 if sma50 > sma200 else 0)
        if mom3 is not None:
            parts.append(score_band(mom3, [(20, 100), (10, 80), (0, 60), (-10, 35), (-100, 15)]))
        trend = sum(parts) / len(parts) if parts else None

        info = t.info or {}
        fpe = info.get("forwardPE") or info.get("trailingPE")
        value = score_band(-fpe, [(-15, 100), (-25, 80), (-40, 55), (-70, 30), (-1e9, 10)]) if fpe and fpe > 0 else None
        rg = info.get("revenueGrowth")
        growth = score_band(rg * 100, [(40, 100), (20, 80), (10, 60), (0, 40), (-100, 10)]) if rg is not None else None
        tgt = info.get("targetMeanPrice")
        up = ((tgt - close) / close * 100) if tgt else None
        upside = score_band(up, [(30, 100), (15, 80), (5, 60), (-5, 40), (-1e9, 20)]) if up is not None else None
        roe = info.get("returnOnEquity")
        quality = score_band(roe * 100, [(25, 100), (15, 75), (8, 50), (0, 30), (-1e9, 10)]) if roe is not None else None
        dy = info.get("dividendYield")
        dividend = score_band(dy, [(4, 100), (2, 75), (1, 50), (0.01, 30), (-1, 0)]) if dy is not None else None

        return {
            "ticker": ticker, "name": (info.get("shortName") or ticker)[:22],
            "close": close, "rsi": rsi, "mom3": mom3, "fpe": fpe,
            "rev_g": rg * 100 if rg is not None else None, "upside": up,
            "roe": roe * 100 if roe is not None else None, "dy": dy,
            "scores": {"trend": trend, "value": value, "growth": growth,
                       "upside": upside, "quality": quality, "dividend": dividend},
        }
    except Exception:
        return None


def composite(scores, w):
    keys = ["trend", "value", "growth", "upside", "quality", "dividend"]
    num = den = 0.0
    for k, wi in zip(keys, w):
        s = scores.get(k)
        if s is not None and wi > 0:
            num += s * wi; den += wi
    return round((num / den) if den else (scores.get("trend") or 0), 1)


@st.cache_data(ttl=86400, show_spinner=False)
def to_thai(text):
    """แปลข้อความเป็นไทย (ฟรี) — cache 1 วัน, แปลไม่ได้คืนต้นฉบับ"""
    if not text or not _HAS_TR:
        return text
    try:
        return GoogleTranslator(source="auto", target="th").translate(text[:480]) or text
    except Exception:
        return text


@st.cache_data(ttl=900, show_spinner=False)
def detail(ticker):
    """ข้อมูลเจาะลึก 1 ตัว สำหรับหน้ารายตัว"""
    t = yf.Ticker(ticker)
    hist = t.history(period="1y", auto_adjust=True)
    if hist is None or hist.empty:
        return None
    info = t.info or {}
    try:
        news = t.news or []
    except Exception:
        news = []
    return {"hist": hist, "info": info, "news": news}


# ===================== UI =====================
st.set_page_config(page_title="Pixel Trader Agent", page_icon="👾", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap');
.stApp { background: #0d0221; color: #e0e0ff; }
h1, h2, h3 { font-family: 'Press Start 2P', monospace !important; color: #39ff14 !important;
             text-shadow: 2px 2px #ff2079; }
.pixel-box { border: 3px solid #39ff14; border-radius: 0; padding: 14px;
             background: #1a0938; box-shadow: 4px 4px 0 #ff2079; margin-bottom: 12px; }
.big { font-family: 'VT323', monospace; font-size: 1.4rem; }
section[data-testid="stSidebar"] { background: #1a0938; border-right: 3px solid #ff2079; }
.stButton button { font-family: 'Press Start 2P', monospace; background: #ff2079; color: #fff;
                   border: 2px solid #39ff14; border-radius: 0; }
</style>
""", unsafe_allow_html=True)

st.markdown("# 👾 PIXEL TRADER AGENT")
st.markdown("<div class='big'>ผู้ช่วยร่อนหุ้น/คริปโต/ทอง — ฟรี ไม่ใช้ API key 🕹️</div>",
            unsafe_allow_html=True)
st.write("")

st.session_state.setdefault("view", "🔎 ร่อนหาหุ้น")
st.session_state.setdefault("sel_ticker", "NVDA")

_views = ["🔎 ร่อนหาหุ้น", "🔬 ดูรายตัว"]
mode = st.sidebar.radio("เลือกโหมด", _views, index=_views.index(st.session_state["view"]))
st.session_state["view"] = mode
st.sidebar.markdown("---")
st.sidebar.caption("💡 กดชื่อหุ้นในตารางร่อน → เด้งไปดูรายตัว + วิเคราะห์ได้เลย")

if mode == "🔎 ร่อนหาหุ้น":
    c1, c2 = st.columns(2)
    style = c1.selectbox("สไตล์", list(STYLE_WEIGHTS.keys()))
    market = c2.selectbox("ตลาด", ["ทั้งหมด", "us", "th", "crypto", "gold"])
    if st.button("🚀 เริ่มร่อนหุ้น"):
        tickers = ([tk for l in UNIVERSE.values() for tk in l]
                   if market == "ทั้งหมด" else UNIVERSE[market])
        weights = STYLE_WEIGHTS[style]
        with st.spinner(f"กำลังสแกน {len(tickers)} ตัว..."):
            rows = []
            with ThreadPoolExecutor(max_workers=10) as pool:
                for d in pool.map(analyze, tickers):
                    if d:
                        d["total"] = composite(d["scores"], weights)
                        rows.append(d)
            rows.sort(key=lambda r: r["total"], reverse=True)
        st.session_state["screen_rows"] = rows
        st.session_state["screen_style"] = style

    rows = st.session_state.get("screen_rows")
    if rows:
        st.markdown(f"### 🏆 อันดับหุ้นเด่น — สไตล์ {st.session_state.get('screen_style','')}")
        df = pd.DataFrame([{
            "คะแนน": r["total"], "สัญลักษณ์": r["ticker"], "ชื่อ": r["name"],
            "ราคา": round(r["close"], 2), "RSI": round(r["rsi"], 0) if r["rsi"] else None,
            "โมเมนตัม3ด%": round(r["mom3"], 0) if r["mom3"] is not None else None,
            "Fwd P/E": round(r["fpe"], 1) if r["fpe"] else None,
            "โต%": round(r["rev_g"], 0) if r["rev_g"] is not None else None,
            "อัพไซด์%": round(r["upside"], 0) if r["upside"] is not None else None,
            "ปันผล%": round(r["dy"], 1) if r["dy"] is not None else None,
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True, height=400)

        st.markdown("**👇 กดชื่อหุ้นเพื่อดูรายตัว + วิเคราะห์ทันที:**")
        cols = st.columns(5)
        for i, r in enumerate(rows[:20]):
            if cols[i % 5].button(f"🔍 {r['ticker']}", key=f"go_{r['ticker']}",
                                  use_container_width=True):
                st.session_state["sel_ticker"] = r["ticker"]
                st.session_state["view"] = "🔬 ดูรายตัว"
                st.rerun()

else:  # ดูรายตัว
    ticker = st.text_input("ใส่สัญลักษณ์ (เช่น NVDA, PTT.BK, BTC-USD, GLD)",
                           st.session_state.get("sel_ticker", "NVDA")).strip().upper()
    st.session_state["sel_ticker"] = ticker
    if ticker:
        with st.spinner("กำลังดึงข้อมูลสด..."):
            d = detail(ticker)
        if not d:
            st.error(f"ไม่พบข้อมูลของ {ticker}")
        else:
            hist, info = d["hist"], d["info"]
            close = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else close
            chg = (close / prev - 1) * 100
            cur = info.get("currency", "")
            st.markdown(f"### {info.get('shortName', ticker)} ({ticker})")
            m = st.columns(4)
            m[0].metric("ราคาล่าสุด", f"{close:,.2f} {cur}", f"{chg:+.2f}%")
            m[1].metric("52สัปดาห์ สูง", f"{hist['Close'].max():,.2f}")
            m[2].metric("52สัปดาห์ ต่ำ", f"{hist['Close'].min():,.2f}")
            pe = info.get("trailingPE")
            m[3].metric("P/E", f"{pe:,.1f}" if pe else "—")

            # 🚦 หน้าปัดมาตรวัด ซื้อ-ถือ-ขาย (จากสัญญาณรวม เทคนิค+พื้นฐาน)
            a = analyze(ticker)
            if a:
                comp = composite(a["scores"], STYLE_WEIGHTS["สมดุล"])
                sellness = max(0, min(100, 100 - comp))
                st.markdown("### 🚦 มาตรวัดสัญญาณ (ซ้าย=ซื้อ · กลาง=ถือ · ขวา=ขาย)")
                gc1, gc2 = st.columns([3, 2])
                gc1.plotly_chart(reco_gauge(sellness), use_container_width=True)
                gc2.markdown(f"<div class='pixel-box' style='margin-top:40px'>"
                             f"<div class='big'>คำตัดสินเร็ว:</div>"
                             f"<h3 style='margin:6px 0'>{gauge_label(sellness)}</h3>"
                             f"<div class='big'>คะแนนรวม {comp:.0f}/100</div></div>",
                             unsafe_allow_html=True)
                st.caption("มาตรวัดนี้คิดจากตัวเลขอัตโนมัติ · กดปุ่ม 'วิเคราะห์เชิงลึก' ด้านล่างเพื่อให้ AI วิเคราะห์ละเอียด")

            # กราฟราคา + เส้นค่าเฉลี่ย
            chart = pd.DataFrame({"ราคา": hist["Close"]})
            chart["SMA50"] = hist["Close"].rolling(50).mean()
            chart["SMA200"] = hist["Close"].rolling(200).mean()
            st.line_chart(chart, height=320)

            # อินดิเคเตอร์
            stock = ss_wrap(hist.copy())
            colA, colB = st.columns(2)
            with colA:
                st.markdown("**อินดิเคเตอร์เทคนิค**")
                st.table(pd.DataFrame({
                    "ค่า": {
                        "RSI(14)": round(ind(stock, "rsi_14") or 0, 1),
                        "SMA50": round(ind(stock, "close_50_sma") or 0, 2),
                        "SMA200": round(ind(stock, "close_200_sma") or 0, 2),
                        "MACD": round(ind(stock, "macd") or 0, 2),
                    }
                }))
            with colB:
                st.markdown("**ปัจจัยพื้นฐาน**")
                fpe = info.get("forwardPE")
                rg = info.get("revenueGrowth")
                tgt = info.get("targetMeanPrice")
                st.table(pd.DataFrame({
                    "ค่า": {
                        "Forward P/E": round(fpe, 1) if fpe else "—",
                        "การเติบโต%": round(rg * 100, 1) if rg is not None else "—",
                        "เป้านักวิเคราะห์": tgt or "—",
                        "คำแนะนำ": info.get("recommendationKey", "—"),
                    }
                }))

            st.markdown("### 🕯️ สัญญาณเทคนิคขั้นสูง (แท่งเทียน + กลยุทธ์ + สภาวะตลาด)")
            try:
                st.markdown("<div class='pixel-box'>", unsafe_allow_html=True)
                st.markdown(technical_report_th(hist))
                st.markdown("</div>", unsafe_allow_html=True)
            except Exception as e:
                st.caption(f"คำนวณสัญญาณขั้นสูงไม่ได้: {e}")

            st.markdown("**📰 ข่าวล่าสุด**")
            cnt = 0
            for it in d["news"][:6]:
                c = it.get("content", it)
                title = c.get("title") or it.get("title")
                if title:
                    cnt += 1
                    st.write(f"{cnt}. {to_thai(title)}")
            if cnt == 0:
                st.caption("ไม่พบข่าว")

            st.markdown("---")
            st.markdown("### 🧠 วิเคราะห์เชิงลึกด้วย AI (หลายมุม)")
            st.caption("กดปุ่มแล้ว AI จะคิดให้ในเว็บเลย ฟรี (ใช้ Claude Code เดิม) ~30-90 วินาที")
            has_claude = shutil.which("claude") is not None
            has_gemini = _get_secret("GEMINI_API_KEY") is not None
            has_ai = has_claude or has_gemini
            label = "🚀 วิเคราะห์เชิงลึก (AI จริง)" if has_ai else "🚀 วิเคราะห์เชิงลึก (สรุปอัตโนมัติ)"
            if st.button(label):
                report = None
                src = ""
                prompt = build_deep_prompt(ticker, d)
                if has_claude:
                    with st.spinner("🤖 Claude กำลังวิเคราะห์ 4 มุมมอง... ~30-90 วินาที"):
                        report = run_claude(prompt)
                    src = "🤖 วิเคราะห์โดย Claude"
                if not report and has_gemini:
                    with st.spinner("🤖 Gemini กำลังวิเคราะห์ 4 มุมมอง..."):
                        report = call_gemini(prompt)
                    src = "🤖 วิเคราะห์โดย Google Gemini (ฟรี)"
                if not report:
                    with st.spinner("📊 กำลังสรุปจากตัวเลข..."):
                        report = rule_based_analysis(ticker, d)
                    src = "📊 สรุปอัตโนมัติ (ไม่มี AI — ใส่ GEMINI_API_KEY เพื่อให้ AI คิดจริง)"
                st.caption(src)
                st.markdown("<div class='pixel-box'>", unsafe_allow_html=True)
                st.markdown(report)
                st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("⚠️ เพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน · ข้อมูลจาก Yahoo Finance")
