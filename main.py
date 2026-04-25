#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام السكور المتكامل – Backtesting كامل مع تحميل CSV
First Station Multi-Indicator Scoring System - Complete Edition

المميزات:
✅ 7 مؤشرات متكاملة لحساب السكور
✅ Backtesting على 30 يوم
✅ تصدير النتائج إلى CSV مع رابط تحميل من تليجرام
✅ تقرير مجمع للصفقات الرابحة والخاسرة
✅ إشعارات تليجرام شاملة
✅ تحليل حسب السكور (عالٍ، متوسط، منخفض)
"""

import asyncio, pandas as pd, numpy as np, httpx, json, os, time, csv
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import ccxt.async_support as ccxt_async
from flask import Flask, send_file

# =========================================================
# إعدادات تليجرام
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
BOT_TAG = "#ScoringV2"

# =========================================================
# 🎯 إعدادات النظام
# =========================================================
SIMULATION_CAPITAL = 500.0
BACKTEST_DAYS = 30
MIN_SCORE = 50

TAKE_PROFIT = 3.5
STOP_LOSS = -1.5
TRAILING_ACTIVATION = 1.5
TRAILING_DISTANCE = 0.5
CAPITAL_PER_TRADE_RATIO = 0.1
MAX_CAPITAL_PER_TRADE = 100.0

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
# إعدادات Flask والملفات
# =========================================================
LOG_DIR = "paper_trading_logs"
os.makedirs(LOG_DIR, exist_ok=True)
TRADES_CSV_PATH = f"{LOG_DIR}/backtest_trades.csv"

app = Flask(__name__)

@app.route('/download/trades')
def download_trades():
    if os.path.exists(TRADES_CSV_PATH):
        return send_file(TRADES_CSV_PATH, as_attachment=True, download_name='backtest_results.csv')
    return "File not found", 404

@app.route('/health')
def health():
    return json.dumps({'status': 'healthy'})

def start_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# =========================================================
# دوال تليجرام
# =========================================================
async def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text.strip(), "parse_mode": "Markdown"})
            return resp.status_code == 200
    except:
        return False

# =========================================================
# 🧮 حاسبة السكور – 7 مؤشرات
# =========================================================
class ScoringEngine:
    def __init__(self, btc_ohlcv: np.ndarray = None):
        self.btc_ohlcv = btc_ohlcv
        
    def calculate_score(self, ohlcv_5m: np.ndarray, ohlcv_1h: np.ndarray, 
                        ticker: dict, symbol: str = "") -> dict:
        if len(ohlcv_5m) < 50 or len(ohlcv_1h) < 30:
            return {'total_score': 0, 'symbol': symbol}
        
        closes_5m = ohlcv_5m[:, 4]
        volumes_5m = ohlcv_5m[:, 5]
        closes_1h = ohlcv_1h[:, 4]
        
        current_price = ticker.get('last', closes_5m[-1])
        volume_24h = ticker.get('quoteVolume', 0) or 0
        
        total = 0
        
        # 1. انخناق البولنجر (0-15)
        recent = closes_5m[-20:]; middle = np.mean(recent); std = np.std(recent)
        upper, lower = middle + 2*std, middle - 2*std
        bandwidth = (upper - lower) / middle * 100
        position = (current_price - lower) / (upper - lower) if upper != lower else 0.5
        if bandwidth < 3.0: total += 12
        elif bandwidth < 5.0: total += 8
        elif bandwidth < 7.0: total += 4
        if position < 0.3: total += 8
        elif position < 0.5: total += 4
        
        # 2. السيولة (0-15)
        if volume_24h > 500000: total += 10
        elif volume_24h > 200000: total += 7
        elif volume_24h > 100000: total += 4
        avg_vol = np.mean(volumes_5m[-10:])
        if volumes_5m[-1] > avg_vol * 2.0: total += 5
        elif volumes_5m[-1] > avg_vol * 1.5: total += 3
        
        # 3. أوامر (0-15)
        bid, ask = ticker.get('bid',0) or 0, ticker.get('ask',0) or 0
        if bid > 0 and ask > 0 and (ask-bid)/bid*100 < 0.15: total += 8
        change = ticker.get('percentage',0) or 0
        if 1 < change < 8: total += 7
        
        # 4. حيتان (0-15)
        if len(volumes_5m) >= 10 and len(closes_5m) >= 5:
            vol_ratio = volumes_5m[-1] / np.mean(volumes_5m[-10:]) if np.mean(volumes_5m[-10:]) > 0 else 1
            stability = (np.max(closes_5m[-5:]) - np.min(closes_5m[-5:])) / np.mean(closes_5m[-5:]) * 100
            if vol_ratio > 2.0 and stability < 1.0: total += 12
            elif vol_ratio > 1.5 and stability < 1.5: total += 8
        
        # 5. تقاطع ذهبي (0-15)
        if len(closes_1h) >= 50:
            e20 = pd.Series(closes_1h).ewm(span=20, adjust=False).mean().values
            e50 = pd.Series(closes_1h).ewm(span=50, adjust=False).mean().values
            if e20[-2] <= e50[-2] and e20[-1] > e50[-1]: total += 12
            elif e20[-1] > e50[-1]: total += 6
        
        # 6. RSI دايفرجنس (0-15)
        if len(closes_5m) >= 30:
            rsi = self._calc_rsi(closes_5m, 14)
            mid = len(closes_5m) // 2
            if np.min(closes_5m[mid:]) < np.min(closes_5m[:mid]) and np.min(rsi[mid:]) > np.min(rsi[:mid]):
                total += 10
            if 50 <= rsi[-1] <= 65: total += 5
        
        # 7. حالة السوق (0-15)
        if self.btc_ohlcv is not None and len(self.btc_ohlcv) >= 50:
            btc_closes = self.btc_ohlcv[:, 4]
            e20 = pd.Series(btc_closes).ewm(span=20, adjust=False).mean().values
            e50 = pd.Series(btc_closes).ewm(span=50, adjust=False).mean().values
            if e20[-1] > e50[-1]: total += 10
            adx = self._calc_adx(self.btc_ohlcv)
            if adx > 25: total += 5
        
        final_score = min(100, round(total / 1.05))
        
        return {
            'symbol': symbol, 'total_score': final_score,
            'current_price': current_price, 'volume_24h': volume_24h
        }
    
    def _calc_rsi(self, prices, period=14):
        if len(prices) < period+1: return np.array([50]*len(prices))
        d = np.diff(prices); g = np.where(d>0,d,0); l = np.where(d<0,-d,0)
        ag, al = np.zeros_like(prices), np.zeros_like(prices)
        ag[period], al[period] = np.mean(g[:period]), np.mean(l[:period])
        for i in range(period+1, len(prices)):
            ag[i] = (ag[i-1]*(period-1) + g[i-1]) / period
            al[i] = (al[i-1]*(period-1) + l[i-1]) / period
        return 100 - (100 / (1 + ag/(al+1e-9)))
    
    def _calc_adx(self, ohlcv, period=14):
        if len(ohlcv) < period+1: return 20
        h, l, c = ohlcv[:,2], ohlcv[:,3], ohlcv[:,4]
        tr = np.maximum(np.maximum(h[1:]-l[1:], np.abs(h[1:]-c[:-1])), np.abs(l[1:]-c[:-1]))
        atr = np.mean(tr[-period:]) if len(tr)>=period else np.mean(tr)
        up, down = h[1:]-h[:-1], l[:-1]-l[1:]
        pdm = np.where((up>down)&(up>0), up, 0); ndm = np.where((down>up)&(down>0), down, 0)
        pdi = 100*np.mean(pdm[-period:])/atr if atr>0 else 0
        ndi = 100*np.mean(ndm[-period:])/atr if atr>0 else 0
        return 100*np.abs(pdi-ndi)/(pdi+ndi) if (pdi+ndi)>0 else 0

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

    def open(self, price: float, score: int = 0, symbol: str = "", timestamp=None):
        if self.current_trade is not None: return
        size = min(self.capital * CAPITAL_PER_TRADE_RATIO, MAX_CAPITAL_PER_TRADE)
        if size < 10: return
        self.capital -= size
        self.current_trade = {
            'entry': price, 'size': size, 'high': price, 'score': score,
            'symbol': symbol,
            'entry_time': timestamp or datetime.now(),
            'trailing': 0, 'activated': False
        }

    def update(self, price: float, timestamp=None):
        equity = self.capital
        if self.current_trade:
            t = self.current_trade
            pnl = (price - t['entry']) / t['entry']
            equity += t['size'] * (1 + pnl)
        
        if equity > self.peak: self.peak = equity
        if self.peak > 0:
            dd = (self.peak - equity) / self.peak * 100
            if dd > self.max_dd: self.max_dd = dd

        if self.current_trade is None: return
        t = self.current_trade
        if price > t['high']: t['high'] = price
        pnl_pct = (price - t['entry']) / t['entry'] * 100

        if pnl_pct >= TAKE_PROFIT:
            self._close(price, pnl_pct, 'جني أرباح', timestamp)
            return
        if pnl_pct <= STOP_LOSS:
            self._close(price, pnl_pct, 'وقف خسارة', timestamp)
            return
        if pnl_pct >= TRAILING_ACTIVATION:
            if not t['activated']:
                t['activated'] = True
                t['trailing'] = t['high'] * (1 - TRAILING_DISTANCE/100)
            else:
                new_stop = t['high'] * (1 - TRAILING_DISTANCE/100)
                if new_stop > t['trailing']: t['trailing'] = new_stop
            if price <= t['trailing']:
                self._close(price, pnl_pct, 'وقف متحرك', timestamp)

    def _close(self, price, pnl_pct, reason, timestamp=None):
        if self.current_trade is None: return
        t = self.current_trade
        pnl_usd = t['size'] * (pnl_pct / 100)
        self.capital += t['size'] + pnl_usd
        
        exit_time = timestamp or datetime.now()
        duration = abs((exit_time - t['entry_time']).total_seconds() / 60) if t['entry_time'] else 0
        
        self.trades.append({
            'symbol': t.get('symbol', '?'),
            'entry': t['entry'], 'exit': price,
            'pnl_pct': pnl_pct, 'pnl_usd': pnl_usd,
            'reason': reason, 'size': t['size'],
            'duration': duration, 'score': t['score'],
            'entry_time': t['entry_time'],
            'exit_time': exit_time
        })
        self.current_trade = None

    def get_stats(self):
        if not self.trades:
            return {'total': 0, 'wins': 0, 'win_rate': 0, 'pnl': 0, 'max_dd': 0, 
                    'best': None, 'worst': None, 'avg_dur': 0}
        
        wins = [t for t in self.trades if t['pnl_pct'] > 0]
        net = self.capital - self.initial
        
        return {
            'total': len(self.trades),
            'wins': len(wins),
            'win_rate': len(wins)/len(self.trades)*100,
            'pnl': net,
            'pnl_pct': net/self.initial*100,
            'max_dd': self.max_dd,
            'best': max(self.trades, key=lambda x: x['pnl_pct']),
            'worst': min(self.trades, key=lambda x: x['pnl_pct']),
            'avg_dur': np.mean([t['duration'] for t in self.trades]) if self.trades else 0
        }

# =========================================================
# 🚀 الدالة الرئيسية
# =========================================================
async def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║     🧮 نظام السكور المتكامل – Backtesting كامل 🧮        ║
║     7 مؤشرات | 30 يوم | 500$ | CSV + تليجرام             ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    # بدء Flask في الخلفية
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    await send_telegram(f"🧮 *بدء Backtesting*\n{BOT_TAG}\n📅 {BACKTEST_DAYS} يوم | 💰 {SIMULATION_CAPITAL}$ | 🎯 حد السكور: {MIN_SCORE}")
    
    exchange = ccxt_async.binance({'enableRateLimit': True, 'rateLimit': 200, 'options': {'defaultType': 'spot'}})
    await exchange.fetch_ticker('BTC/USDT')
    print("✅ Binance متصل\n")
    
    btc_ohlcv = await exchange.fetch_ohlcv('BTC/USDT', '1h', limit=100)
    btc_data = np.array(btc_ohlcv)
    scorer = ScoringEngine(btc_data)
    simulator = Simulator()
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=BACKTEST_DAYS)
    
    tickers = await exchange.fetch_tickers()
    symbols = []
    for sym, t in tickers.items():
        if not sym.endswith('/USDT'): continue
        if is_excluded(sym): continue
        if (t.get('quoteVolume') or 0) < 100000: continue
        symbols.append(sym)
    symbols = symbols[:150]
    
    print(f"🪙 العملات: {len(symbols)}")
    
    all_scores = []
    processed = 0
    
    for symbol in symbols:
        try:
            since = exchange.parse8601(start_date.strftime('%Y-%m-%dT00:00:00Z'))
            ohlcv_5m = await exchange.fetch_ohlcv(symbol, '5m', since=since, limit=5000)
            ohlcv_1h = await exchange.fetch_ohlcv(symbol, '1h', since=since, limit=200)
            
            if len(ohlcv_5m) < 100 or len(ohlcv_1h) < 50: continue
            processed += 1
            
            ticker = tickers.get(symbol, {})
            data_5m = np.array(ohlcv_5m)
            
            for i in range(100, len(data_5m)):
                price = data_5m[i][4]
                ts = datetime.fromtimestamp(data_5m[i][0]/1000)
                
                simulator.update(price, ts)
                
                if simulator.current_trade is None:
                    local_5m = data_5m[max(0,i-100):i+1]
                    local_1h = np.array(ohlcv_1h[-50:])
                    
                    if len(local_5m) >= 50:
                        result = scorer.calculate_score(local_5m, local_1h, ticker, symbol)
                        
                        if result['total_score'] >= MIN_SCORE:
                            simulator.open(price, result['total_score'], symbol, ts)
                            all_scores.append(result)
            
            if processed % 20 == 0:
                print(f"   📊 تقدم: {processed}/{len(symbols)}")
                
        except Exception as e:
            continue
    
    if simulator.current_trade:
        simulator._close(0, -2.0, 'نهاية', end_date)
    
    await exchange.close()
    
    s = simulator.get_stats()
    all_scores.sort(key=lambda x: x['total_score'], reverse=True)
    
    # =========================================================
    # 📁 حفظ النتائج في CSV
    # =========================================================
    with open(TRADES_CSV_PATH, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['symbol', 'entry_time', 'entry_price', 'exit_time', 'exit_price', 
                     'pnl_pct', 'pnl_usd', 'duration_min', 'score', 'reason']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for t in simulator.trades:
            writer.writerow({
                'symbol': t.get('symbol', '?'),
                'entry_time': t.get('entry_time', '').strftime('%Y-%m-%d %H:%M:%S') if t.get('entry_time') else '',
                'entry_price': f"{t['entry']:.8f}",
                'exit_time': t.get('exit_time', '').strftime('%Y-%m-%d %H:%M:%S') if t.get('exit_time') else '',
                'exit_price': f"{t['exit']:.8f}",
                'pnl_pct': f"{t['pnl_pct']:+.2f}",
                'pnl_usd': f"{t['pnl_usd']:+.2f}",
                'duration_min': f"{t['duration']:.0f}",
                'score': t.get('score', 0),
                'reason': t.get('reason', '')
            })
    print(f"📁 تم حفظ النتائج في: {TRADES_CSV_PATH}")
    
    # =========================================================
    # 📊 عرض النتائج
    # =========================================================
    print(f"""
