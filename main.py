#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام السكور المتكامل – 7 مؤشرات لاختيار العملات
First Station Multi-Indicator Scoring System

المؤشرات السبعة:
✅ 1. انخناق البولنجر باند (Bollinger Squeeze)
✅ 2. زيادة دخول السيولة (Volume Inflow)
✅ 3. أوامر البيع والشراء (Order Book Imbalance)
✅ 4. تجميع الحيتان (Whale Accumulation)
✅ 5. التقاطع الذهبي (Golden Cross)
✅ 6. الدايفرجنس RSI (RSI Divergence)
✅ 7. حالة السوق (Market Regime)

كل مؤشر يعطي 0-15 نقطة → السكور النهائي من 0-100
"""

import asyncio, pandas as pd, numpy as np, httpx, json, os, time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import ccxt.async_support as ccxt_async

# =========================================================
# إعدادات تليجرام
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
BOT_TAG = "#ScoringSystem"

# =========================================================
# 🎯 إعدادات النظام
# =========================================================
SIMULATION_CAPITAL = 500.0
BACKTEST_DAYS = 30
MIN_SCORE = 45  # الحد الأدنى للسكور للدخول

# =========================================================
# 🎯 العملات المستبعدة
# =========================================================
EXCLUDED = ['USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'BTC', 'ETH', 'BNB', 'XRP', 'SOL', 'ADA']
LEVERAGED = ['3S', '3L', '5S', '5L', 'X3', 'X5', 'BEAR', 'BULL', 'UP', 'DOWN']

def is_excluded(symbol: str) -> bool:
    base = symbol.split('/')[0]
    if base in EXCLUDED: return True
    if any(lev in base for lev in LEVERAGED): return True
    return False

# =========================================================
# دوال تليجرام
# =========================================================
async def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text.strip(), "parse_mode": "Markdown"})
    except: pass

# =========================================================
# 🧮 حاسبة السكور – 7 مؤشرات
# =========================================================
class ScoringEngine:
    """
    يحسب السكور النهائي للعملة بناءً على 7 مؤشرات
    كل مؤشر يعطي 0-15 نقطة (الإجمالي 0-105، يُقسم على 1.05 ليصبح 0-100)
    """
    
    def __init__(self, btc_ohlcv: np.ndarray = None):
        self.btc_ohlcv = btc_ohlcv
        
    def calculate_score(self, ohlcv_5m: np.ndarray, ohlcv_1h: np.ndarray, 
                        ticker: dict, orderbook: dict = None) -> dict:
        """
        يحسب السكور النهائي ويعيد تقريراً مفصلاً
        """
        if len(ohlcv_5m) < 50 or len(ohlcv_1h) < 30:
            return {'total_score': 0, 'details': {}, 'verdict': 'بيانات غير كافية'}
        
        closes_5m = ohlcv_5m[:, 4]
        volumes_5m = ohlcv_5m[:, 5]
        highs_5m = ohlcv_5m[:, 2]
        lows_5m = ohlcv_5m[:, 3]
        
        closes_1h = ohlcv_1h[:, 4]
        volumes_1h = ohlcv_1h[:, 5]
        
        current_price = ticker.get('last', closes_5m[-1])
        volume_24h = ticker.get('quoteVolume', 0) or 0
        
        details = {}
        total = 0
        
        # ============================
        # 1. انخناق البولنجر باند (0-15)
        # ============================
        boll_score, boll_detail = self._score_bollinger_squeeze(closes_5m, current_price)
        details['bollinger'] = boll_detail
        total += boll_score
        
        # ============================
        # 2. زيادة دخول السيولة (0-15)
        # ============================
        vol_score, vol_detail = self._score_volume_inflow(volumes_5m, volumes_1h, volume_24h)
        details['volume'] = vol_detail
        total += vol_score
        
        # ============================
        # 3. أوامر البيع والشراء (0-15)
        # ============================
        order_score, order_detail = self._score_order_imbalance(ticker, orderbook)
        details['orders'] = order_detail
        total += order_score
        
        # ============================
        # 4. تجميع الحيتان (0-15)
        # ============================
        whale_score, whale_detail = self._score_whale_accumulation(volumes_5m, closes_5m)
        details['whale'] = whale_detail
        total += whale_score
        
        # ============================
        # 5. التقاطع الذهبي (0-15)
        # ============================
        cross_score, cross_detail = self._score_golden_cross(closes_1h)
        details['golden_cross'] = cross_detail
        total += cross_score
        
        # ============================
        # 6. الدايفرجنس RSI (0-15)
        # ============================
        div_score, div_detail = self._score_rsi_divergence(closes_5m)
        details['rsi_divergence'] = div_detail
        total += div_score
        
        # ============================
        # 7. حالة السوق (0-15)
        # ============================
        market_score, market_detail = self._score_market_regime()
        details['market'] = market_detail
        total += market_score
        
        # السكور النهائي (تطبيع إلى 0-100)
        final_score = min(100, round(total / 1.05))
        
        # توصية
        if final_score >= 70:
            verdict = "✅ قوية جداً"
            action = "buy"
        elif final_score >= 55:
            verdict = "👍 جيدة"
            action = "buy"
        elif final_score >= 45:
            verdict = "📊 متوسطة"
            action = "watch"
        else:
            verdict = "❌ ضعيفة"
            action = "ignore"
        
        return {
            'total_score': final_score,
            'details': details,
            'verdict': verdict,
            'action': action,
            'current_price': current_price,
            'volume_24h': volume_24h
        }
    
    # ============================================================
    # 1. انخناق البولنجر باند (0-15)
    # ============================================================
    def _score_bollinger_squeeze(self, closes: np.ndarray, current_price: float) -> Tuple[float, dict]:
        recent = closes[-20:]
        middle = np.mean(recent)
        std = np.std(recent)
        upper = middle + 2 * std
        lower = middle - 2 * std
        
        bandwidth = (upper - lower) / middle * 100
        price_position = (current_price - lower) / (upper - lower) if upper != lower else 0.5
        
        score = 0
        reasons = []
        
        # عرض النطاق ضيق
        if bandwidth < 3.0:
            score += 8
            reasons.append(f'نطاق ضيق جداً ({bandwidth:.1f}%)')
        elif bandwidth < 5.0:
            score += 5
            reasons.append(f'نطاق ضيق ({bandwidth:.1f}%)')
        elif bandwidth < 7.0:
            score += 3
            reasons.append(f'نطاق متوسط ({bandwidth:.1f}%)')
        
        # السعر في القاع
        if price_position < 0.3:
            score += 7
            reasons.append(f'سعر عند القاع (موقع {price_position:.2f})')
        elif price_position < 0.5:
            score += 4
            reasons.append(f'سعر في المنتصف السفلي')
        
        return min(15, score), {'score': min(15, score), 'bandwidth': round(bandwidth, 2), 
                                'position': round(price_position, 2), 'reasons': reasons}
    
    # ============================================================
    # 2. زيادة دخول السيولة (0-15)
    # ============================================================
    def _score_volume_inflow(self, volumes_5m: np.ndarray, volumes_1h: np.ndarray, 
                             volume_24h: float) -> Tuple[float, dict]:
        score = 0
        reasons = []
        
        # حجم 24 ساعة
        if volume_24h > 500000:
            score += 5
            reasons.append(f'سيولة عالية (${volume_24h:,.0f})')
        elif volume_24h > 200000:
            score += 3
            reasons.append(f'سيولة متوسطة (${volume_24h:,.0f})')
        elif volume_24h > 100000:
            score += 1
        
        # ارتفاع الحجم الحالي
        avg_vol_5m = np.mean(volumes_5m[-10:])
        if volumes_5m[-1] > avg_vol_5m * 2.0:
            score += 5
            reasons.append(f'حجم 5د ×{volumes_5m[-1]/avg_vol_5m:.1f}')
        elif volumes_5m[-1] > avg_vol_5m * 1.5:
            score += 3
        
        # اتجاه الحجم (متزايد)
        if len(volumes_5m) >= 10:
            slope = np.polyfit(range(10), volumes_5m[-10:], 1)[0]
            if slope > 0:
                score += 5
                reasons.append('حجم متزايد')
        
        return min(15, score), {'score': min(15, score), 'volume_24h': volume_24h, 'reasons': reasons}
    
    # ============================================================
    # 3. أوامر البيع والشراء (0-15)
    # ============================================================
    def _score_order_imbalance(self, ticker: dict, orderbook: dict = None) -> Tuple[float, dict]:
        score = 0
        reasons = []
        
        # من التيكر - فرق السعر
        bid = ticker.get('bid', 0) or 0
        ask = ticker.get('ask', 0) or 0
        
        if bid > 0 and ask > 0:
            spread = (ask - bid) / bid * 100
            if spread < 0.15:
                score += 5
                reasons.append(f'سبريد ضيق ({spread:.2f}%)')
            elif spread < 0.3:
                score += 3
                reasons.append(f'سبريد مقبول ({spread:.2f}%)')
        
        # تغير 24 ساعة (إيجابي)
        change = ticker.get('percentage', 0) or 0
        if 1 < change < 8:
            score += 5
            reasons.append(f'زخم إيجابي (+{change:.1f}%)')
        elif 0 < change <= 1:
            score += 3
        
        # من دفتر الأوامر (إذا وجد)
        if orderbook:
            bids_volume = sum(b[1] for b in orderbook.get('bids', [])[:5])
            asks_volume = sum(a[1] for a in orderbook.get('asks', [])[:5])
            if bids_volume > asks_volume * 1.5:
                score += 5
                reasons.append(f'ضغط شرائي ({bids_volume/asks_volume:.1f}x)')
        
        return min(15, score), {'score': min(15, score), 'reasons': reasons}
    
    # ============================================================
    # 4. تجميع الحيتان (0-15)
    # ============================================================
    def _score_whale_accumulation(self, volumes: np.ndarray, closes: np.ndarray) -> Tuple[float, dict]:
        score = 0
        reasons = []
        
        if len(volumes) < 10 or len(closes) < 5:
            return 0, {'score': 0, 'reasons': []}
        
        # حجم مرتفع مع سعر مستقر
        current_vol = volumes[-1]
        avg_vol = np.mean(volumes[-10:])
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1
        
        recent_closes = closes[-5:]
        price_stability = (np.max(recent_closes) - np.min(recent_closes)) / np.mean(recent_closes) * 100
        
        if vol_ratio > 2.0 and price_stability < 1.0:
            score += 10
            reasons.append(f'حيتان واضحة (حجم {vol_ratio:.1f}x، استقرار {price_stability:.1f}%)')
        elif vol_ratio > 1.5 and price_stability < 1.5:
            score += 7
            reasons.append(f'تجميع حيتان (حجم {vol_ratio:.1f}x)')
        elif vol_ratio > 1.3 and price_stability < 2.0:
            score += 4
            reasons.append(f'نشاط حيتان محتمل')
        
        # سعر في اتجاه صاعد بطيء
        if len(closes) >= 10:
            trend = np.polyfit(range(10), closes[-10:], 1)[0]
            if trend > 0:
                score += 5
                reasons.append('اتجاه صاعد بطيء')
        
        return min(15, score), {'score': min(15, score), 'vol_ratio': round(vol_ratio, 1), 'reasons': reasons}
    
    # ============================================================
    # 5. التقاطع الذهبي (0-15)
    # ============================================================
    def _score_golden_cross(self, closes_1h: np.ndarray) -> Tuple[float, dict]:
        score = 0
        reasons = []
        
        if len(closes_1h) < 50:
            return 0, {'score': 0, 'reasons': []}
        
        ema20 = pd.Series(closes_1h).ewm(span=20, adjust=False).mean().values
        ema50 = pd.Series(closes_1h).ewm(span=50, adjust=False).mean().values
        
        current_20 = ema20[-1]
        current_50 = ema50[-1]
        prev_20 = ema20[-2] if len(ema20) > 1 else current_20
        prev_50 = ema50[-2] if len(ema50) > 1 else current_50
        
        # تقاطع ذهبي
        if prev_20 <= prev_50 and current_20 > current_50:
            score += 12
            reasons.append('🔥 تقاطع ذهبي حديث')
        elif current_20 > current_50:
            distance = (current_20 - current_50) / current_50 * 100
            if distance > 2:
                score += 10
                reasons.append(f'✅ تقاطع ذهبي مؤكد (+{distance:.1f}%)')
            else:
                score += 6
                reasons.append(f'📊 فوق EMA50')
        elif current_20 > current_50 * 0.98:
            score += 3
            reasons.append('🎯 قريب من التقاطع')
        
        return min(15, score), {'score': min(15, score), 'reasons': reasons}
    
    # ============================================================
    # 6. الدايفرجنس RSI (0-15)
    # ============================================================
    def _score_rsi_divergence(self, closes: np.ndarray) -> Tuple[float, dict]:
        score = 0
        reasons = []
        
        if len(closes) < 30:
            return 0, {'score': 0, 'reasons': []}
        
        # حساب RSI
        rsi = self._calc_rsi(closes, 14)
        
        # البحث عن قاعين
        mid = len(closes) // 2
        
        first_low_idx = np.argmin(closes[:mid])
        second_low_idx = np.argmin(closes[mid:]) + mid
        
        first_rsi_low = np.min(rsi[:mid])
        second_rsi_low = np.min(rsi[mid:])
        
        # دايفرجنس إيجابي (السعر ينخفض لكن RSI يرتفع)
        if closes[second_low_idx] < closes[first_low_idx] and second_rsi_low > first_rsi_low:
            score += 12
            reasons.append('📈 دايفرجنس إيجابي واضح')
        elif second_rsi_low > first_rsi_low * 1.05:
            score += 5
            reasons.append('دايفرجنس إيجابي محتمل')
        
        # RSI في منطقة القوة
        current_rsi = rsi[-1]
        if 50 <= current_rsi <= 65:
            score += 3
            reasons.append(f'RSI مثالي ({current_rsi:.0f})')
        
        return min(15, score), {'score': min(15, score), 'rsi': round(current_rsi, 0), 'reasons': reasons}
    
    # ============================================================
    # 7. حالة السوق (0-15)
    # ============================================================
    def _score_market_regime(self) -> Tuple[float, dict]:
        score = 0
        reasons = []
        
        if self.btc_ohlcv is None or len(self.btc_ohlcv) < 50:
            return 5, {'score': 5, 'reasons': ['بيانات BTC غير متوفرة']}
        
        btc_closes = self.btc_ohlcv[:, 4]
        
        # اتجاه BTC
        ema20 = pd.Series(btc_closes).ewm(span=20, adjust=False).mean().values
        ema50 = pd.Series(btc_closes).ewm(span=50, adjust=False).mean().values
        
        if ema20[-1] > ema50[-1] and btc_closes[-1] > ema20[-1]:
            score += 8
            reasons.append('🟢 BTC صاعد بقوة')
        elif ema20[-1] > ema50[-1]:
            score += 5
            reasons.append('🟢 BTC صاعد')
        elif btc_closes[-1] > ema50[-1]:
            score += 3
            reasons.append('🟡 BTC مستقر')
        
        # ADX (قوة الترند)
        adx = self._calc_adx(self.btc_ohlcv)
        if adx > 25:
            score += 5
            reasons.append(f'ADX قوي ({adx:.0f})')
        elif adx > 20:
            score += 3
        
        # تغير BTC
        change_24h = (btc_closes[-1] - btc_closes[-24]) / btc_closes[-24] * 100 if len(btc_closes) >= 24 else 0
        if -1 < change_24h < 3:
            score += 2
            reasons.append(f'BTC مستقر ({change_24h:+.1f}%)')
        
        return min(15, score), {'score': min(15, score), 'reasons': reasons}
    
    # ============================================================
    # دوال مساعدة
    # ============================================================
    def _calc_rsi(self, prices, period=14):
        if len(prices) < period + 1: return np.array([50] * len(prices))
        deltas = np.diff(prices)
        gain = np.where(deltas > 0, deltas, 0)
        loss = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.zeros_like(prices)
        avg_loss = np.zeros_like(prices)
        avg_gain[period] = np.mean(gain[:period])
        avg_loss[period] = np.mean(loss[:period])
        for i in range(period + 1, len(prices)):
            avg_gain[i] = (avg_gain[i-1] * (period-1) + gain[i-1]) / period
            avg_loss[i] = (avg_loss[i-1] * (period-1) + loss[i-1]) / period
        rs = avg_gain / (avg_loss + 1e-9)
        return 100 - (100 / (1 + rs))
    
    def _calc_adx(self, ohlcv, period=14):
        if len(ohlcv) < period + 1: return 20
        high, low, close = ohlcv[:, 2], ohlcv[:, 3], ohlcv[:, 4]
        tr1 = high[1:] - low[1:]
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        atr = np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr)
        up, down = high[1:] - high[:-1], low[:-1] - low[1:]
        plus_dm = np.where((up > down) & (up > 0), up, 0)
        minus_dm = np.where((down > up) & (down > 0), down, 0)
        plus_di = 100 * np.mean(plus_dm[-period:]) / atr if atr > 0 else 0
        minus_di = 100 * np.mean(minus_dm[-period:]) / atr if atr > 0 else 0
        return 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0

# =========================================================
# محاكي التداول
# =========================================================
class Simulator:
    def __init__(self):
        self.initial = SIMULATION_CAPITAL
        self.capital = SIMULATION_CAPITAL
        self.trades = []
        self.current_trade = None
        self.peak = SIMULATION_CAPITAL
        self.max_dd = 0.0

    def open(self, price: float, timestamp=None):
        if self.current_trade is not None: return
        size = min(self.capital * 0.1, 100)
        if size < 10: return
        self.capital -= size
        self.current_trade = {
            'entry': price, 'size': size, 'high': price,
            'entry_time': timestamp or datetime.now(),
            'trailing': 0, 'activated': False
        }

    def update(self, price: float, timestamp=None):
        equity = self.capital + (self.current_trade['size'] if self.current_trade else 0)
        if equity > self.peak: self.peak = equity
        dd = (self.peak - equity) / self.peak * 100 if self.peak > 0 else 0
        if dd > self.max_dd: self.max_dd = dd

        if self.current_trade is None: return
        t = self.current_trade
        if price > t['high']: t['high'] = price
        pnl = (price - t['entry']) / t['entry'] * 100

        if pnl >= 3.5:
            self._close(price, pnl, 'جني أرباح', timestamp)
            return
        if pnl <= -1.5:
            self._close(price, pnl, 'وقف خسارة', timestamp)
            return

        if pnl >= 1.5:
            if not t['activated']:
                t['activated'] = True
                t['trailing'] = t['high'] * 0.995
            else:
                new_stop = t['high'] * 0.995
                if new_stop > t['trailing']: t['trailing'] = new_stop
            if price <= t['trailing']:
                self._close(price, pnl, 'وقف متحرك', timestamp)

    def _close(self, price, pnl, reason, timestamp=None):
        if self.current_trade is None: return
        t = self.current_trade
        self.capital += t['size'] * (1 + pnl/100)
        exit_time = timestamp or datetime.now()
        duration = abs((exit_time - t['entry_time']).total_seconds() / 60) if t['entry_time'] else 0
        self.trades.append({
            'entry': t['entry'], 'exit': price, 'pnl': pnl,
            'reason': reason, 'size': t['size'], 'duration': duration
        })
        self.current_trade = None

    def get_stats(self):
        if not self.trades:
            return {'total': 0, 'wins': 0, 'win_rate': 0, 'pnl': 0, 'max_dd': 0, 'best': None, 'worst': None, 'avg_dur': 0}
        wins = [t for t in self.trades if t['pnl'] > 0]
        net = self.capital - self.initial
        return {
            'total': len(self.trades), 'wins': len(wins),
            'win_rate': len(wins)/len(self.trades)*100, 'pnl': net,
            'pnl_pct': net/self.initial*100, 'max_dd': self.max_dd,
            'best': max(self.trades, key=lambda x: x['pnl']),
            'worst': min(self.trades, key=lambda x: x['pnl']),
            'avg_dur': np.mean([t['duration'] for t in self.trades])
        }

# =========================================================
# 🚀 الدالة الرئيسية
# =========================================================
async def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║     🧮 نظام السكور المتكامل – 7 مؤشرات 🧮                ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    await send_telegram(f"🧮 *بدء نظام السكور المتكامل*\n{BOT_TAG}\n📅 {BACKTEST_DAYS} يوم | 💰 {SIMULATION_CAPITAL}$\n📊 7 مؤشرات")
    
    exchange = ccxt_async.binance({'enableRateLimit': True, 'rateLimit': 200, 'options': {'defaultType': 'spot'}})
    await exchange.fetch_ticker('BTC/USDT')
    print("✅ Binance متصل\n")
    
    # جلب بيانات BTC
    btc_ohlcv = await exchange.fetch_ohlcv('BTC/USDT', '1h', limit=100)
    btc_data = np.array(btc_ohlcv)
    
    scorer = ScoringEngine(btc_data)
    simulator = Simulator()
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=BACKTEST_DAYS)
    
    # جلب العملات
    tickers = await exchange.fetch_tickers()
    symbols = []
    for sym, t in tickers.items():
        if not sym.endswith('/USDT'): continue
        if is_excluded(sym): continue
        if (t.get('quoteVolume') or 0) < 100000: continue
        symbols.append(sym)
    symbols = symbols[:100]
    
    print(f"🪙 العملات: {len(symbols)}")
    
    scored_results = []
    
    for symbol in symbols:
        try:
            # جلب بيانات 5m و 1h
            since = exchange.parse8601(start_date.strftime('%Y-%m-%dT00:00:00Z'))
            ohlcv_5m = await exchange.fetch_ohlcv(symbol, '5m', since=since, limit=5000)
            ohlcv_1h = await exchange.fetch_ohlcv(symbol, '1h', since=since, limit=200)
            
            if len(ohlcv_5m) < 100 or len(ohlcv_1h) < 50: continue
            
            ticker = tickers.get(symbol, {})
            
            # حساب السكور
            score_result = scorer.calculate_score(np.array(ohlcv_5m[-100:]), np.array(ohlcv_1h[-50:]), ticker)
            
            if score_result['total_score'] >= MIN_SCORE:
                scored_results.append(score_result)
                print(f"  {symbol}: سكور {score_result['total_score']}/100 - {score_result['verdict']}")
                
                # محاكاة التداول
                data_5m = np.array(ohlcv_5m)
                for i in range(100, len(data_5m)):
                    price = data_5m[i][4]
                    ts = datetime.fromtimestamp(data_5m[i][0]/1000)
                    simulator.update(price, ts)
                    
                    if simulator.current_trade is None:
                        # إعادة تقييم السكور عند كل شمعة
                        local_data = data_5m[max(0,i-100):i+1]
                        if len(local_data) >= 50:
                            local_score = scorer.calculate_score(local_data, np.array(ohlcv_1h[-50:]), ticker)
                            if local_score['total_score'] >= MIN_SCORE:
                                simulator.open(price, ts)
                    
        except Exception as e: continue
    
    if simulator.current_trade:
        simulator._close(0, -2.0, 'نهاية', end_date)
    
    await exchange.close()
    
    s = simulator.get_stats()
    
    # ترتيب أعلى 10 عملات بالسكور
    scored_results.sort(key=lambda x: x['total_score'], reverse=True)
    
    print(f"""
