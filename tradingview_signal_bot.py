#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingView-only Futures Signal Bot (BINANCE:PAIR.P) — v7 (Pine-accurate S/D)
================================================================================
Perbaikan utama v7 (sesuai keluhan Anda):
1) Zona Supply/Demand dihitung MENIRU PineScript SND.txt:
   - swing_length per TF: 30m=7, 1h=10, 4h=20, 1D=40 (fallback 20)
   - history_keep dinamis: <1H=20, 1H=15, >1H=10
   - atrpoi = ta.atr(50) (Wilder)
   - pivot dikonfirmasi (ta.pivothigh/low) => pivot muncul setelah "swing_length" bar
   - supply: top=pivotHigh, bottom=top-ATR*(box_width/10)
   - demand: bottom=pivotLow, top=bottom+ATR*(box_width/10)
   - overlap filter: new_poi tidak boleh berada dalam ±(ATR*2) dari poi zona existing
   - BOS (hapus zona):
        supply hilang jika close >= top
        demand hilang jika close <= bottom

2) Tidak ada BUY & SELL bersamaan pada TF yang sama:
   - Kalau dua-duanya eligible, pilih 1 side dengan jarak paling dekat ke zona.
   - Ada "lock side" per (symbol, tf) supaya tidak bolak-balik di loop yang sama.

3) Tidak spam: sinyal tiap (symbol, tf, side) hanya sekali per "cycle".
   - Boleh sinyal lagi HANYA jika sudah tembus TP2 lalu retest kembali ke Z1.
     (Plus re-arm aman setelah SL jika harga keluar area lalu retest).

Data:
- Harga & OHLC diambil dari TradingView via package `tradingview-datafeed` (tvDatafeed).
- Symbol perpetual: BINANCE:<SYMBOL>.P (contoh BTCUSDT.P)
- Daftar koin (SYMBOLS=ALL): TradingView scanner endpoint, filter USDT.P

Catatan:
- Ini bot sinyal (Telegram), bukan auto-trade.
- Scan banyak koin + 4 TF berat. Mulai dari MAX_SYMBOLS 30-200 dulu.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
import json

# --- chart image (zones only) ---
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt



# =========================
# CONFIG
# =========================

SYMBOLS_ENV = os.getenv("SYMBOLS", "ALL").strip()  # ALL atau list manual tanpa .P
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "80"))  # 0 = semua (berat)
MIN_TV_VOLUME_1D = float(os.getenv("MIN_TV_VOLUME_1D", "0"))

TIMEFRAMES: Dict[str, str] = {"30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}

BOX_WIDTH = float(os.getenv("BOX_WIDTH", "7.0"))
TRIGGER_ATR_MULT = float(os.getenv("TRIGGER_ATR_MULT", "0.25"))

KLINES_LIMIT = int(os.getenv("KLINES_LIMIT", "800"))  # butuh cukup bar untuk pivot
PRICE_REFRESH_SEC = int(os.getenv("PRICE_REFRESH_SEC", "12"))
LOOP_SLEEP_SEC = int(os.getenv("LOOP_SLEEP_SEC", "15"))

KLINE_REFRESH_SEC = {
    "30m": int(os.getenv("KLINE_REFRESH_30M", "240")),
    "1h":  int(os.getenv("KLINE_REFRESH_1H", "300")),
    "4h":  int(os.getenv("KLINE_REFRESH_4H", "900")),
    "1d":  int(os.getenv("KLINE_REFRESH_1D", "2400")),
}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TV_USERNAME = os.getenv("TV_USERNAME", "")
TV_PASSWORD = os.getenv("TV_PASSWORD", "")

MODE = os.getenv("MODE", "AUTO").upper().strip()

CORNIX_ENABLED = os.getenv("CORNIX_ENABLED", "1").strip()  # 1=pakai format Cornix untuk SINYAL entry
CORNIX_EXCHANGE = os.getenv("CORNIX_EXCHANGE", "Binance Futures").strip()
CORNIX_LEVERAGE = os.getenv("CORNIX_LEVERAGE", "Cross (20X)").strip()
CORNIX_MOVE_SL_TO_ENTRY_AFTER_TP1 = os.getenv("MOVE_SL_TO_ENTRY_AFTER_TP1", "1").strip()  # 1=SL pindah ke entry setelah TP1
CORNIX_SAFE_UPDATES = os.getenv("CORNIX_SAFE_UPDATES", "1").strip()
# === CHART IMAGE (ZONA SUPPLY/DEMAND SAJA) ===
SEND_CHART_IMAGE = os.getenv("SEND_CHART_IMAGE", "1").strip()  # 1=kirim gambar chart saat sinyal entry
CHART_IMAGE_CHAT = os.getenv("CHART_IMAGE_CHAT", "UPDATES").strip().upper()  # UPDATES atau SIGNALS
CHART_BARS = int(os.getenv("CHART_BARS", "120").strip() or "120")
CHART_DPI = int(os.getenv("CHART_DPI", "140").strip() or "140")
CHART_SHOW_LABELS = os.getenv("CHART_SHOW_LABELS", "0").strip()  # 1=tampilkan label Z1/Z2

  # 1=update dibuat anti-parse Cornix
TELEGRAM_CHAT_ID_SIGNALS = os.getenv("TELEGRAM_CHAT_ID_SIGNALS", "").strip()  # opsional: chat khusus sinyal
TELEGRAM_CHAT_ID_UPDATES = os.getenv("TELEGRAM_CHAT_ID_UPDATES", "").strip()  # opsional: chat khusus update

# --- TP/SL mode (for futures leverage) ---
# TP_SL_MODE:
# - ROI  : TP/SL berdasarkan target ROI (lebih cocok untuk leverage)
# - ZONE : TP/SL berdasarkan tinggi Zona-1 (mode lama)
TP_SL_MODE = os.getenv("TP_SL_MODE", "ROI").strip().upper()   # ROI / ZONE
LEVERAGE = float(os.getenv("LEVERAGE", "20"))                 # leverage default 20x
TP_ROI_1 = float(os.getenv("TP_ROI_1", "75"))                 # target ROI% untuk TP1
TP_ROI_2 = float(os.getenv("TP_ROI_2", "120"))                 # target ROI% untuk TP2
TP_ROI_3 = float(os.getenv("TP_ROI_3", "200"))                 # target ROI% untuk TP3
SL_ROI   = float(os.getenv("SL_ROI", "100"))                   # risk ROI% untuk StopLoss

DEBUG_SYMBOL = os.getenv("DEBUG_SYMBOL", "").strip().upper()  # contoh: BTCUSDT untuk print zone (opsional)
DEBUG_TF = os.getenv("DEBUG_TF", "").strip()  # contoh: 1h (opsional)


# =========================
# TradingView datafeed
# =========================

def _ensure_tv():
    try:
        from tvDatafeed import TvDatafeed, Interval  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Module tvDatafeed tidak ditemukan.\n"
            "Install:\n"
            "  pip install tradingview-datafeed pandas\n"
        ) from e
    return TvDatafeed, Interval


