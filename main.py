import asyncio
import sqlite3
import ccxt.async_support as ccxt_async
import pandas as pd
import numpy as np
import json
import os
import httpx
import csv
from datetime import datetime, time
from dataclasses import dataclass, field, asdict
import aiofiles

# =========================================================
# ⚙️ الإعدادات العامة (قابلة للتعديل)
# =========================================================
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"

LOG_DIR = "/tmp/trading_logs"
DB_FILE = os.path.join(LOG_DIR, "empire_v32.db")
REAL_CSV = os.path.join(LOG_DIR, "real_trades.csv")
MISSED_CSV = os.path.join(LOG_DIR, "missed_trades.csv")
OPPORTUNITIES_CSV = os.path.join(LOG_DIR, "opportunities.csv")
os.makedirs(LOG_DIR, exist_ok=True)

# إعدادات التداول
MAX_CONCURRENT_TRADES = 50
RISK_PER_TRADE = 0.02
STOP_LOSS_PCT = 0.025
TRAILING_ACTIVATE_PCT = 2.0
TRAILING_DISTANCE_PCT = 1.5
PARTIAL_TP_PCT = 4.0
PARTIAL_CLOSE_RATIO = 0.5
FINAL_TP_PCT = 8.0

# إعدادات المسح
TOTAL_SYMBOLS_TO_SCAN = 1000
SCAN_INTERVAL = 10
BATCH_SIZE = 50

# شروط الاختيار
MIN_VOTES = 3
ENABLE_EXPLOSION_FILTER = True
EXPLOSION_FILTER_MIN_CONDITIONS = 2
MIN_24H_VOLUME_USD = 300000
MAX_SPREAD_PCT = 0.2

# فلتر الوقت (معطل)
ENABLE_TIME_FILTER = False
TIME_FILTER_START = 14
TIME_FILTER_END = 22

MIN_SCORE_FOR_WATCH = 60

# فلاتر الرموز (استبعاد العملات المستقرة والكبيرة جداً)
EXCLUDE_STABLECOINS = True
EXCLUDE_VERY_LARGE_CAP = True
MAX_24H_VOLUME_USD_FILTER = 500_000_000
MIN_PRICE_USD = 0.00001
MAX_PRICE_USD = 500
STABLECOINS = ["USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "FDUSD", "UST", "USDD", "FRAX", "GUSD", "HUSD", "PAX", "USDK"]

# إعدادات الإرسال التلقائي لـ CSV
AUTO_SEND_CSV = True
AUTO_SEND_INTERVAL_HOURS = 1          # كل ساعة
AUTO_SEND_FILE = OPPORTUNITIES_CSV     # الملف المرسل (يمكن تغييره إلى REAL_CSV أو MISSED_CSV)
AUTO_SEND_CAPTION = "📊 تقرير تلقائي: سجل جميع الفرص (آخر ساعة)"

# =========================================================
# هياكل البيانات
# =========================================================
@dataclass
class TrainSignal:
    symbol: str
    entry_price: float
    expected_pump_pct: float
    votes: int
    strategies: list
    score: float
    candle_patterns: list = field(default_factory=list)
    reason: str = ""
    entry_point: float = 0.0
    extra_scores: dict = field(default_factory=dict)
    time_found: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))

@dataclass
class TradeInfo:
    symbol: str
    signal: TrainSignal
    entry_price: float
    invested: float
    highest_price: float
    stop_loss: float
    take_profit: float
    entry_time: str = field(default_factory=lambda: datetime.now().isoformat())
    partial_closed: bool = False