╔══════════════════════════════════════════════════════════╗
║              📊 نتائج Backtesting                         ║
╠══════════════════════════════════════════════════════════╣
║  🔄 الصفقات: {s['total']}   | ✅ {s['win_rate']:.1f}%   | 💰 {s['pnl']:+.2f}$ ({s['pnl_pct']:+.2f}%)  ║
║  📉 أقصى انخفاض: {s['max_dd']:.1f}%   | ⏱️ متوسط: {s['avg_dur']:.0f}د                          ║
╚══════════════════════════════════════════════════════════╝

🏆 أفضل 5 عملات بالسكور:
""")
    
    for i, r in enumerate(all_scores[:5], 1):
        print(f"  {i}. {r.get('symbol','?'):12s} | سكور: {r['total_score']:3d}/100 | ${r.get('volume_24h',0):,.0f}")
    
    # تحليل حسب السكور
    if s['total'] > 0:
        high = [t for t in simulator.trades if t.get('score', 0) >= 70]
        mid = [t for t in simulator.trades if 55 <= t.get('score', 0) < 70]
        low = [t for t in simulator.trades if t.get('score', 0) < 55]
        
        print(f"\n📊 تحليل حسب السكور:")
        if high:
            wr = len([t for t in high if t['pnl_pct']>0]) / len(high) * 100
            print(f"  🟢 سكور ≥ 70: {len(high)} صفقة | نجاح {wr:.0f}%")
        if mid:
            wr = len([t for t in mid if t['pnl_pct']>0]) / len(mid) * 100
            print(f"  🟡 سكور 55-69: {len(mid)} صفقة | نجاح {wr:.0f}%")
        if low:
            wr = len([t for t in low if t['pnl_pct']>0]) / len(low) * 100
            print(f"  🔴 سكور < 55: {len(low)} صفقة | نجاح {wr:.0f}%")
    
    # =========================================================
    # 📱 إرسال التقارير إلى تليجرام
    # =========================================================
    
    # 1. رابط تحميل CSV
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8080")
    csv_link = f"{base_url}/download/trades"
    
    await send_telegram(f"""