class TradingViewClient:
    def __init__(self, username: str = "", password: str = "") -> None:
        self._username = username
        self._password = password
        self._init_client()

    def _init_client(self) -> None:
        TvDatafeed, Interval = _ensure_tv()
        self.Interval = Interval
        self.tv = TvDatafeed(username=self._username or None, password=self._password or None)
        self.tf_map = {
            "1m":  self.Interval.in_1_minute,
            "5m":  self.Interval.in_5_minute,
            "30m": self.Interval.in_30_minute,
            "1h":  self.Interval.in_1_hour,
            "4h":  self.Interval.in_4_hour,
            "1d":  self.Interval.in_daily,
        }

    def reconnect(self) -> None:
        """Re-init koneksi TradingView datafeed jika koneksi putus."""
        self._init_client()

    def get_hist(self, tv_symbol: str, tf: str, n_bars: int) -> List[dict]:
        if tf not in self.tf_map:
            raise ValueError(f"TF tidak didukung: {tf}")

        max_try = int(os.getenv("TV_RETRY", "5") or "5")
        wait_s = float(os.getenv("TV_RETRY_WAIT", "2") or "2")
        last_err: Exception | None = None

        for attempt in range(1, max_try + 1):
            try:
                df = self.tv.get_hist(symbol=tv_symbol, exchange="BINANCE", interval=self.tf_map[tf], n_bars=n_bars)
                if df is None or getattr(df, "empty", False):
                    raise RuntimeError(f"TradingView data kosong: {tv_symbol} {tf}")

                # Pastikan ascending time
                try:
                    df = df.sort_index()
                except Exception:
                    pass

                out: List[dict] = []
                for _, row in df.iterrows():
                    out.append({
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0.0)),
                    })
                return out

            except Exception as e:
                last_err = e
                msg = str(e)
                print(f"[WARN] TV get_hist gagal (try {attempt}/{max_try}): {msg}")
                try:
                    self.reconnect()
                except Exception as re_e:
                    print(f"[WARN] reconnect gagal: {re_e}")
                import time as _t
                _t.sleep(wait_s * attempt)

        raise last_err  # type: ignore

# =========================
# TradingView scanner (symbol discovery)
# =========================

def _tv_scan(endpoint: str, rng: Tuple[int, int]) -> dict:
    url = f"https://scanner.tradingview.com/{endpoint}/scan"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }
    payload = {
        "filter": [{"left": "exchange", "operation": "equal", "right": "BINANCE"}],
        "options": {"lang": "en"},
        "markets": ["crypto"],
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "volume|1D"],
        "sort": {"sortBy": "volume|1D", "sortOrder": "desc"},
        "range": [rng[0], rng[1]],
    }
    r = requests.post(url, headers=headers, json=payload, timeout=25)
    r.raise_for_status()
    return r.json()

def _normalize_tv_symbol(s: str) -> Optional[str]:
    s = s.strip()
    if not s:
        return None
    if s.startswith("BINANCE:"):
        s = s.split(":", 1)[1]
    # hanya perpetual
    if not s.endswith(".P"):
        return None
    # hanya USDT perpetual
    if not s.endswith("USDT.P"):
        return None
    s = s.replace(".P", "")
    return s if s.endswith("USDT") else None

def discover_binance_usdt_perp_symbols(limit: int = 20000) -> List[str]:
    endpoints = ["crypto", "futures"]
    out: List[str] = []
    seen = set()
    start, end = 0, min(limit, 20000)

    for ep in endpoints:
        try:
            j = _tv_scan(ep, (start, end))
        except Exception as e:
            print(f"[WARN] Scan endpoint '{ep}' gagal: {e}")
            continue

        for row in j.get("data", []):
            sym_raw = row.get("s")
            d = row.get("d", [])
            if not sym_raw:
                sym_raw = str(d[0]) if d else ""
            vol1d = 0.0
            if isinstance(d, list) and len(d) > 1 and d[1] is not None:
                try:
                    vol1d = float(d[1])
                except Exception:
                    vol1d = 0.0

            sym = _normalize_tv_symbol(str(sym_raw))
            if not sym:
                continue
            if MIN_TV_VOLUME_1D > 0 and vol1d < MIN_TV_VOLUME_1D:
                continue
            if sym not in seen:
                seen.add(sym)
                out.append(sym)
    return out


# =========================
# Structures
# =========================

@dataclass(frozen=True)
class Zone:
    kind: str   # demand/supply
    low: float
    high: float

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2.0

    @property
    def height(self) -> float:
        return abs(self.high - self.low)


@dataclass(frozen=True)
class FVG:
    kind: str   # bull/bear
    low: float
    high: float


@dataclass
class SetupState:
    symbol: str
    tf: str
    side: str          # BUY / SELL
    zone1: Zone
    zone2: Optional[FVG]
    atr: float
    buffer: float
    levels: Dict[str, float]

    state: str = "SEARCHING"
    extreme_price: float = 0.0
    choch_level: float = 0.0

    # one-shot flags per cycle
    confirmed_sent: bool = False
    tp1_sent: bool = False
    tp2_sent: bool = False
    tp3_sent: bool = False
    sl_sent: bool = False
    sl_moved_to_entry: bool = False

    position_active: bool = False

    # rearm rules
    tp2_hit: bool = False
    left_zone_after_tp2: bool = False

    finished: bool = False
    left_zone_after_finish: bool = False
    setup_type: str = ""

    def signature(self) -> str:
        z2 = f"{self.zone2.low:.8f}-{self.zone2.high:.8f}" if self.zone2 else "none"
        return f"{self.side}|{self.zone1.low:.8f}-{self.zone1.high:.8f}|{z2}"

    def reset_cycle(self) -> None:
        self.state = "SEARCHING"
        self.confirmed_sent = False
        self.tp1_sent = False
        self.tp2_sent = False
        self.tp3_sent = False
        self.sl_sent = False
        self.position_active = False
        self.tp2_hit = False
        self.left_zone_after_tp2 = False
        self.finished = False
        self.left_zone_after_finish = False
        self.setup_type = ""