╔══════════════════════════════════════════════════════════╗
║              📊 نتائج Backtesting                         ║
╠══════════════════════════════════════════════════════════╣
║  🔄 الصفقات: {s['total']}   | ✅ {s['win_rate']:.1f}%   | 💰 {s['pnl']:+.2f}$ ({s['pnl_pct']:+.2f}%)  ║
║  📉 أقصى انخفاض: {s['max_dd']:.1f}%   | ⏱️ متوسط: {s['avg_dur']:.0f}د                          ║
╚══════════════════════════════════════════════════════════╝

🏆 أعلى 10 عملات بالسكور:
""")
    
    for i, r in enumerate(scored_results[:10], 1):
        print(f"  {i}. {r.get('symbol', 'N/A')}: سكور {r['total_score']}/100 - {r['verdict']}")
    
    # إرسال تليجرام
    best = s['best']
    worst = s['worst']
    
    msg = f"""
🧮 *نتائج نظام السكور*
{BOT_TAG}
🔄 الصفقات: {s['total']}
✅ النجاح: {s['win_rate']:.1f}%
💰 الربح: {s['pnl']:+.2f}$ ({s['pnl_pct']:+.2f}%)
📉 أقصى انخفاض: {s['max_dd']:.1f}%
⏱️ متوسط المدة: {s['avg_dur']:.0f} دقيقة
🏆 أفضل: +{best['pnl']:.2f}% ({best['duration']:.0f}د)
💔 أسوأ: {worst['pnl']:.2f}% ({worst['duration']:.0f}د)

🏆 *أعلى 5 بالسكور:*
{chr(10).join(f'{i}. {r.get("symbol", "?")}: {r["total_score"]}/100' for i, r in enumerate(scored_results[:5], 1))}

🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
    """
    await send_telegram(msg)

if __name__ == "__main__":
    asyncio.run(main())