📊 *نتائج Backtesting*
{BOT_TAG}

🔄 الصفقات: {s['total']}
✅ النجاح: {s['win_rate']:.1f}%
💰 الربح: {s['pnl']:+.2f}$ ({s['pnl_pct']:+.2f}%)
📉 أقصى انخفاض: {s['max_dd']:.1f}%
⏱️ متوسط المدة: {s['avg_dur']:.0f}د

📥 *تحميل النتائج:*
[اضغط هنا لتحميل ملف CSV]({csv_link})

🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
    """)
    
    # 2. تقرير الصفقات الرابحة
    winning_trades = [t for t in simulator.trades if t['pnl_pct'] > 0]
    winning_trades.sort(key=lambda x: x['pnl_pct'], reverse=True)
    
    if winning_trades:
        win_msg = f"💰 *الصفقات الرابحة ({len(winning_trades)})*\n{BOT_TAG}\n\n"
        for i, t in enumerate(winning_trades[:15], 1):
            entry_time = t.get('entry_time', '').strftime('%m/%d %H:%M') if t.get('entry_time') else '?'
            win_msg += f"{i}. {t.get('symbol','?')} | +{t['pnl_pct']:.2f}% | {entry_time} | ⏱️{t['duration']:.0f}د | سكور:{t.get('score','?')}\n"
        await send_telegram(win_msg)
    
    # 3. تقرير الصفقات الخاسرة
    losing_trades = [t for t in simulator.trades if t['pnl_pct'] <= 0]
    losing_trades.sort(key=lambda x: x['pnl_pct'])
    
    if losing_trades:
        loss_msg = f"📉 *الصفقات الخاسرة ({len(losing_trades)})*\n{BOT_TAG}\n\n"
        for i, t in enumerate(losing_trades[:15], 1):
            entry_time = t.get('entry_time', '').strftime('%m/%d %H:%M') if t.get('entry_time') else '?'
            loss_msg += f"{i}. {t.get('symbol','?')} | {t['pnl_pct']:.2f}% | {entry_time} | ⏱️{t['duration']:.0f}د | سكور:{t.get('score','?')}\n"
        await send_telegram(loss_msg)
    
    # 4. تحليل السكور
    if s['total'] > 0:
        score_msg = f"📊 *تحليل حسب السكور*\n{BOT_TAG}\n\n"
        if high:
            wr = len([t for t in high if t['pnl_pct']>0]) / len(high) * 100
            score_msg += f"🟢 سكور ≥ 70: {len(high)} صفقة | نجاح {wr:.0f}%\n"
        if mid:
            wr = len([t for t in mid if t['pnl_pct']>0]) / len(mid) * 100
            score_msg += f"🟡 سكور 55-69: {len(mid)} صفقة | نجاح {wr:.0f}%\n"
        if low:
            wr = len([t for t in low if t['pnl_pct']>0]) / len(low) * 100
            score_msg += f"🔴 سكور < 55: {len(low)} صفقة | نجاح {wr:.0f}%\n"
        await send_telegram(score_msg)

if __name__ == "__main__":
    asyncio.run(main())