# =========================
# Pine-accurate Supply/Demand builder (from SND.txt)
# =========================

def swing_length_for_tf(tf: str) -> int:
    # Pine: tf == "1D" ? 40 : tf == "240" ? 20 : tf == "60" ? 10 : tf == "30" ? 7 : ...
    # tvDatafeed tf naming we use: "1d","4h","1h","30m"
    if tf in ("1d", "1D"):
        return 40
    if tf in ("4h", "240"):
        return 20
    if tf in ("1h", "60"):
        return 10
    if tf in ("30m", "30"):
        return 7
    return 20

def history_keep_for_tf(tf: str) -> int:
    # Pine: <1h => 20, 1h => 15, >1h => 10
    tf_minutes = {"30m": 30, "1h": 60, "4h": 240, "1d": 1440}.get(tf, 60)
    if tf_minutes < 60:
        return 20
    if tf_minutes == 60:
        return 15
    return 10

def atr_wilder(high: List[float], low: List[float], close: List[float], period: int = 50) -> List[Optional[float]]:
    n = len(close)
    if n == 0:
        return []
    tr = [0.0] * n
    for i in range(n):
        if i == 0:
            tr[i] = high[i] - low[i]
        else:
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
    atr: List[Optional[float]] = [None] * n
    if n <= period:
        return atr
    # Wilder seed: average TR 1..period
    atr[period] = sum(tr[1:period+1]) / period
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period  # type: ignore
    return atr

def _pivot_high_confirmed(high: List[float], i: int, lr: int) -> Optional[float]:
    """
    Mimic ta.pivothigh(high, lr, lr) which returns pivot value at bar i-lr
    when bar i is the confirmation bar.
    Window length = 2*lr+1: [i-2lr .. i]
    """
    c = i - lr
    if c < lr or i < 2 * lr:
        return None
    win = high[i - 2*lr : i + 1]
    return high[c] if high[c] == max(win) else None

def _pivot_low_confirmed(low: List[float], i: int, lr: int) -> Optional[float]:
    c = i - lr
    if c < lr or i < 2 * lr:
        return None
    win = low[i - 2*lr : i + 1]
    return low[c] if low[c] == min(win) else None

def _check_overlapping(new_poi: float, zones: List[Zone], atr_val: float) -> bool:
    # Pine: atr_thres = atr*2; if new_poi in [poi-atr_thres, poi+atr_thres] => not okay
    atr_thres = atr_val * 2.0
    for z in zones:
        poi = z.mid
        if (new_poi >= poi - atr_thres) and (new_poi <= poi + atr_thres):
            return False
    return True

def build_zones_pine(tf: str, ohlc: List[dict], box_width: float) -> Tuple[List[Zone], List[Zone], float]:
    """
    Returns (demand_zones, supply_zones, atr_last) — zones are active at last bar.
    """
    high = [c["high"] for c in ohlc]
    low = [c["low"] for c in ohlc]
    close = [c["close"] for c in ohlc]

    lr = swing_length_for_tf(tf)
    keep = history_keep_for_tf(tf)

    atr = atr_wilder(high, low, close, 50)
    atr_last = next((x for x in reversed(atr) if x is not None), 0.0)
    # fall back atr for early bars
    def atr_at(i: int) -> float:
        return float(atr[i]) if i < len(atr) and atr[i] is not None else float(atr_last)

    supply: List[Zone] = []
    demand: List[Zone] = []

    n = len(close)
    if n < 2 * lr + 10:
        return demand, supply, atr_last

    for i in range(n):
        atr_i = atr_at(i)

        sh = _pivot_high_confirmed(high, i, lr)
        if sh is not None:
            atr_buf = atr_i * (box_width / 10.0)
            top = sh
            bot = top - atr_buf
            poi = (top + bot) / 2.0
            if _check_overlapping(poi, supply, atr_i):
                supply.insert(0, Zone("supply", low=bot, high=top))
                supply = supply[:keep]

        sl = _pivot_low_confirmed(low, i, lr)
        if sl is not None:
            atr_buf = atr_i * (box_width / 10.0)
            bot = sl
            top = bot + atr_buf
            poi = (top + bot) / 2.0
            if _check_overlapping(poi, demand, atr_i):
                demand.insert(0, Zone("demand", low=bot, high=top))
                demand = demand[:keep]

        # BOS removal at bar i (Pine checks every bar): supply close >= top, demand close <= bottom
        c = close[i]
        supply = [z for z in supply if c < z.high]
        demand = [z for z in demand if c > z.low]

    return demand, supply, atr_last


# =========================
# FVG (simple)
# =========================

def build_fvgs(ohlc: List[dict]) -> List[FVG]:
    # Simple 3-bar FVG (bull: low[i] > high[i-2], bear: high[i] < low[i-2])
    high = [c["high"] for c in ohlc]
    low = [c["low"] for c in ohlc]
    out: List[FVG] = []
    for i in range(2, len(ohlc)):
        if low[i] > high[i - 2]:
            out.append(FVG("bull", low=high[i - 2], high=low[i]))
        elif high[i] < low[i - 2]:
            out.append(FVG("bear", low=high[i], high=low[i - 2]))
    out.reverse()
    return out[:80]

def pick_zone2_fvg_for_buy(demand: Zone, fvgs: List[FVG]) -> Optional[FVG]:
    # zone2 buy = FVG di bawah demand (high <= demand.low)
    cand = [f for f in fvgs if f.kind == "bull" and f.high <= demand.low]
    if not cand:
        return None
    cand.sort(key=lambda f: demand.low - f.high)
    return cand[0]

def pick_zone2_fvg_for_sell(supply: Zone, fvgs: List[FVG]) -> Optional[FVG]:
    # zone2 sell = FVG di atas supply (low >= supply.high)
    cand = [f for f in fvgs if f.kind == "bear" and f.low >= supply.high]
    if not cand:
        return None
    cand.sort(key=lambda f: f.low - supply.high)
    return cand[0]