# =========================================================
# المحرك الرئيسي (مع حفظ الحالة)
# =========================================================
class EmpireEngineV32:
    def __init__(self):
        self.active_trades = {}
        self.missed_trades = []
        self.watchlist = []
        self.all_opportunities = []
        self.balance = 2000.0
        self.stats = {"scanned": 0, "opportunities_found": 0, "last_scan_time": None}
        self._init_storage()
        self._load_state_sync()

    def _init_storage(self):
        conn = sqlite3.connect(DB_FILE)
        conn.execute("CREATE TABLE IF NOT EXISTS active_trades (symbol TEXT PRIMARY KEY, data TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value REAL)")
        if not conn.execute("SELECT value FROM config WHERE key='balance'").fetchone():
            conn.execute("INSERT INTO config VALUES ('balance', 2000.0)")
        conn.commit()
        conn.close()
        for f in [REAL_CSV, MISSED_CSV]:
            if not os.path.exists(f):
                with open(f, 'w', newline='') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(['Time', 'Symbol', 'Entry', 'Exit', 'PNL%'])
        if not os.path.exists(OPPORTUNITIES_CSV):
            with open(OPPORTUNITIES_CSV, 'w', encoding='utf-8') as f:
                f.write("Time,Symbol,Price,EntryPoint,ExpectedPump%,Votes,Score,Reason,Strategies,CandlePatterns,ExtraScores\n")

    def _load_state_sync(self):
        conn = sqlite3.connect(DB_FILE)
        try:
            row = conn.execute("SELECT value FROM config WHERE key='balance'").fetchone()
            if row:
                self.balance = row[0]
            rows = conn.execute("SELECT data FROM active_trades").fetchall()
            for (data_json,) in rows:
                d = json.loads(data_json)
                sig_dict = d.pop('signal')
                signal = TrainSignal(**sig_dict)
                trade = TradeInfo(**d, signal=signal)
                self.active_trades[trade.symbol] = trade
            print(f"Loaded {len(self.active_trades)} active trades, balance={self.balance}")
        except Exception as e:
            print(f"Load state error: {e}")
        finally:
            conn.close()

    async def _save_state(self):
        conn = sqlite3.connect(DB_FILE)
        try:
            conn.execute("DELETE FROM active_trades")
            for sym, trade in self.active_trades.items():
                data = asdict(trade)
                data['signal'] = asdict(trade.signal)
                conn.execute("INSERT INTO active_trades VALUES (?, ?)", (sym, json.dumps(data)))
            conn.execute("UPDATE config SET value = ? WHERE key = 'balance'", (self.balance,))
            conn.commit()
        except Exception as e:
            print(f"Save state error: {e}")
        finally:
            conn.close()

    async def log_opportunity(self, symbol, price, entry_point, expected_pump, votes, score, reason, strategies, candle_patterns=None, extra_scores=None):
        async with aiofiles.open(OPPORTUNITIES_CSV, 'a', encoding='utf-8') as f:
            line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')},{symbol},{price},{entry_point},{expected_pump},{votes},{score:.2f},{reason},{'|'.join(strategies)},{'|'.join(candle_patterns) if candle_patterns else ''},{json.dumps(extra_scores or {})}"
            await f.write(line + "\n")

    # ---------- فلتر الانفجار السريع ----------
    async def explosion_filter(self, df):
        if len(df) < 30:
            return False, []
        avg_volume = df['v'].rolling(20).mean().iloc[-2]
        current_volume = df['v'].iloc[-1]
        volume_ok = (current_volume > avg_volume * 1.5) if avg_volume > 0 else False
        price_change_3 = (df['c'].iloc[-1] - df['c'].iloc[-4]) / df['c'].iloc[-4] * 100
        momentum_ok = price_change_3 > 1.0
        sma = df['c'].rolling(20).mean()
        std = df['c'].rolling(20).std()
        upper_bb = sma + (1.5 * std)
        bb_break_ok = df['c'].iloc[-1] > upper_bb.iloc[-1]
        lower_bb = sma - (2 * std)
        bw = (upper_bb - lower_bb) / sma
        squeeze_ok = bw.iloc[-1] < 0.07
        delta = df['c'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain / (loss + 1e-9)))
        rsi_val = rsi.iloc[-1]
        rsi_increasing = rsi.iloc[-1] > rsi.iloc[-2] > rsi.iloc[-3]
        rsi_ok = rsi_val > 50 or rsi_increasing
        conditions = []
        if volume_ok: conditions.append("VolumeSpike")
        if momentum_ok: conditions.append("Momentum3")
        if bb_break_ok: conditions.append("BBBreak")
        if squeeze_ok: conditions.append("Squeeze")
        if rsi_ok: conditions.append("RSI_Dynamic")
        passed = len(conditions) >= EXPLOSION_FILTER_MIN_CONDITIONS
        return passed, conditions

    # ---------- أنماط الشموع اليابانية ----------
    def detect_candlestick_patterns(self, df):
        if len(df) < 30:
            return 0, 0, [], False
        bullish_score = 0
        bearish_score = 0
        patterns = []
        is_exit = False
        avg_volume = df['v'].rolling(20).mean().iloc[-1]
        if avg_volume == 0:
            avg_volume = df['v'].iloc[-1]
        # Three Line Strike
        if len(df) >= 4:
            last_4 = df.iloc[-4:]
            if (all(last_4['c'].iloc[i] < last_4['c'].iloc[i-1] for i in range(1, 4)) and
                last_4['c'].iloc[-1] > last_4['h'].iloc[-2] and
                last_4['c'].iloc[-1] > last_4['o'].iloc[-1] and
                df['v'].iloc[-1] > avg_volume * 1.5):
                bullish_score += 25
                patterns.append("ThreeLineStrike")
        # Hammer
        body = abs(df['c'].iloc[-1] - df['o'].iloc[-1])
        lower_wick = min(df['o'].iloc[-1], df['c'].iloc[-1]) - df['l'].iloc[-1]
        upper_wick = df['h'].iloc[-1] - max(df['o'].iloc[-1], df['c'].iloc[-1])
        if body > 0 and lower_wick > body * 2 and upper_wick < body * 0.5:
            if df['v'].iloc[-1] > avg_volume * 1.2:
                bullish_score += 15
                patterns.append("Hammer")
        # Bullish Engulfing
        if len(df) >= 2:
            if (df['c'].iloc[-1] > df['o'].iloc[-1] and 
                df['o'].iloc[-1] < df['c'].iloc[-2] and 
                df['c'].iloc[-1] > df['o'].iloc[-2] and
                df['v'].iloc[-1] > avg_volume * 1.3):
                bullish_score += 15
                patterns.append("BullishEngulfing")
        # Morning Star
        if len(df) >= 3:
            last_3 = df.iloc[-3:]
            if (last_3['c'].iloc[-3] < last_3['o'].iloc[-3] and
                abs(last_3['c'].iloc[-2] - last_3['o'].iloc[-2]) < abs(last_3['c'].iloc[-3] - last_3['o'].iloc[-3]) * 0.3 and
                last_3['c'].iloc[-1] > last_3['o'].iloc[-1] and
                last_3['c'].iloc[-1] > (last_3['h'].iloc[-3] + last_3['l'].iloc[-3]) / 2 and
                df['v'].iloc[-1] > avg_volume * 1.2):
                bullish_score += 18
                patterns.append("MorningStar")
        # Piercing Line
        if len(df) >= 2:
            if (df['c'].iloc[-2] < df['o'].iloc[-2] and
                df['c'].iloc[-1] > df['o'].iloc[-1] and
                df['o'].iloc[-1] < df['c'].iloc[-2] and
                df['c'].iloc[-1] > (df['c'].iloc[-2] + df['o'].iloc[-2]) / 2 and
                df['v'].iloc[-1] > avg_volume * 1.2):
                bullish_score += 12
                patterns.append("PiercingLine")
        # Three Black Crows
        if len(df) >= 3:
            last_3 = df.iloc[-3:]
            if (all(last_3['c'].iloc[i] < last_3['c'].iloc[i-1] for i in range(1, 3)) and
                all(last_3['h'].iloc[i] - last_3['l'].iloc[i] > (df['h'].iloc[-5] - df['l'].iloc[-5]) * 0.7 for i in range(3))):
                bearish_score += 20
                patterns.append("ThreeBlackCrows")
                is_exit = True
        # Evening Star
        if len(df) >= 3:
            last_3 = df.iloc[-3:]
            if (last_3['c'].iloc[-3] > last_3['o'].iloc[-3] and
                abs(last_3['c'].iloc[-2] - last_3['o'].iloc[-2]) < abs(last_3['c'].iloc[-3] - last_3['o'].iloc[-3]) * 0.3 and
                last_3['c'].iloc[-1] < last_3['o'].iloc[-1] and
                last_3['c'].iloc[-1] < (last_3['l'].iloc[-3] + last_3['h'].iloc[-3]) / 2):
                bearish_score += 15
                patterns.append("EveningStar")
                is_exit = True
        # Shooting Star
        if body > 0 and upper_wick > body * 2 and lower_wick < body * 0.5:
            bearish_score += 12
            patterns.append("ShootingStar")
            is_exit = True
        return bullish_score, bearish_score, patterns, is_exit

    async def get_market_condition_score(self, ex, symbol):
        try:
            ohlcv_15 = await ex.fetch_ohlcv(symbol, timeframe='15m', limit=30)
            ohlcv_1h = await ex.fetch_ohlcv(symbol, timeframe='1h', limit=100)
            if len(ohlcv_15) < 30 or len(ohlcv_1h) < 50:
                return 0, "Insufficient data"
            df_15 = pd.DataFrame(ohlcv_15, columns=['t','o','h','l','c','v'])
            df_1h = pd.DataFrame(ohlcv_1h, columns=['t','o','h','l','c','v'])
            price_15 = df_15['c'].iloc[-1]
            ema50_15 = df_15['c'].ewm(span=50).mean().iloc[-1]
            ema50_1h = df_1h['c'].ewm(span=50).mean().iloc[-1]
            ema200_1h = df_1h['c'].ewm(span=200).mean().iloc[-1]
            if price_15 > ema50_15 and ema50_1h > ema200_1h:
                return 15, "Strong Uptrend"
            elif price_15 > ema50_15:
                return 5, "Weak Uptrend"
            elif price_15 < ema50_15:
                return -15, "Downtrend"
            else:
                return -5, "Sideways"
        except:
            return 0, "Error"

    async def get_golden_cross_score(self, ex, symbol):
        try:
            ohlcv_4h = await ex.fetch_ohlcv(symbol, timeframe='4h', limit=100)
            if len(ohlcv_4h) < 50:
                return 0, None
            df = pd.DataFrame(ohlcv_4h, columns=['t','o','h','l','c','v'])
            ema50 = df['c'].ewm(span=50).mean()
            ema200 = df['c'].ewm(span=200).mean()
            for i in range(-3, 0):
                if ema50.iloc[i] > ema200.iloc[i] and ema50.iloc[i-1] <= ema200.iloc[i-1]:
                    return 10, "Golden Cross (4h)"
            return 0, None
        except:
            return 0, None

    async def analyze(self, ex, symbol):
        reason = None
        try:
            if ENABLE_TIME_FILTER:
                now_utc = datetime.utcnow().time()
                if not (time(TIME_FILTER_START,0) <= now_utc <= time(TIME_FILTER_END,0)):
                    reason = "وقت غير مناسب"
                    return None, reason

            ohlcv_15 = await ex.fetch_ohlcv(symbol, timeframe='15m', limit=30)
            if len(ohlcv_15) < 30:
                reason = "بيانات 15 دقيقة غير كافية"
                return None, reason
            df_15 = pd.DataFrame(ohlcv_15, columns=['t','o','h','l','c','v'])
            ema50_15 = df_15['c'].ewm(span=50).mean().iloc[-1]
            if df_15['c'].iloc[-1] < ema50_15:
                reason = "اتجاه هابط"
                return None, reason

            ohlcv = await ex.fetch_ohlcv(symbol, timeframe='5m', limit=100)
            if len(ohlcv) < 60:
                reason = "بيانات 5 دقائق غير كافية"
                return None, reason
            df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])

            if ENABLE_EXPLOSION_FILTER:
                passed, _ = await self.explosion_filter(df)
                if not passed:
                    reason = "فلتر الانفجار"
                    return None, reason

            ticker = await ex.fetch_ticker(symbol)
            vol_24h = ticker['quoteVolume'] if 'quoteVolume' in ticker else ticker['volume'] * ticker['last']
            spread = (ticker['ask'] - ticker['bid']) / ticker['last'] * 100 if ticker['ask'] and ticker['bid'] else 100
            if vol_24h < MIN_24H_VOLUME_USD:
                reason = "حجم منخفض"
                return None, reason
            if spread > MAX_SPREAD_PCT:
                reason = "سبريد عالٍ"
                return None, reason

            sma = df['c'].rolling(20).mean()
            std = df['c'].rolling(20).std()
            upper_bb = sma + (2 * std)
            lower_bb = sma - (2 * std)
            bw = (upper_bb - lower_bb) / sma

            delta = df['c'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi = 100 - (100 / (1 + gain / (loss + 1e-9)))
            rsi_val = rsi.iloc[-1]
            if rsi_val < 25 or rsi_val > 88:
                reason = "RSI مشبع"
                return None, reason

            atr = (df['h'].rolling(14).max() - df['l'].rolling(14).min()) / 14
            volatility = atr.iloc[-1] / df['c'].iloc[-1] * 100
            if volatility > 6.0:
                reason = "تقلب عالي"
                return None, reason

            exp1 = df['c'].ewm(span=12).mean()
            exp2 = df['c'].ewm(span=26).mean()
            macd = exp1 - exp2
            macd_signal = macd.ewm(span=9).mean()
            macd_hist = macd - macd_signal
            macd_bullish = macd.iloc[-1] > macd_signal.iloc[-1] and macd_hist.iloc[-1] > macd_hist.iloc[-2]

            divergence = None
            if len(df) >= 20:
                price_lows = []
                rsi_lows = []
                for i in range(-20, -1):
                    if df['c'].iloc[i] <= df['c'].iloc[i-1] and df['c'].iloc[i] <= df['c'].iloc[i+1]:
                        price_lows.append(df['c'].iloc[i])
                    if rsi.iloc[i] <= rsi.iloc[i-1] and rsi.iloc[i] <= rsi.iloc[i+1]:
                        rsi_lows.append(rsi.iloc[i])
                if len(price_lows) >= 2 and len(rsi_lows) >= 2:
                    if price_lows[-1] < price_lows[-2] and rsi_lows[-1] > rsi_lows[-2]:
                        divergence = "bullish"
                    elif price_lows[-1] > price_lows[-2] and rsi_lows[-1] < rsi_lows[-2]:
                        divergence = "bearish"

            market_score, _ = await self.get_market_condition_score(ex, symbol)
            golden_score, _ = await self.get_golden_cross_score(ex, symbol)

            avg_volume = df['v'].rolling(20).mean().iloc[-2]
            volume_ratio = df['v'].iloc[-1] / avg_volume if avg_volume > 0 else 1

            votes = []
            if bw.iloc[-1] < bw.rolling(30).min().iloc[-2] * 1.2:
                votes.append("Squeeze")
            if df['c'].iloc[-1] > sma.iloc[-1]:
                votes.append("Uptrend")
            if volume_ratio > 1.8:
                votes.append("Volume")
            if rsi_val > 52:
                votes.append("Momentum")
            if df['c'].iloc[-1] > upper_bb.iloc[-1]:
                votes.append("Breakout")
            if macd_bullish:
                votes.append("MACD")
            if divergence == "bullish":
                votes.append("BullishDivergence")

            base_score = len(votes) * 10
            rsi_score = max(0, (rsi_val - 50) / 6) if rsi_val > 50 else 0
            volume_score = min(volume_ratio * 4, 12)
            bw_score = max(0, (0.5 - bw.iloc[-1]) * 15) if bw.iloc[-1] < 0.5 else 0
            liquidity_score = 10 if vol_24h > 200_000_000 else (7 if vol_24h > 50_000_000 else (3 if vol_24h > 5_000_000 else 0))
            spread_score = 8 if spread < 0.08 else 0
            volume_spike_score = 15 if volume_ratio >= 5 else (10 if volume_ratio >= 3 else (5 if volume_ratio >= 1.8 else 0))

            total_score = base_score + rsi_score + volume_score + bw_score + liquidity_score + spread_score + volume_spike_score + market_score + (golden_score or 0)
            if divergence == "bullish":
                total_score += 15
            total_score = round(total_score, 2)

            candle_bullish, candle_bearish, candle_patterns, _ = self.detect_candlestick_patterns(df)
            if candle_bearish >= 15:
                reason = "نمط هابط"
                return None, reason
            total_score += candle_bullish

            expected_pump = (volume_ratio * 1.2) + (bw.iloc[-1] * 40) + (rsi_val / 25)
            expected_pump = min(expected_pump, 12.0)

            ask_price = ticker['ask'] if ticker['ask'] else df['c'].iloc[-1] * (1 + spread/100)
            entry_point = ask_price

            if len(votes) >= MIN_VOTES:
                extra_scores = {
                    'base': base_score, 'rsi': round(rsi_score,2), 'volume': volume_score,
                    'bw': round(bw_score,2), 'liquidity': liquidity_score, 'spread': spread_score,
                    'spike': volume_spike_score, 'market': market_score, 'golden': golden_score or 0,
                    'divergence': 15 if divergence == 'bullish' else 0,
                    'candle_bullish': candle_bullish
                }
                signal = TrainSignal(
                    symbol=symbol,
                    entry_price=df['c'].iloc[-1],
                    expected_pump_pct=round(expected_pump, 2),
                    votes=len(votes),
                    strategies=votes,
                    score=total_score,
                    candle_patterns=candle_patterns,
                    entry_point=round(entry_point, 8),
                    extra_scores=extra_scores
                )
                return signal, None
            else:
                reason = f"أصوات غير كافية ({len(votes)}/{MIN_VOTES})"
                return None, reason
        except Exception as e:
            reason = f"خطأ: {str(e)[:50]}"
            return None, reason

    async def update_trades(self, ex):
        for sym, trade in list(self.active_trades.items()):
            try:
                ticker = await ex.fetch_ticker(sym)
                curr = ticker['last']
                pnl = (curr - trade.entry_price) / trade.entry_price * 100
                if curr > trade.highest_price:
                    trade.highest_price = curr

                if not trade.partial_closed and pnl >= PARTIAL_TP_PCT:
                    close_amount = trade.invested * PARTIAL_CLOSE_RATIO
                    profit_partial = close_amount * (pnl / 100)
                    self.balance += close_amount + profit_partial
                    trade.invested -= close_amount
                    trade.partial_closed = True
                    await send_tg(f"📊 *جني أرباح جزئي {sym}*\nالربح: {pnl:.2f}% | المتبقي: {trade.invested:.2f} USDT")
                    await self._save_state()

                if pnl >= TRAILING_ACTIVATE_PCT:
                    new_stop = trade.entry_price * (1 + (pnl - TRAILING_DISTANCE_PCT)/100)
                    if new_stop > trade.stop_loss:
                        trade.stop_loss = new_stop

                exit_reason = None
                if pnl <= -STOP_LOSS_PCT * 100:
                    exit_reason = "Stop Loss"
                elif trade.partial_closed and pnl <= (TRAILING_ACTIVATE_PCT - 1):
                    exit_reason = "Trailing Stop (remainder)"
                elif pnl >= FINAL_TP_PCT:
                    exit_reason = "Final Take Profit"
                elif curr <= trade.stop_loss and trade.stop_loss > trade.entry_price:
                    exit_reason = "Trailing Stop"

                if exit_reason:
                    total_pnl = (curr - trade.entry_price) / trade.entry_price * 100
                    self.balance += trade.invested * (1 + total_pnl/100)
                    await self._save_state()
                    async with aiofiles.open(REAL_CSV, 'a') as f:
                        await f.write(f"{datetime.now().isoformat()},{sym},{trade.entry_price},{curr},{total_pnl:.2f}\n")
                    await send_tg(f"🏁 *إغلاق {sym}*\nالربح: `{total_pnl:.2f}%`\nالسبب: {exit_reason}\nالرصيد: {self.balance:.2f} USDT")
                    del self.active_trades[sym]
                    await self._save_state()
            except Exception as e:
                print(f"Update trade error: {e}")

# =========================================================
# دوال تلغرام
# =========================================================
async def send_tg(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except:
        pass

async def send_document(file_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    try:
        async with httpx.AsyncClient() as client:
            with open(file_path, 'rb') as f:
                files = {'document': f}
                data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
                await client.post(url, data=data, files=files)
    except Exception as e:
        print(f"Send doc error: {e}")

async def handle_telegram_commands():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id+1}&timeout=30"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                data = resp.json()
                if data['ok']:
                    for update in data['result']:
                        last_update_id = update['update_id']
                        if 'message' in update and 'text' in update['message']:
                            text = update['message']['text'].strip()
                            if text == '/start':
                                await send_tg("مرحباً! البوت V32 (نهائي) - إرسال CSV تلقائي كل ساعة\nالأوامر:\n/download_real\n/download_missed\n/download_opp\n/status")
                            elif text == '/download_real':
                                if os.path.exists(REAL_CSV):
                                    await send_document(REAL_CSV, "سجل الصفقات الحقيقية")
                                else:
                                    await send_tg("⚠️ الملف غير موجود.")
                            elif text == '/download_missed':
                                if os.path.exists(MISSED_CSV):
                                    await send_document(MISSED_CSV, "الفرص الضائعة")
                                else:
                                    await send_tg("⚠️ الملف غير موجود.")
                            elif text == '/download_opp':
                                if os.path.exists(OPPORTUNITIES_CSV):
                                    await send_document(OPPORTUNITIES_CSV, "سجل كل الفرص")
                                else:
                                    await send_tg("⚠️ الملف غير موجود.")
                            elif text == '/status':
                                await send_tg(f"📈 الحالة\nالرصيد: {engine.balance:.2f} USDT\nصفقات مفتوحة: {len(engine.active_trades)}/{MAX_CONCURRENT_TRADES}")
        except:
            pass
        await asyncio.sleep(2)

# =========================================================
# مهمة الإرسال التلقائي لـ CSV
# =========================================================
async def auto_send_csv_periodically():
    """إرسال ملف CSV تلقائياً كل AUTO_SEND_INTERVAL_HOURS ساعة"""
    if not AUTO_SEND_CSV:
        return
    await asyncio.sleep(60)  # تأخير البداية لتجنب الإرسال فور التشغيل
    while True:
        try:
            if os.path.exists(AUTO_SEND_FILE):
                await send_document(AUTO_SEND_FILE, AUTO_SEND_CAPTION)
                print(f"[{datetime.now()}] Auto-sent {AUTO_SEND_FILE}")
            else:
                print(f"[{datetime.now()}] File {AUTO_SEND_FILE} not found")
        except Exception as e:
            print(f"Auto-send error: {e}")
        await asyncio.sleep(AUTO_SEND_INTERVAL_HOURS * 3600)

# =========================================================
# حلقة التداول الرئيسية (مع فلتر الرموز)
# =========================================================
async def main_loop():
    global engine
    ex = ccxt_async.gateio({'enableRateLimit': True})
    await send_tg("🚀 Empire V32 (نهائي) بدأ - إرسال CSV تلقائي كل ساعة")
    
    # جلب جميع الرموز وتصفيتها
    markets = await ex.fetch_markets()
    raw_symbols = [m for m in markets if m['symbol'].endswith('/USDT') and m['active']]
    symbols = []
    
    for market in raw_symbols:
        base = market['base']
        if EXCLUDE_STABLECOINS and base in STABLECOINS:
            continue
        try:
            ticker = await ex.fetch_ticker(market['symbol'])
            vol_24h = ticker['quoteVolume'] if 'quoteVolume' in ticker else ticker['volume'] * ticker['last']
            price = ticker['last']
            if EXCLUDE_VERY_LARGE_CAP and vol_24h > MAX_24H_VOLUME_USD_FILTER:
                continue
            if price < MIN_PRICE_USD or price > MAX_PRICE_USD:
                continue
            symbols.append(market['symbol'])
        except:
            continue
    
    symbols = symbols[:TOTAL_SYMBOLS_TO_SCAN]
    await send_tg(f"📊 {len(symbols)} عملة مؤهلة للمسح (بعد استبعاد المستقرة والكبيرة)")
    
    while True:
        try:
            scan_start = datetime.now()
            engine.stats["scanned"] = 0
            engine.stats["opportunities_found"] = 0
            random_symbols = np.random.choice(symbols, min(len(symbols), TOTAL_SYMBOLS_TO_SCAN), replace=False)
            all_signals = []
            
            for i in range(0, len(random_symbols), BATCH_SIZE):
                batch = random_symbols[i:i+BATCH_SIZE]
                tasks = [engine.analyze(ex, s) for s in batch]
                results = await asyncio.gather(*tasks)
                for (sig, reason), symbol in zip(results, batch):
                    if sig:
                        all_signals.append(sig)
                        engine.stats["opportunities_found"] += 1
                        await engine.log_opportunity(sig.symbol, sig.entry_price, sig.entry_point, sig.expected_pump_pct,
                                                     sig.votes, sig.score, "إشارة قوية", sig.strategies, sig.candle_patterns, sig.extra_scores)
                        engine.all_opportunities.append(sig)
                    else:
                        dummy = TrainSignal(symbol=symbol, entry_price=0, expected_pump_pct=0, votes=0,
                                            strategies=[], score=0, reason=reason or "لا توجد إشارة", entry_point=0)
                        engine.all_opportunities.append(dummy)
                        await engine.log_opportunity(symbol, 0, 0, 0, 0, 0, reason or "لا توجد إشارة", [], [], {})
                        if len(engine.all_opportunities) > 500:
                            engine.all_opportunities = engine.all_opportunities[-500:]
                engine.stats["scanned"] += len(batch)
                await asyncio.sleep(0.1)
            
            all_signals.sort(key=lambda x: x.score, reverse=True)
            if all_signals:
                best = all_signals[0]
                await send_tg(f"🏆 أفضل عملة: {best.symbol} | سكور {best.score} | ارتفاع متوقع {best.expected_pump_pct}%")
                if best.symbol not in engine.active_trades:
                    risk_amount = engine.balance * RISK_PER_TRADE
                    position_size = risk_amount / STOP_LOSS_PCT
                    invest = min(position_size, engine.balance)
                    if len(engine.active_trades) < MAX_CONCURRENT_TRADES and engine.balance >= invest:
                        stop_loss_price = best.entry_point * (1 - STOP_LOSS_PCT)
                        take_profit_price = best.entry_point * (1 + FINAL_TP_PCT/100)
                        trade = TradeInfo(
                            symbol=best.symbol,
                            signal=best,
                            entry_price=best.entry_point,
                            invested=invest,
                            highest_price=best.entry_point,
                            stop_loss=stop_loss_price,
                            take_profit=take_profit_price,
                            partial_closed=False
                        )
                        engine.active_trades[best.symbol] = trade
                        engine.balance -= invest
                        await engine._save_state()
                        await send_tg(f"🟢 شراء {best.symbol} بمبلغ {invest:.2f} USDT")
                        await engine.log_opportunity(best.symbol, best.entry_price, best.entry_point, best.expected_pump_pct,
                                                     best.votes, best.score, "✅ تم الدخول", best.strategies, best.candle_patterns, best.extra_scores)
                    else:
                        await send_tg(f"⚠️ لا يمكن شراء {best.symbol}: حد الصفقات ({len(engine.active_trades)}/{MAX_CONCURRENT_TRADES}) أو رصيد غير كافٍ.")
            
            await engine.update_trades(ex)
            engine.stats["last_scan_time"] = scan_start.strftime("%H:%M:%S")
        except Exception as e:
            print("Main loop error:", e)
            await send_tg(f"⚠️ خطأ: {str(e)[:100]}")
            await asyncio.sleep(5)
        await asyncio.sleep(SCAN_INTERVAL)

# =========================================================
# تشغيل البوت
# =========================================================
async def main():
    global engine
    engine = EmpireEngineV32()
    asyncio.create_task(handle_telegram_commands())
    asyncio.create_task(auto_send_csv_periodically())   # إرسال CSV تلقائي
    await main_loop()

if __name__ == "__main__":
    asyncio.run(main())
