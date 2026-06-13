"""
patterns.py — โมดูลวิเคราะห์เทคนิคขั้นสูง (แท่งเทียน + กลยุทธ์ + สภาวะตลาด)

รวมเทคนิคจาก 2 แหล่ง:
  1) คลังความรู้ของผู้ใช้ (D:\\cowork\\wiki) — กลยุทธ์ที่ backtest แล้ว:
     - RSI(2) Mean Reversion (Win 75-91% ในตลาด sideways)
     - MA Crossover 9/21/200 (จับ trend)
     - Market Regime (เลือกกลยุทธ์ตามสภาวะตลาด)
  2) งานวิจัยแท่งเทียน — แท่งเทียนต้องมี "volume + เทรนด์ + แนวรับ" ยืนยันถึงจะแม่น

ใช้: import แล้วเรียก technical_report_th(hist)  โดย hist = DataFrame ราคา (Open/High/Low/Close/Volume)
"""

import numpy as np
import pandas as pd


# ---------- ตัวช่วยพื้นฐาน ----------
def _rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(hist, period=14):
    h, l, c = hist["High"], hist["Low"], hist["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ---------- 1) แท่งเทียน (ต้องมีบริบทยืนยัน) ----------
def detect_candles(hist):
    """ตรวจรูปแบบแท่งเทียนของแท่งล่าสุด พร้อมบริบท (volume/เทรนด์)"""
    if len(hist) < 5:
        return []
    o, h, l, c = hist["Open"], hist["High"], hist["Low"], hist["Close"]
    v = hist.get("Volume", pd.Series([0] * len(hist), index=hist.index))
    i = -1  # แท่งล่าสุด

    body = abs(c.iloc[i] - o.iloc[i])
    rng = h.iloc[i] - l.iloc[i] or 1e-9
    upper = h.iloc[i] - max(c.iloc[i], o.iloc[i])
    lower = min(c.iloc[i], o.iloc[i]) - l.iloc[i]
    bull = c.iloc[i] > o.iloc[i]

    # บริบท: เทรนด์ก่อนหน้า (เทียบ SMA10) + volume เทียบเฉลี่ย 20 วัน
    sma10 = c.rolling(10).mean()
    downtrend = c.iloc[i] < sma10.iloc[i] if not pd.isna(sma10.iloc[i]) else False
    uptrend = c.iloc[i] > sma10.iloc[i] if not pd.isna(sma10.iloc[i]) else False
    vol_avg = v.iloc[-20:].mean() if len(v) >= 20 else v.mean()
    vol_confirm = (v.iloc[i] > vol_avg * 1.2) if vol_avg else False
    vmark = " ✅volume ยืนยัน" if vol_confirm else " ⚠️volume เบา"

    found = []

    # Doji — ไม่ตัดสินใจ
    if body < rng * 0.1:
        found.append(("Doji (ลังเล)", "กลาง", "ตลาดลังเล รอแท่งถัดไปยืนยัน"))

    # Hammer — กลับตัวขาขึ้น (ต้องอยู่ในขาลง)
    if lower >= body * 2 and upper <= body and downtrend:
        found.append(("Hammer (ค้อน)", "บวก", f"สัญญาณกลับตัวขึ้นที่ปลายขาลง{vmark}"))

    # Shooting Star — กลับตัวขาลง (ต้องอยู่ในขาขึ้น)
    if upper >= body * 2 and lower <= body and uptrend:
        found.append(("Shooting Star (ดาวตก)", "ลบ", f"สัญญาณกลับตัวลงที่ปลายขาขึ้น{vmark}"))

    # Engulfing — แท่งกลืนแท่งก่อนหน้า
    pbody_bull = c.iloc[i - 1] > o.iloc[i - 1]
    if bull and not pbody_bull and c.iloc[i] >= o.iloc[i - 1] and o.iloc[i] <= c.iloc[i - 1]:
        sig = "บวก (แรง)" if vol_confirm else "บวก"
        found.append(("Bullish Engulfing (กลืนขึ้น)", sig, f"แรงซื้อกลืนแรงขาย{vmark}"))
    if (not bull) and pbody_bull and o.iloc[i] >= c.iloc[i - 1] and c.iloc[i] <= o.iloc[i - 1]:
        sig = "ลบ (แรง)" if vol_confirm else "ลบ"
        found.append(("Bearish Engulfing (กลืนลง)", sig, f"แรงขายกลืนแรงซื้อ{vmark}"))

    # Morning/Evening Star (3 แท่ง)
    if len(hist) >= 3:
        b2 = abs(c.iloc[-2] - o.iloc[-2])
        b3 = abs(c.iloc[-3] - o.iloc[-3])
        # Morning Star: แดงใหญ่ → ตัวเล็ก → เขียวใหญ่
        if c.iloc[-3] < o.iloc[-3] and b2 < b3 * 0.5 and bull and body > b2:
            found.append(("Morning Star (ดาวรุ่ง)", "บวก", f"กลับตัวขึ้น 3 แท่ง{vmark}"))
        if c.iloc[-3] > o.iloc[-3] and b2 < b3 * 0.5 and not bull and body > b2:
            found.append(("Evening Star (ดาวค่ำ)", "ลบ", f"กลับตัวลง 3 แท่ง{vmark}"))

    return found


# ---------- 2) สัญญาณกลยุทธ์ (จากคลังผู้ใช้) ----------
def rsi2_signal(hist):
    """RSI(2) Mean Reversion — กลยุทธ์ Win 75-91% ของผู้ใช้ (เหมาะตลาด sideways)"""
    rsi2 = _rsi(hist["Close"], 2).iloc[-1]
    if pd.isna(rsi2):
        return None
    if rsi2 < 10:
        sig = "🟢 ซื้อ (oversold รุนแรง — เด้งกลับ)"
    elif rsi2 > 90:
        sig = "🔴 ขาย (overbought รุนแรง)"
    else:
        sig = "⚪ ยังไม่มีสัญญาณ"
    return {"rsi2": round(float(rsi2), 1), "signal": sig}


def ma_crossover_signal(hist):
    """MA Crossover 9/21/200 (จากคลังผู้ใช้) — จับ trend"""
    c = hist["Close"]
    s9, s21, s200 = c.rolling(9).mean(), c.rolling(21).mean(), c.rolling(200).mean()
    if pd.isna(s21.iloc[-1]):
        return None
    above200 = c.iloc[-1] > s200.iloc[-1] if not pd.isna(s200.iloc[-1]) else None
    cross_up = s9.iloc[-1] > s21.iloc[-1] and s9.iloc[-2] <= s21.iloc[-2]
    cross_dn = s9.iloc[-1] < s21.iloc[-1] and s9.iloc[-2] >= s21.iloc[-2]
    if cross_up and above200:
        sig = "🟢 สัญญาณซื้อ (9 ตัดขึ้น 21 + เหนือ 200)"
    elif cross_dn:
        sig = "🔴 สัญญาณออก/ขาย (9 ตัดลง 21)"
    elif s9.iloc[-1] > s21.iloc[-1]:
        sig = "⚪ ถือ (ยังเป็นขาขึ้น 9>21)"
    else:
        sig = "⚪ ยังไม่เข้าเงื่อนไข (9<21)"
    return {"signal": sig, "above_200": above200}


# ---------- 3) สภาวะตลาด (Market Regime) ----------
def detect_regime(hist):
    """ระบุสภาวะตลาด → แนะนำกลยุทธ์ที่เหมาะ (จากแนวคิด Market Regime ในคลัง)"""
    c = hist["Close"]
    close = c.iloc[-1]
    atr_pct = (_atr(hist).iloc[-1] / close * 100) if close else 0
    s50 = c.rolling(50).mean()
    slope = ((s50.iloc[-1] - s50.iloc[-20]) / s50.iloc[-20] * 100) if (len(c) > 50 and not pd.isna(s50.iloc[-20]) and s50.iloc[-20]) else 0

    if atr_pct > 5:
        regime, strat = "ผันผวนสูง (High Volatility)", "ลดขนาดลงทุน เลี่ยงไม้ใหญ่"
    elif abs(slope) > 3:
        d = "ขาขึ้น" if slope > 0 else "ขาลง"
        regime, strat = f"มีเทรนด์ชัด ({d})", "ใช้ Trend Following (MA Crossover)"
    else:
        regime, strat = "ออกข้าง (Sideways)", "ใช้ Mean Reversion (RSI2) ได้ดี"
    return {"regime": regime, "atr_pct": round(atr_pct, 1), "slope": round(slope, 1), "strategy": strat}


# ---------- รายงานรวม (ภาษาไทย) ----------
def technical_report_th(hist):
    out = []
    reg = detect_regime(hist)
    out.append(f"**สภาวะตลาด:** {reg['regime']} (ATR {reg['atr_pct']}%, แนวโน้ม50วัน {reg['slope']:+}%)")
    out.append(f"→ กลยุทธ์ที่เหมาะ: {reg['strategy']}")
    out.append("")

    r2 = rsi2_signal(hist)
    if r2:
        out.append(f"**RSI(2) Mean Reversion:** RSI2={r2['rsi2']} → {r2['signal']}")
    mac = ma_crossover_signal(hist)
    if mac:
        out.append(f"**MA Crossover 9/21/200:** {mac['signal']}")
    out.append("")

    candles = detect_candles(hist)
    if candles:
        out.append("**แท่งเทียนล่าสุด:**")
        for name, bias, note in candles:
            emoji = "🟢" if "บวก" in bias else "🔴" if "ลบ" in bias else "⚪"
            out.append(f"- {emoji} {name} [{bias}] — {note}")
    else:
        out.append("**แท่งเทียน:** ไม่พบรูปแบบเด่นในแท่งล่าสุด")

    return "\n".join(out)


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    import yfinance as yf
    tk = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    h = yf.Ticker(tk).history(period="1y", auto_adjust=True)
    print(f"=== เทคนิคขั้นสูง: {tk} ===")
    print(technical_report_th(h))