# =========================
# Signal helpers
# =========================

def get_internal_swing_high(high: List[float], current_idx: int) -> float:
    for i in range(current_idx - 5, 5, -1):
        if i >= len(high) or i < 5: continue
        is_pivot = True
        for j in range(1, 6):
            if i-j >= 0 and high[i] <= high[i-j]:
                is_pivot = False; break
            if i+j < len(high) and high[i] <= high[i+j]:
                is_pivot = False; break
        if is_pivot:
            return float(high[i])
    start_idx = max(0, current_idx - 10)
    sub = high[start_idx:current_idx]
    if sub:
        return float(max(sub))
    return float(high[0]) if high else 0.0

def get_internal_swing_low(low: List[float], current_idx: int) -> float:
    for i in range(current_idx - 5, 5, -1):
        if i >= len(low) or i < 5: continue
        is_pivot = True
        for j in range(1, 6):
            if i-j >= 0 and low[i] >= low[i-j]:
                is_pivot = False; break
            if i+j < len(low) and low[i] >= low[i+j]:
                is_pivot = False; break
        if is_pivot:
            return float(low[i])
    start_idx = max(0, current_idx - 10)
    sub = low[start_idx:current_idx]
    if sub:
        return float(min(sub))
    return float(low[0]) if low else 0.0

def pick_nearest_active_zones(price: float, demand_zones: List[Zone], supply_zones: List[Zone]) -> Tuple[Optional[Zone], Optional[Zone]]:
    # Demand "nearest below": choose zone with smallest (price - zone.high) where zone.high <= price
    best_d, best_dd = None, float("inf")
    for z in demand_zones:
        if z.low <= price <= z.high:
            best_d, best_dd = z, 0.0
            break
        if z.high <= price:
            d = price - z.high
            if d < best_dd:
                best_dd, best_d = d, z

    # Supply "nearest above": choose zone with smallest (zone.low - price) where zone.low >= price
    best_s, best_sd = None, float("inf")
    for z in supply_zones:
        if z.low <= price <= z.high:
            best_s, best_sd = z, 0.0
            break
        if z.low >= price:
            d = z.low - price
            if d < best_sd:
                best_sd, best_s = d, z

    return best_d, best_s

def calc_tp_sl(side: str, zone1: Zone) -> Dict[str, float]:
    """
    TP/SL modes:
    - ZONE: sesuai request awal (berdasarkan tinggi Zona-1 / range)
    - ROI : sesuai leverage. Perhitungan berdasarkan target ROI% dan leverage:
            price_move_pct = ROI% / leverage
            price_move     = entry * price_move_pct
    """
    e = zone1.mid

    if TP_SL_MODE == "ZONE":
        h = zone1.height if zone1.height != 0 else max(1e-6, e * 0.001)
        if side == "BUY":
            return {"entry": e, "tp1": e + 0.5*h, "tp2": e + 1.0*h, "tp3": e + 1.5*h, "sl": e - 1.0*h}
        return {"entry": e, "tp1": e - 0.5*h, "tp2": e - 1.0*h, "tp3": e - 1.5*h, "sl": e + 1.0*h}

    # ROI mode (default) — cocok untuk leverage 20x
    lev = max(1.0, float(LEVERAGE))
    def move(roi_pct: float) -> float:
        return e * (roi_pct / 100.0) / lev

    m1 = move(TP_ROI_1)
    m2 = move(TP_ROI_2)
    m3 = move(TP_ROI_3)
    ms = move(SL_ROI)

    if side == "BUY":
        return {"entry": e, "tp1": e + m1, "tp2": e + m2, "tp3": e + m3, "sl": e - ms}
    return {"entry": e, "tp1": e - m1, "tp2": e - m2, "tp3": e - m3, "sl": e + ms}


def send_telegram(text: str, chat_id: str = "") -> int:
    """Kirim pesan Telegram. Return message_id (0 jika gagal)."""
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diisi. Pesan tidak dikirim.")
        print(text)
        return 0
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    try:
        j = r.json()
        return int(j.get("result", {}).get("message_id", 0) or 0)
    except Exception:
        return 0


def send_telegram_reply(text: str, reply_to_message_id: int, chat_id: str = "") -> int:
    """Kirim reply ke message_id tertentu (dipakai untuk /close Cornix)."""
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat or not reply_to_message_id:
        print("[WARN] Reply tidak dikirim (token/chat_id/message_id kosong).")
        print(text)
        return 0


def send_telegram_photo(photo_path: str, caption: str = "", chat_id: str = "") -> int:
    """Kirim foto Telegram. Return message_id (0 jika gagal)."""
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diisi. Foto tidak dikirim.")
        print(caption)
        return 0
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data = {
                "chat_id": target_chat,
                "caption": caption[:1024],
                "disable_web_page_preview": True,
            }
            r = requests.post(url, data=data, files=files, timeout=30)
        r.raise_for_status()
        j = r.json()
        return int(j.get("result", {}).get("message_id", 0) or 0)
    except Exception as e:
        print(f"[WARN] send_telegram_photo gagal: {e}")
        return 0


def render_zones_chart(tv, symbol: str, tf: str, side: str, zone1, zone2=None) -> str:
    """Gambar ulang chart (candlestick) + zona Z1/Z2. Tanpa garis entry/tp/sl."""
    try:
        tv_symbol = f"{symbol}.P"
        ohlc = tv.get_hist(tv_symbol, tf, CHART_BARS)
        if not ohlc or len(ohlc) < 10:
            return ""
    except Exception as e:
        print(f"[WARN] render_zones_chart: gagal ambil OHLC {symbol} {tf}: {e}")
        return ""

    o = [float(x["open"]) for x in ohlc]
    h = [float(x["high"]) for x in ohlc]
    l = [float(x["low"]) for x in ohlc]
    c = [float(x["close"]) for x in ohlc]
    x = list(range(len(ohlc)))

    fig, ax = plt.subplots(figsize=(9, 5), dpi=CHART_DPI)
    arah = "LONG" if side == "BUY" else "SHORT"
    ax.set_title(f"{symbol} | {tf} | {arah}", fontsize=10)

    body_w = 0.6
    for i in range(len(ohlc)):
        ax.vlines(x[i], l[i], h[i], linewidth=1)
        y0 = min(o[i], c[i])
        y1 = max(o[i], c[i])
        height = max(y1 - y0, (h[i] - l[i]) * 0.001)
        rect = plt.Rectangle((x[i] - body_w/2, y0), body_w, height)
        ax.add_patch(rect)

    # Z1
    z1_low, z1_high = float(zone1.low), float(zone1.high)
    ax.axhspan(z1_low, z1_high, alpha=0.18)
    if CHART_SHOW_LABELS == "1":
        ax.text(0.01, (z1_low + z1_high) / 2, "Z1", transform=ax.get_yaxis_transform(), fontsize=9, va="center")

    # Z2
    if zone2 is not None:
        z2_low, z2_high = float(zone2.low), float(zone2.high)
        ax.axhspan(z2_low, z2_high, alpha=0.14)
        if CHART_SHOW_LABELS == "1":
            ax.text(0.01, (z2_low + z2_high) / 2, "Z2", transform=ax.get_yaxis_transform(), fontsize=9, va="center")

    ax.set_xlim(-1, len(ohlc))
    ax.grid(True, linewidth=0.3, alpha=0.4)
    ax.tick_params(axis="x", which="both", bottom=False, labelbottom=False)

    out_dir = Path("charts")
    out_dir.mkdir(exist_ok=True)
    fname = f"{symbol}_{tf}_{int(time.time())}.png".replace("/", "_")
    out_path = out_dir / fname
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        files = {"photo": f}
        data = {
            "chat_id": target_chat,
            "caption": caption[:1024],
            "disable_web_page_preview": True,
        }
        r = requests.post(url, data=data, files=files, timeout=30)
    r.raise_for_status()
    try:
        j = r.json()
        return int(j.get("result", {}).get("message_id", 0) or 0)
    except Exception:
        return 0
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "disable_web_page_preview": True,
        # param lama Telegram masih kompatibel luas
        "reply_to_message_id": int(reply_to_message_id),
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    try:
        j = r.json()
        return int(j.get("result", {}).get("message_id", 0) or 0)
    except Exception:
        return 0


# =========================
# Engine
# =========================

class SignalEngine:
    def __init__(self, tv: TradingViewClient) -> None:
        self.tv = tv
        self.zone_cache: Dict[Tuple[str, str], dict] = {}
        self.price_cache: Dict[str, dict] = {}
        self.setups: Dict[Tuple[str, str, str], SetupState] = {}
        self.signatures: Dict[Tuple[str, str, str], str] = {}

        # lock per (symbol, tf) to avoid BUY+SELL oscillation/spam
        self.lock_side: Dict[Tuple[str, str], Optional[str]] = {}

    def _fmt(self, x: float) -> str:
        if abs(x) >= 1000:
            return f"{x:,.0f}".replace(",", ".")
        if abs(x) >= 1:
            return f"{x:.4f}"
        return f"{x:.8f}"

    def _chat_signals(self) -> str:
        return TELEGRAM_CHAT_ID_SIGNALS or TELEGRAM_CHAT_ID

    def _chat_updates(self) -> str:
        return TELEGRAM_CHAT_ID_UPDATES or TELEGRAM_CHAT_ID

    def _cornix_pair(self, sym: str) -> str:
        if sym.endswith("USDT"):
            return f"{sym[:-4]}/USDT"
        return sym

    def _build_cornix_signal(self, st: SetupState, price: float, zname: str) -> str:
        pair = self._cornix_pair(st.symbol)
        sig_type = "Regular (Long)" if st.side == "BUY" else "Regular (Short)"
        entry = st.levels["entry"]
        emin = st.levels.get("entry_min", entry)
        emax = st.levels.get("entry_max", entry)
        tp1, tp2, tp3 = st.levels["tp1"], st.levels["tp2"], st.levels["tp3"]
        sl = st.levels["sl"]

        lines = [
            f"⚡⚡ #{pair} ⚡⚡",
            f"Exchanges: {CORNIX_EXCHANGE}",
            f"Signal Type: {sig_type}",
        ]
        if CORNIX_LEVERAGE:
            lines.append(f"Leverage: {CORNIX_LEVERAGE}")

        lines.append(f"Entry Zone: {self._fmt(emin)} - {self._fmt(emax)}")

        lines.append("Take-Profit Targets:")
        lines.append(f"1) {self._fmt(tp1)} - 50%")
        lines.append(f"2) {self._fmt(tp2)} - 25%")
        lines.append(f"3) {self._fmt(tp3)} - 25%")

        lines.append("Stop Targets:")
        lines.append(f"1) {self._fmt(sl)}")

        info = f"Info: TF={st.tf} | Harga={self._fmt(price)} | Z1({zname})={self._fmt(st.zone1.low)}-{self._fmt(st.zone1.high)}"
        if st.zone2:
            info += f" | Z2(FVG)={self._fmt(st.zone2.low)}-{self._fmt(st.zone2.high)}"
        lines.append("")
        lines.append(info)
        return "\n".join(lines)

    def _build_update_text(self, title: str, st: SetupState, price: float, extra: str = "") -> str:
        """
        UPDATE (anti-parse Cornix):
        - Tidak memakai: Pair:, Side:, Entry:, TP, SL, Exchanges:, Signal Type:, Entry Zone:
        - Tidak memakai ':' agar tidak terbaca 'KEY: VALUE'
        - Pair ditulis tanpa '/' (pakai '-') dan TANPA '#'
        """
        sym = self._cornix_pair(st.symbol).replace("/", "-").replace("#", "")
        arah = "LONG" if st.side == "BUY" else "SHORT"
        parts = [title, f"SYMBOL {sym}", f"TF {st.tf}", f"ARAH {arah}", f"HARGA {self._fmt(price)}"]
        msg_plain = " | ".join(parts)
        if extra:
            msg_plain = msg_plain + " | " + extra.strip()
        return msg_plain

    def get_price(self, symbol: str) -> float:
        now = time.time()
        c = self.price_cache.get(symbol)
        if c and (now - c["ts"] < PRICE_REFRESH_SEC):
            return c["price"]
        tv_symbol = f"{symbol}.P"
        try:
            kl = self.tv.get_hist(tv_symbol, "1m", 3)
        except Exception:
            kl = self.tv.get_hist(tv_symbol, "5m", 3)
        price = float(kl[-1]["close"])
        self.price_cache[symbol] = {"ts": now, "price": price}
        return price

    def get_pine_zones(self, symbol: str, tf: str):
        key = (symbol, tf)
        now = time.time()
        refresh = KLINE_REFRESH_SEC.get(tf, 300)
        cached = self.zone_cache.get(key)
        if cached and (now - cached["ts"] < refresh):
            return cached["demand"], cached["supply"], cached["fvgs"], cached["atr"], cached["ohlc"]

        tv_symbol = f"{symbol}.P"
        ohlc = self.tv.get_hist(tv_symbol, tf, KLINES_LIMIT)

        demand, supply, atr_last = build_zones_pine(tf, ohlc, BOX_WIDTH)
        fvgs = build_fvgs(ohlc)

        self.zone_cache[key] = {"ts": now, "demand": demand, "supply": supply, "fvgs": fvgs, "atr": atr_last, "ohlc": ohlc}

        # optional debug
        if DEBUG_SYMBOL and symbol == DEBUG_SYMBOL and (not DEBUG_TF or tf == DEBUG_TF):
            d0 = demand[0] if demand else None
            s0 = supply[0] if supply else None
            print(f"[DEBUG] {symbol} {tf} demand0={d0} supply0={s0} atr={atr_last}")
        return demand, supply, fvgs, atr_last, ohlc

    def process_symbol_tf(self, symbol: str, tf: str, price: float) -> None:
        demand_zones, supply_zones, fvgs, atr_last, ohlc = self.get_pine_zones(symbol, tf)
        demand, supply = pick_nearest_active_zones(price, demand_zones, supply_zones)
        fvg_buy = pick_zone2_fvg_for_buy(demand, fvgs) if demand else None
        fvg_sell = pick_zone2_fvg_for_sell(supply, fvgs) if supply else None

        buffer_val = (atr_last * TRIGGER_ATR_MULT) if (atr_last and atr_last > 0) else max(price * 0.005, 1e-6)

        opens = [float(c["open"]) for c in ohlc]
        highs = [float(c["high"]) for c in ohlc]
        lows = [float(c["low"]) for c in ohlc]
        closes = [float(c["close"]) for c in ohlc]
        curr_idx = len(ohlc) - 1

        buy_key = (symbol, tf, "BUY")
        sell_key = (symbol, tf, "SELL")

        if buy_key not in self.setups:
            self.setups[buy_key] = SetupState(symbol=symbol, tf=tf, side="BUY", zone1=Zone("demand",0,0), zone2=None, atr=atr_last, buffer=buffer_val, levels={})
        if sell_key not in self.setups:
            self.setups[sell_key] = SetupState(symbol=symbol, tf=tf, side="SELL", zone1=Zone("supply",0,0), zone2=None, atr=atr_last, buffer=buffer_val, levels={})

        st_buy = self.setups[buy_key]
        st_sell = self.setups[sell_key]

        st_buy.atr = atr_last; st_buy.buffer = buffer_val
        st_sell.atr = atr_last; st_sell.buffer = buffer_val

        if demand:
            st_buy.zone1 = demand
            st_buy.zone2 = fvg_buy
        if supply:
            st_sell.zone1 = supply
            st_sell.zone2 = fvg_sell

        self._process_smc_state(st_buy, price, demand, opens, highs, lows, closes, curr_idx)
        self._process_smc_state(st_sell, price, supply, opens, highs, lows, closes, curr_idx)

    def _process_smc_state(self, st: SetupState, price: float, active_zone: Optional[Zone], opens: List[float], highs: List[float], lows: List[float], closes: List[float], curr_idx: int) -> None:
        prev_idx = curr_idx - 1 if curr_idx > 0 else 0

        if st.state == "SEARCHING":
            if not active_zone: return
            if st.side == "BUY" and price <= active_zone.high + st.buffer:
                st.state = "TAPPED_Z1"
                st.extreme_price = price
            elif st.side == "SELL" and price >= active_zone.low - st.buffer:
                st.state = "TAPPED_Z1"
                st.extreme_price = price

        elif st.state == "TAPPED_Z1":
            if not active_zone: 
                st.reset_cycle()
                return

            if st.side == "BUY":
                if price < st.extreme_price: st.extreme_price = price
                # Look for Micro-BOS in the last 4 closed candles
                setup_triggered = False
                for i in range(max(0, curr_idx - 4), curr_idx):
                    if closes[i] > opens[i] and lows[i] <= active_zone.high + st.buffer:
                        for j in range(i + 1, curr_idx):
                            if closes[j] > highs[i]:
                                setup_triggered = True
                                entry_p = closes[j]
                                st.choch_level = highs[i]
                                break
                    if setup_triggered: break
                
                if setup_triggered:
                    st.state = "SETUP1_ACTIVE"
                    st.setup_type = "[SETUP 1] Demand Micro-BOS Confirmed"
                    base_sl = min(st.extreme_price, active_zone.low)
                    if st.zone2 and st.zone2.low < base_sl:
                        base_sl = min(base_sl, st.zone2.low)
                    sl = base_sl - (st.atr * 0.2)
                    if sl >= entry_p: sl = entry_p - max(st.atr * 1.0, entry_p * 0.005)
                    self._set_levels(st, entry_p, sl, "BUY", entry_min=st.choch_level, entry_max=entry_p + (st.atr * 0.1))
                    self._send_confirmed(st, price, "Z1 Demand")
                elif closes[prev_idx] < active_zone.low:
                    # Broke Z1, seek FVG
                    st.state = "SEEKING_FVG"

            elif st.side == "SELL":
                if price > st.extreme_price: st.extreme_price = price
                setup_triggered = False
                for i in range(max(0, curr_idx - 4), curr_idx):
                    if closes[i] < opens[i] and highs[i] >= active_zone.low - st.buffer:
                        for j in range(i + 1, curr_idx):
                            if closes[j] < lows[i]:
                                setup_triggered = True
                                entry_p = closes[j]
                                st.choch_level = lows[i]
                                break
                    if setup_triggered: break
                
                if setup_triggered:
                    st.state = "SETUP1_ACTIVE"
                    st.setup_type = "[SETUP 1] Supply Micro-BOS Confirmed"
                    base_sl = max(st.extreme_price, active_zone.high)
                    if st.zone2 and st.zone2.high > base_sl:
                        base_sl = max(base_sl, st.zone2.high)
                    sl = base_sl + (st.atr * 0.2)
                    if sl <= entry_p: sl = entry_p + max(st.atr * 1.0, entry_p * 0.005)
                    self._set_levels(st, entry_p, sl, "SELL", entry_min=entry_p - (st.atr * 0.1), entry_max=st.choch_level)
                    self._send_confirmed(st, price, "Z1 Supply")
                elif closes[prev_idx] > active_zone.high:
                    # Broke Z1, seek FVG
                    st.state = "SEEKING_FVG"

        elif st.state == "SEEKING_FVG":
            if not st.zone2: 
                # No FVG to sweep into, abandon
                st.reset_cycle()
                return
                
            if st.side == "BUY":
                if price < st.extreme_price: st.extreme_price = price
                # If price completely breaks FVG, invalidate
                if closes[prev_idx] < st.zone2.low:
                    st.reset_cycle()
                    return
                # Touch FVG & Reject & Micro-BOS
                setup_triggered = False
                for i in range(max(0, curr_idx - 4), curr_idx):
                    if lows[i] <= st.zone2.high + st.buffer and closes[i] > opens[i]:
                        for j in range(i + 1, curr_idx):
                            if closes[j] > highs[i]:
                                setup_triggered = True
                                entry_p = closes[j]
                                st.choch_level = highs[i]
                                break
                    if setup_triggered: break

                if setup_triggered:
                    st.state = "SETUP2_ACTIVE"
                    st.setup_type = "[SETUP 2] FVG Deep Sweep Micro-BOS Confirmed"
                    base_sl = min(st.extreme_price, st.zone2.low)
                    if st.zone1 and st.zone1.low < base_sl: # Safety check with z1 too, just in case
                        base_sl = min(base_sl, st.zone1.low)
                    sl = base_sl - (st.atr * 0.2)
                    if sl >= entry_p: sl = entry_p - max(st.atr * 1.0, entry_p * 0.005)
                    self._set_levels(st, entry_p, sl, "BUY", entry_min=st.choch_level, entry_max=entry_p + (st.atr * 0.1))
                    self._send_confirmed(st, price, "Z2 FVG")
            
            elif st.side == "SELL":
                if price > st.extreme_price: st.extreme_price = price
                # If price completely breaks FVG, invalidate
                if closes[prev_idx] > st.zone2.high:
                    st.reset_cycle()
                    return
                # Touch FVG & Reject & Micro-BOS
                setup_triggered = False
                for i in range(max(0, curr_idx - 4), curr_idx):
                    if highs[i] >= st.zone2.low - st.buffer and closes[i] < opens[i]:
                        for j in range(i + 1, curr_idx):
                            if closes[j] < lows[i]:
                                setup_triggered = True
                                entry_p = closes[j]
                                st.choch_level = lows[i]
                                break
                    if setup_triggered: break

                if setup_triggered:
                    st.state = "SETUP2_ACTIVE"
                    st.setup_type = "[SETUP 2] FVG Deep Sweep Micro-BOS Confirmed"
                    base_sl = max(st.extreme_price, st.zone2.high)
                    if st.zone1 and st.zone1.high > base_sl: # Safety check with z1 too
                        base_sl = max(base_sl, st.zone1.high)
                    sl = base_sl + (st.atr * 0.2)
                    if sl <= entry_p: sl = entry_p + max(st.atr * 1.0, entry_p * 0.005)
                    self._set_levels(st, entry_p, sl, "SELL", entry_min=entry_p - (st.atr * 0.1), entry_max=st.choch_level)
                    self._send_confirmed(st, price, "Z2 FVG")

        elif st.state in ("SETUP1_ACTIVE", "SETUP2_ACTIVE"):
            st.position_active = True
            
            if st.side == "BUY":
                if not st.tp1_sent and price >= st.levels["tp1"]:
                    st.tp1_sent = True; self._send_tp(st, price, "TP1")
                    if CORNIX_MOVE_SL_TO_ENTRY_AFTER_TP1 == "1": st.levels["sl"] = max(st.levels["sl"], st.levels["entry"])
                if not st.tp2_sent and price >= st.levels["tp2"]:
                    st.tp2_sent = True; self._send_tp(st, price, "TP2")
                if not st.tp3_sent and price >= st.levels["tp3"]:
                    st.tp3_sent = True; self._send_tp(st, price, "TP3")
                    st.finished = True; st.reset_cycle()
                if not st.sl_sent and price <= st.levels["sl"]:
                    st.sl_sent = True; self._send_sl(st, price)
                    # Stop Hunt detected! Move to Seeking FVG if it was Setup 1
                    if st.state == "SETUP1_ACTIVE":
                        st.state = "SEEKING_FVG"
                        st.position_active = False
                        st.confirmed_sent = False
                        st.tp1_sent = False; st.tp2_sent = False; st.tp3_sent = False; st.sl_sent = False
                    else:
                        st.finished = True; st.reset_cycle()
            else:
                if not st.tp1_sent and price <= st.levels["tp1"]:
                    st.tp1_sent = True; self._send_tp(st, price, "TP1")
                    if CORNIX_MOVE_SL_TO_ENTRY_AFTER_TP1 == "1": st.levels["sl"] = min(st.levels["sl"], st.levels["entry"])
                if not st.tp2_sent and price <= st.levels["tp2"]:
                    st.tp2_sent = True; self._send_tp(st, price, "TP2")
                if not st.tp3_sent and price <= st.levels["tp3"]:
                    st.tp3_sent = True; self._send_tp(st, price, "TP3")
                    st.finished = True; st.reset_cycle()
                if not st.sl_sent and price >= st.levels["sl"]:
                    st.sl_sent = True; self._send_sl(st, price)
                    # Stop Hunt detected! Move to Seeking FVG if it was Setup 1
                    if st.state == "SETUP1_ACTIVE":
                        st.state = "SEEKING_FVG"
                        st.position_active = False
                        st.confirmed_sent = False
                        st.tp1_sent = False; st.tp2_sent = False; st.tp3_sent = False; st.sl_sent = False
                    else:
                        st.finished = True; st.reset_cycle()

    def _set_levels(self, st: SetupState, entry: float, sl: float, side: str, entry_min: float = 0.0, entry_max: float = 0.0) -> None:
        risk = abs(entry - sl)
        if risk <= 0: risk = entry * 0.001
        
        # High ROI / R:R config for Double-Strike (1:2, 1:4, 1:8 due to massive expected drop & tight SL)
        if side == "BUY":
            tp1 = entry + risk * 2.0
            tp2 = entry + risk * 4.0
            tp3 = entry + risk * 8.0
            emin = entry_min if entry_min > 0 else entry - risk * 0.2
            emax = entry_max if entry_max > 0 else entry
        else:
            tp1 = entry - risk * 2.0
            tp2 = entry - risk * 4.0
            tp3 = entry - risk * 8.0
            emin = entry_min if entry_min > 0 else entry
            emax = entry_max if entry_max > 0 else entry + risk * 0.2
            
        st.levels = {
            "entry": entry, "entry_min": min(emin, emax), "entry_max": max(emin, emax), 
            "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3
        }

    # -------- Telegram message builders --------

    def _send_confirmed(self, st: SetupState, price: float, zname: str) -> None:
        if st.confirmed_sent: return
        st.confirmed_sent = True
        
        sig_type_note = f"⚠️ {st.setup_type}"

        if CORNIX_ENABLED == "1":
            msg = self._build_cornix_signal(st, price, zname)
            msg = msg + f"\n[NOTE: {sig_type_note}]"
            mid = send_telegram(msg, chat_id=self._chat_signals())
            if mid and SEND_CHART_IMAGE == "1":
                try:
                    img = render_zones_chart(self.tv, st.symbol, st.tf, st.side, st.zone1, st.zone2)
                    if img:
                        cap = f"CHART {self._cornix_pair(st.symbol).replace('/', '-')} TF {st.tf} ARAH {('LONG' if st.side=='BUY' else 'SHORT')} CONFIRMED"
                        target = self._chat_updates() if CHART_IMAGE_CHAT != "SIGNALS" else self._chat_signals()
                        send_telegram_photo(img, caption=cap, chat_id=target)
                except Exception as _e:
                    pass
            print(msg)
            return

        emoji = "🟢" if st.side == "BUY" else "🔴"
        z2txt = "-" if not st.zone2 else f"{self._fmt(st.zone2.low)} - {self._fmt(st.zone2.high)}"
        msg = "\n".join([
            f"{emoji} SINYAL KONFIRMASI — {st.side}",
            sig_type_note,
            f"Pair: {st.symbol} (TV: BINANCE:{st.symbol}.P)",
            f"TF: {st.tf}",
            f"Harga Konfirmasi: {self._fmt(price)}",
            "",
            f"Area Entry Ideal: {self._fmt(st.levels.get('entry_min', st.levels['entry']))} - {self._fmt(st.levels.get('entry_max', st.levels['entry']))}",
            f"Titik Ekstrim (POI): {self._fmt(st.extreme_price)}",
            f"Zona Konfirmasi: {zname}",
            "",
            f"TP1: {self._fmt(st.levels['tp1'])} | TP2: {self._fmt(st.levels['tp2'])} | TP3: {self._fmt(st.levels['tp3'])}",
            f"SL Ideal: {self._fmt(st.levels['sl'])}",
        ])
        
        # Build cornix format and inline button
        import urllib.parse
        cornix_str = self._build_cornix_signal(st, price, zname)
        cornix_url = f"https://t.me/cornix_trading_bot?start={urllib.parse.quote(cornix_str)}"
        
        reply_markup = {
            "inline_keyboard": [[
                {"text": "🚀 Follow Signal (Cornix)", "url": cornix_url}
            ]]
        }
        
        # Send human-readable alert with the cornix button attached
        send_telegram(msg, chat_id=self._chat_signals(), reply_markup=reply_markup)
        print(msg)
        print("\n--- CORNIX PAYLOAD (URL) ---\n" + cornix_str + "\n----------------------------\n")


    def _send_tp(self, st: SetupState, price: float, tp: str) -> None:
        num = tp.replace("TP", "").strip()
        title = f"UPDATE TARGET {num} TERCAPAI"
        extra = f"MASUK {self._fmt(st.levels['entry'])} | BATAS {self._fmt(st.levels['sl'])}"
        msg = self._build_update_text(title, st, price, extra=extra)
        send_telegram(msg, chat_id=self._chat_updates())
        print(msg)

    def _send_sl(self, st: SetupState, price: float) -> None:
        title = "UPDATE STOPLOSS HIT"
        extra = f"BATAS {self._fmt(st.levels['sl'])}"
        msg = self._build_update_text(title, st, price, extra=extra)
        send_telegram(msg, chat_id=self._chat_updates())
        print(msg)



def build_symbol_list() -> List[str]:
    if SYMBOLS_ENV.upper() == "ALL":
        syms = discover_binance_usdt_perp_symbols()
        if MAX_SYMBOLS > 0:
            syms = syms[:MAX_SYMBOLS]
        return syms
    syms = [s.strip().upper() for s in SYMBOLS_ENV.split(",") if s.strip()]
    if MAX_SYMBOLS > 0:
        syms = syms[:MAX_SYMBOLS]
    return syms


# =========================
# Main
# =========================

def main() -> None:
    symbols = build_symbol_list()
    print("[INFO] VERSION=v17_3_nocancel_fix (CORNIX_LEVERAGE + TV retry)")
    print("[INFO] VERSION=v17_nocancel (indent fix + chart vars + sendPhoto)")

    print("[INFO] TradingView-only Signal Bot v16_fixed5 (Auto-cancel expired Cornix entries)")
    print(f"[INFO] SYMBOLS='{SYMBOLS_ENV}' | MAX_SYMBOLS={MAX_SYMBOLS} | MIN_TV_VOLUME_1D={MIN_TV_VOLUME_1D}")
    print(f"[INFO] Timeframes: {list(TIMEFRAMES.keys())}")
    if not symbols:
        raise RuntimeError("Symbol list kosong. Isi SYMBOLS manual atau gunakan SYMBOLS=ALL")
    print(f"[INFO] Symbols loaded ({len(symbols)}): {symbols[:20]}{' ...' if len(symbols) > 20 else ''}")

    tv = TradingViewClient(username=TV_USERNAME, password=TV_PASSWORD)
    eng = SignalEngine(tv)

    while True:
        try:
            for symbol in symbols:
                price = eng.get_price(symbol)
                for tf in TIMEFRAMES.keys():
                    eng.process_symbol_tf(symbol, tf, price)
            time.sleep(LOOP_SLEEP_SEC)
        except KeyboardInterrupt:
            print("\n[INFO] Stop by user.")
            return
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
