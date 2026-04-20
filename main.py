"""
نظام التداول الورقي المتكامل - الإصدار النهائي [PROJET_100]
============================================================================
الميزات الكاملة:
- مسح ذكي متعدد المستويات (Gold/Silver/Bronze)
- نظام ثقة تراكمي (Confidence Scoring)
- وقف خسارة متحرك مع تأمين التعادل
- 4 سيناريوهات للمراقبة والمقارنة
- إشعارات تيليجرام مع علامة [PROJET_100]
- تقارير CSV مع بادئة projet_100_
- أمر /performance لعرض أداء آخر 24 ساعة
- فلتر العملات الوهمية (High Spread Detection)
- إيقاف تلقائي في عطلة نهاية الأسبوع
- نسخ احتياطي تلقائي للكود والإعدادات
"""

import asyncio
import ccxt.async_support as ccxt_async
import ccxt
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import json
import os
import csv
import shutil
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================================================
# ⭐ علامة المشروع - تضاف إلى كل شيء
# =========================================================
PROJECT_TAG = "[PROJET_100]"

# =========================================================
# إعدادات تيليجرام
# =========================================================
TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
PUBLIC_CHAT_ID = "-1003692815602"
PRIVATE_USER_ID = "5067771509"

telegram_app = None

# =========================================================
# الإعدادات المثلى
# =========================================================
INITIAL_CAPITAL = 1000
MAX_POSITIONS = 8
MIN_APPEARANCES = 2
TOP_CANDIDATES_COUNT = 5

# إعدادات المسح
GOLD_SCAN_INTERVAL = 300
SILVER_SCAN_INTERVAL = 0    # معطل - نركز على Gold فقط
BRONZE_SCAN_INTERVAL = 0    # معطل
GOLD_COUNT = 60

PRICE_UPDATE_INTERVAL = 60
MAX_AGE_HOURS = 12

# إعدادات الثقة
MIN_CONFIDENCE_TO_TRADE = 40
CONFIDENCE_HIGH = 70
CONFIDENCE_MEDIUM = 50
MIN_FILTER_SCORE = 25

# إعدادات وقف الخسارة والهدف
ATR_MULTIPLIER = 2.0
TAKE_PROFIT_TARGET = 10
BREAKEVEN_ACTIVATION = 0.015

# عتبات تقييم النتائج
FAIL_THRESHOLD = -0.025
SUCCESS_THRESHOLD = 0.08

# إعدادات Rate Limit
MAX_REQUESTS_PER_MINUTE = 100

# ⭐ إيقاف التداول في عطلة نهاية الأسبوع
WEEKEND_PAUSE = True

# ⭐ السيناريوهات الأربعة للمراقبة
SCENARIOS = {
    1: {'name': 'SL -2% / TP 4%', 'sl_pct': -0.02, 'tp_pct': 0.04, 'trailing': False},
    2: {'name': 'SL -3% / TP 6%', 'sl_pct': -0.03, 'tp_pct': 0.06, 'trailing': False},
    3: {'name': 'SL -2% / TP 5% + Trailing', 'sl_pct': -0.02, 'tp_pct': 0.05, 'trailing': True},
    4: {'name': 'SL/TP ديناميكي (ATR)', 'sl_pct': None, 'tp_pct': None, 'trailing': True, 'dynamic': True}
}

# متغيرات عامة
all_symbols = []
gold_symbols = []
symbol_classification_time = 0
trader_instance = None
is_paused = False
auto_paused_reason = None

# أسماء الملفات مع بادئة المشروع
TRADES_CSV = "projet_100_closed_trades.csv"
REPORT_CSV = "projet_100_hourly_report.csv"
CANDIDATES_CSV = "projet_100_scan_candidates.csv"
SCENARIOS_CSV = "projet_100_scenario_results.csv"
STATE_FILE = "projet_100_trader_state.json"

# =========================================================
# دوال تيليجرام (مع علامة المشروع)
# =========================================================
async def send_telegram_message(text: str):
    global telegram_app
    if not telegram_app or not TELEGRAM_TOKEN:
        return
    try:
        # ⭐ إضافة علامة المشروع
        tagged_text = f"{PROJECT_TAG}\n{text}"
        await telegram_app.bot.send_message(chat_id=PRIVATE_USER_ID, text=tagged_text)
        await telegram_app.bot.send_message(chat_id=PUBLIC_CHAT_ID, text=tagged_text)
    except Exception as e:
        print(f"خطأ تيليجرام: {e}")

async def send_csv_file(file_path: str, caption: str = ""):
    global telegram_app
    if not telegram_app or not os.path.exists(file_path):
        return
    
    # ⭐ إضافة علامة المشروع للتعليق
    tagged_caption = f"{PROJECT_TAG} {caption}"
    
    for chat_id in [PUBLIC_CHAT_ID, PRIVATE_USER_ID]:
        try:
            with open(file_path, 'rb') as f:
                await telegram_app.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=os.path.basename(file_path),
                    caption=tagged_caption
                )
        except Exception as e:
            print(f"خطأ في إرسال ملف: {e}")

# =========================================================
# دوال مساعدة
# =========================================================
def is_weekend():
    """التحقق مما إذا كان اليوم سبت أو أحد"""
    today = datetime.now().weekday()
    return today in [5, 6]

def is_honeypot_or_high_concentration(exchange, symbol):
    """فحص ما إذا كانت العملة مشبوهة (سبريد عالي)"""
    try:
        ticker = exchange.fetch_ticker(symbol)
        bid = ticker.get('bid', 0)
        ask = ticker.get('ask', 0)
        
        if ask > 0:
            spread = (ask - bid) / ask
            if spread > 0.02:  # سبريد > 2% = خطير
                return True
        return False
    except:
        return False

def backup_code():
    """نسخ احتياطي للكود والإعدادات"""
    backup_dir = "projet_100_backups"
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # نسخ الملف الرئيسي
    if os.path.exists(__file__):
        shutil.copy(__file__, f"{backup_dir}/main_{timestamp}.py")
    
    # نسخ الإعدادات
    settings = {
        'MIN_CONFIDENCE': MIN_CONFIDENCE_TO_TRADE,
        'MAX_POSITIONS': MAX_POSITIONS,
        'GOLD_COUNT': GOLD_COUNT,
        'ATR_MULTIPLIER': ATR_MULTIPLIER,
        'TAKE_PROFIT_TARGET': TAKE_PROFIT_TARGET,
        'timestamp': timestamp
    }
    with open(f"{backup_dir}/settings_{timestamp}.json", 'w') as f:
        json.dump(settings, f, indent=2)
    
    print(f"✅ {PROJECT_TAG} تم عمل نسخة احتياطية في {backup_dir}")

# =========================================================
# المؤشرات الفنية
# =========================================================
def manual_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def manual_rsi(close, length=14):
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def manual_macd(close):
    ema12 = manual_ema(close, 12)
    ema26 = manual_ema(close, 26)
    macd = ema12 - ema26
    signal = manual_ema(macd, 9)
    return macd, signal

def manual_atr(high, low, close, length=14):
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()

def manual_donchian(high, low, length=20):
    upper = high.rolling(window=length).max()
    return upper

# =========================================================
# حساب السكور
# =========================================================
def calculate_filter_score(df):
    if df.empty or len(df) < 20:
        return 0
    
    last = df.iloc[-1]
    score = 0
    
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    if pd.notna(avg_vol) and avg_vol > 0:
        vol_ratio = last['volume'] / avg_vol
        if vol_ratio > 2.0: score += 15
        if vol_ratio > 3.0: score += 15
    
    rsi = manual_rsi(df['close']).iloc[-1]
    if pd.notna(rsi):
        if 50 < rsi < 75: score += 20
        elif rsi > 75: score += 10
    
    macd, signal = manual_macd(df['close'])
    if pd.notna(macd.iloc[-1]) and pd.notna(signal.iloc[-1]):
        if macd.iloc[-1] > signal.iloc[-1]:
            score += 15
    
    upper = manual_donchian(df['high'], df['low']).iloc[-1]
    if pd.notna(upper) and last['close'] > upper:
        score += 20
    
    return score

def calculate_alpha(df):
    if df.empty or len(df) < 20:
        return 0
    last = df.iloc[-1]
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    vol_ratio = last['volume'] / avg_vol if avg_vol > 0 else 1.0
    rsi = manual_rsi(df['close']).iloc[-1]
    rsi_score = (rsi - 30) / 50 if pd.notna(rsi) else 0.5
    alpha = (min(vol_ratio / 3, 1.0) * 0.5) + (max(0, min(rsi_score, 1.0)) * 0.5)
    return round(alpha * 3, 3)

def check_explosion_criteria(candidate):
    score = 0
    if candidate.get('filter_score', 0) >= 55:
        score += 1
    if candidate.get('alpha', 0) >= 1.3:
        score += 1
    if candidate.get('target_pct', 0) >= 12:
        score += 1
    if candidate.get('strategy_points', 0) >= 4:
        score += 1
    return score >= 4, score

def calculate_target_percentage(df):
    if df.empty or len(df) < 20:
        return 8.0
    last = df.iloc[-1]
    highs = df['high'].rolling(50).max().dropna().unique()
    highs_sorted = sorted(highs, reverse=True)
    for h in highs_sorted:
        if h > last['close'] * 1.02:
            return ((h - last['close']) / last['close']) * 100
    return 8.0

def calculate_confidence_score(candidate, market_context):
    confidence = 0
    
    filter_score = candidate.get('filter_score', 0)
    if filter_score >= 70: confidence += 30
    elif filter_score >= 50: confidence += 22
    elif filter_score >= 35: confidence += 15
    elif filter_score >= 25: confidence += 8
    
    if candidate.get('volume_confirm') and candidate.get('trend_confirm'):
        confidence += 25
    elif candidate.get('volume_confirm'):
        confidence += 15
    
    strategy_points = candidate.get('strategy_points', 0)
    if strategy_points >= 6: confidence += 20
    elif strategy_points >= 4: confidence += 14
    elif strategy_points >= 2: confidence += 8
    
    regime = market_context.get('regime', 'CALM')
    if regime == 'HOT': confidence += 15
    elif regime == 'CALM': confidence += 10
    else: confidence += 3
    
    priority = candidate.get('priority', 0)
    confidence += min(priority * 2, 10)
    
    alpha = candidate.get('alpha', 0)
    if alpha >= 2.0: confidence += 10
    elif alpha >= 1.5: confidence += 6
    elif alpha >= 1.0: confidence += 3
    
    return min(confidence, 100)

# =========================================================
# نظام تتبع السيناريوهات
# =========================================================
class ScenarioTracker:
    def __init__(self):
        self.scenarios_csv = SCENARIOS_CSV
        self.active_trades = []
        self._init_csv()
    
    def _init_csv(self):
        if not os.path.exists(self.scenarios_csv):
            with open(self.scenarios_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Project', 'Entry Time', 'Symbol', 'Entry Price', 'Scenario', 'SL %', 'TP %',
                    'Exit Time', 'Exit Price', 'Result', 'PNL %', 'Max Favorable %', 'Max Adverse %'
                ])
    
    def add_trade(self, symbol, entry_price, entry_time, df=None):
        for scenario_id, config in SCENARIOS.items():
            trade = {
                'symbol': symbol,
                'entry_price': entry_price,
                'entry_time': entry_time,
                'scenario_id': scenario_id,
                'scenario_name': config['name'],
                'sl_pct': config['sl_pct'],
                'tp_pct': config['tp_pct'],
                'trailing': config['trailing'],
                'dynamic': config.get('dynamic', False),
                'highest_price': entry_price,
                'lowest_price': entry_price,
                'df': df,
                'atr_value': None
            }
            
            if config.get('dynamic') and df is not None and len(df) > 14:
                atr = manual_atr(df['high'], df['low'], df['close']).iloc[-1]
                trade['atr_value'] = atr
                trade['sl_price'] = entry_price - (ATR_MULTIPLIER * atr)
                trade['tp_price'] = entry_price * (1 + TAKE_PROFIT_TARGET / 100)
            else:
                trade['sl_price'] = entry_price * (1 + config['sl_pct']) if config['sl_pct'] else None
                trade['tp_price'] = entry_price * (1 + config['tp_pct']) if config['tp_pct'] else None
            
            self.active_trades.append(trade)
    
    def update_prices(self, prices):
        now = datetime.now()
        to_close = []
        
        for i, trade in enumerate(self.active_trades):
            symbol = trade['symbol']
            if symbol not in prices:
                continue
            
            price = prices[symbol]
            
            if price > trade['highest_price']:
                trade['highest_price'] = price
            if price < trade['lowest_price']:
                trade['lowest_price'] = price
            
            if trade.get('trailing') and trade.get('dynamic'):
                atr = trade.get('atr_value', price * 0.03)
                new_sl = trade['highest_price'] - (ATR_MULTIPLIER * atr)
                if new_sl > trade.get('sl_price', 0):
                    trade['sl_price'] = new_sl
            elif trade.get('trailing') and trade['highest_price'] > trade['entry_price']:
                new_sl = trade['entry_price'] * (1 + BREAKEVEN_ACTIVATION)
                if new_sl > trade.get('sl_price', 0):
                    trade['sl_price'] = new_sl
            
            exit_reason = None
            
            if trade['sl_price'] and price <= trade['sl_price']:
                exit_reason = "STOP_LOSS"
            elif trade['tp_price'] and price >= trade['tp_price']:
                exit_reason = "TAKE_PROFIT"
            
            age = (now - trade['entry_time']).total_seconds() / 3600
            if age >= MAX_AGE_HOURS:
                exit_reason = "EXPIRED"
            
            if exit_reason:
                to_close.append((i, price, exit_reason))
        
        for i, price, reason in sorted(to_close, key=lambda x: x[0], reverse=True):
            self.close_trade(i, price, reason)
    
    def close_trade(self, index, exit_price, reason):
        trade = self.active_trades.pop(index)
        pnl_pct = ((exit_price - trade['entry_price']) / trade['entry_price']) * 100
        
        result = "WIN" if pnl_pct > 0 else "LOSS"
        if reason == "EXPIRED":
            result = "EXPIRED"
        
        max_favorable = ((trade['highest_price'] - trade['entry_price']) / trade['entry_price']) * 100
        max_adverse = ((trade['lowest_price'] - trade['entry_price']) / trade['entry_price']) * 100
        
        with open(self.scenarios_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                PROJECT_TAG,
                trade['entry_time'].isoformat(),
                trade['symbol'],
                f"{trade['entry_price']:.4f}",
                trade['scenario_name'],
                f"{trade['sl_pct']*100:.1f}%" if trade['sl_pct'] else "ATR",
                f"{trade['tp_pct']*100:.1f}%" if trade['tp_pct'] else "ATR",
                datetime.now().isoformat(),
                f"{exit_price:.4f}",
                result,
                f"{pnl_pct:.2f}%",
                f"{max_favorable:.2f}%",
                f"{max_adverse:.2f}%"
            ])
    
    def get_statistics(self):
        if not os.path.exists(self.scenarios_csv):
            return None
        
        df = pd.read_csv(self.scenarios_csv)
        stats = {}
        
        for scenario in df['Scenario'].unique():
            scenario_df = df[df['Scenario'] == scenario]
            total = len(scenario_df)
            wins = len(scenario_df[scenario_df['Result'] == 'WIN'])
            losses = len(scenario_df[scenario_df['Result'] == 'LOSS'])
            win_rate = (wins / total * 100) if total > 0 else 0
            
            avg_win = scenario_df[scenario_df['Result'] == 'WIN']['PNL %'].mean() if wins > 0 else 0
            avg_loss = abs(scenario_df[scenario_df['Result'] == 'LOSS']['PNL %'].mean()) if losses > 0 else 0
            
            stats[scenario] = {
                'total': total,
                'wins': wins,
                'losses': losses,
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': (wins * avg_win) / (losses * avg_loss) if losses > 0 and avg_loss > 0 else 0
            }
        
        return stats

# =========================================================
# نظام التداول الورقي
# =========================================================
class PaperTrader:
    def __init__(self, initial_capital=1000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = []
        self.closed_trades = []
        self.data_file = STATE_FILE
        self.trades_csv = TRADES_CSV
        self.report_csv = REPORT_CSV
        self.load_state()
        self._init_csv_files()
    
    def _init_csv_files(self):
        if not os.path.exists(self.trades_csv):
            with open(self.trades_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Project', 'Symbol', 'Entry Price', 'Exit Price', 'Amount', 'Entry Time', 'Exit Time',
                    'PNL ($)', 'PNL (%)', 'Exit Reason', 'Alpha', 'Target %', 'ETA',
                    'Signal Type', 'Confidence', 'Entry Reason'
                ])
        if not os.path.exists(self.report_csv):
            with open(self.report_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Project', 'Timestamp', 'Cash', 'Total PNL', 'Return %', 'Total Trades',
                    'Wins', 'Losses', 'Win Rate %', 'Open Positions'
                ])
    
    def load_state(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.cash = data.get('cash', self.initial_capital)
                    self.closed_trades = data.get('closed_trades', [])
                    print(f"{PROJECT_TAG} 📂 تم تحميل الحالة: الرصيد = {self.cash:.2f}$")
            except:
                print(f"{PROJECT_TAG} ⚠️ بدء محفظة جديدة")
    
    def save_state(self):
        with open(self.data_file, 'w') as f:
            json.dump({'cash': self.cash, 'closed_trades': self.closed_trades, 'positions': self.positions}, f)
    
    def _append_trade_to_csv(self, trade):
        with open(self.trades_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                PROJECT_TAG,
                trade['symbol'],
                f"{trade['entry_price']:.4f}",
                f"{trade['exit_price']:.4f}",
                f"{trade['amount']:.4f}",
                trade['entry_time'],
                trade['exit_time'],
                f"{trade['pnl']:.2f}",
                f"{trade['pnl_pct']:.2f}",
                trade['exit_reason'],
                f"{trade.get('alpha', 0):.3f}",
                f"{trade.get('target_pct', 0):.2f}",
                trade.get('eta_str', 'N/A'),
                trade.get('signal_type', 'unknown'),
                trade.get('confidence', 0),
                trade.get('entry_reason', '')
            ])
    
    def open_position(self, signal, exchange, signal_type='alpha', entry_reason=''):
        symbol = signal['symbol']
        entry_price = signal['entry_price']
        target_pct = signal.get('target_pct', TAKE_PROFIT_TARGET)
        alpha = signal.get('alpha', 0)
        df = signal.get('df')
        confidence = signal.get('confidence', 50)
        
        # ⭐ فلتر العملات الوهمية
        if is_honeypot_or_high_concentration(exchange, symbol):
            print(f"{PROJECT_TAG} ⚠️ {symbol} عملة مشبوهة (سبريد عالي)، تم تخطيها")
            return False
        
        if df is not None and len(df) > 14:
            atr = manual_atr(df['high'], df['low'], df['close']).iloc[-1]
        else:
            atr = entry_price * 0.03
        
        stop_loss = entry_price - (ATR_MULTIPLIER * atr)
        take_profit = entry_price * (1 + target_pct / 100)
        
        risk_amount = self.cash * 0.03
        risk_per_unit = abs(entry_price - stop_loss) / entry_price
        if risk_per_unit == 0:
            return False
        
        position_value = risk_amount / risk_per_unit
        
        # تعديل الحجم حسب الثقة
        if confidence >= CONFIDENCE_HIGH:
            position_value *= 1.3
        elif confidence < CONFIDENCE_MEDIUM:
            position_value *= 0.7
        
        position_value = min(position_value, self.cash * 0.95)
        
        if position_value > self.cash or len(self.positions) >= MAX_POSITIONS:
            return False
        
        for pos in self.positions:
            if pos['symbol'] == symbol:
                return False
        
        amount = position_value / entry_price
        self.cash -= position_value
        
        self.positions.append({
            'symbol': symbol,
            'entry_price': entry_price,
            'amount': amount,
            'position_value': position_value,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'entry_time': datetime.now(),
            'alpha': alpha,
            'target_pct': target_pct,
            'highest_price': entry_price,
            'atr_value': atr,
            'breakeven_activated': False,
            'current_stop': stop_loss,
            'signal_type': signal_type,
            'confidence': confidence,
            'entry_reason': entry_reason
        })
        
        confidence_tag = "🟢" if confidence >= CONFIDENCE_HIGH else ("🟡" if confidence >= CONFIDENCE_MEDIUM else "🟠")
        msg = (f"{confidence_tag} صفقة جديدة ({signal_type}، ثقة {confidence}%): {symbol}\n"
               f"سعر الدخول: {entry_price:.4f}\n"
               f"قيمة الصفقة: {position_value:.2f}$\n"
               f"🛑 وقف: {stop_loss:.4f} | 🎯 هدف: {take_profit:.4f}\n"
               f"📈 صعود: {target_pct:.2f}%\n"
               f"💰 الرصيد: {self.cash:.2f}$\n"
               f"📝 السبب: {entry_reason}")
        print(f"{PROJECT_TAG} {msg}")
        asyncio.create_task(send_telegram_message(msg))
        self.save_state()
        return True
    
    def update_positions(self, prices):
        to_close = []
        for i, pos in enumerate(self.positions):
            symbol = pos['symbol']
            if symbol not in prices:
                continue
            price = prices[symbol]
            
            if price > pos['highest_price']:
                pos['highest_price'] = price
            
            atr_value = pos.get('atr_value', price * 0.03)
            trailing_stop = pos['highest_price'] - (ATR_MULTIPLIER * atr_value)
            
            if not pos['breakeven_activated'] and price >= pos['entry_price'] * (1 + BREAKEVEN_ACTIVATION):
                pos['breakeven_activated'] = True
                trailing_stop = max(trailing_stop, pos['entry_price'])
            
            if trailing_stop > pos['current_stop']:
                pos['current_stop'] = trailing_stop
            
            final_stop = pos['current_stop']
            
            if price <= final_stop:
                reason = "وقف خسارة متحرك"
                if pos['breakeven_activated'] and final_stop >= pos['entry_price']:
                    reason = "وقف خسارة (تعادل)"
                to_close.append((i, price, reason))
            elif price <= pos['stop_loss']:
                to_close.append((i, price, "وقف خسارة أولي"))
            elif price >= pos['take_profit']:
                to_close.append((i, price, "جني أرباح"))
        
        for i, price, reason in sorted(to_close, key=lambda x: x[0], reverse=True):
            self.close_position(i, price, reason)
    
    def close_position(self, index, exit_price, reason):
        pos = self.positions.pop(index)
        exit_value = pos['amount'] * exit_price
        pnl = exit_value - pos['position_value']
        pnl_pct = (pnl / pos['position_value']) * 100
        self.cash += exit_value
        
        trade_record = {
            'symbol': pos['symbol'],
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'amount': pos['amount'],
            'entry_time': pos['entry_time'].isoformat(),
            'exit_time': datetime.now().isoformat(),
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'exit_reason': reason,
            'alpha': pos.get('alpha', 0),
            'target_pct': pos.get('target_pct', 0),
            'signal_type': pos.get('signal_type', 'unknown'),
            'confidence': pos.get('confidence', 0),
            'entry_reason': pos.get('entry_reason', '')
        }
        self.closed_trades.append(trade_record)
        self._append_trade_to_csv(trade_record)
        
        msg = f"🔴 إغلاق: {pos['symbol']}\n{reason}\nربح: {pnl:.2f}$ ({pnl_pct:.2f}%)\nرصيد: {self.cash:.2f}$"
        print(f"{PROJECT_TAG} {msg}")
        asyncio.create_task(send_telegram_message(msg))
        self.save_state()
    
    def get_stats(self):
        if not self.closed_trades:
            return None
        wins = [t for t in self.closed_trades if t['pnl'] > 0]
        losses = [t for t in self.closed_trades if t['pnl'] <= 0]
        win_rate = len(wins) / len(self.closed_trades) * 100 if self.closed_trades else 0
        total_pnl = sum(t['pnl'] for t in self.closed_trades)
        return {
            'total_trades': len(self.closed_trades),
            'win_count': len(wins),
            'loss_count': len(losses),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return_pct': (total_pnl / self.initial_capital) * 100,
            'current_cash': self.cash,
            'open_positions': len(self.positions)
        }
    
    def generate_report(self, current_prices=None):
        stats = self.get_stats()
        if not stats:
            return None
        
        with open(self.report_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                PROJECT_TAG,
                datetime.now().isoformat(),
                f"{self.cash:.2f}",
                f"{stats['total_pnl']:.2f}",
                f"{stats['total_return_pct']:.2f}",
                stats['total_trades'],
                stats['win_count'],
                stats['loss_count'],
                f"{stats['win_rate']:.2f}",
                stats['open_positions']
            ])
        
        report = f"📊 تقرير الأداء\n"
        report += f"💰 الرصيد: {self.cash:.2f}$ (بداية: {self.initial_capital}$)\n"
        report += f"📈 العائد: {stats['total_pnl']:.2f}$ ({stats['total_return_pct']:.2f}%)\n"
        report += f"📋 صفقات: {stats['total_trades']} | ✅ {stats['win_count']} | ❌ {stats['loss_count']}\n"
        report += f"🎯 نجاح: {stats['win_rate']:.2f}% | 🔓 مفتوحة: {stats['open_positions']}"
        
        if self.positions and current_prices:
            report += "\n\n📌 الصفقات المفتوحة:\n"
            for pos in self.positions:
                sym = pos['symbol']
                cp = current_prices.get(sym, pos['entry_price'])
                pnl = (cp - pos['entry_price']) * pos['amount']
                pnl_pct = ((cp / pos['entry_price']) - 1) * 100
                report += f"  - {sym}: {pos['entry_price']:.4f} → {cp:.4f} | {pnl:.2f}$ ({pnl_pct:.2f}%)\n"
        
        return report

# =========================================================
# تصنيف العملات
# =========================================================
async def classify_symbols(exchange, symbols):
    gold = []
    print(f"{PROJECT_TAG} 📊 جاري تصنيف {len(symbols)} عملة...")
    
    for sym in symbols[:200]:
        try:
            ticker = await exchange.fetch_ticker(sym)
            volume = ticker.get('quoteVolume', 0) or 0
            high = ticker.get('high', 0) or 0
            low = ticker.get('low', 0) or 0
            close = ticker.get('close', 0) or 1
            volatility = (high - low) / close if close > 0 else 0
            
            if volume > 5_000_000 and volatility > 0.03:
                gold.append(sym)
        except:
            pass
    
    print(f"{PROJECT_TAG} ✅ تصنيف: 🥇 Gold={len(gold)}")
    return gold

# =========================================================
# المسح والتحليل
# =========================================================
def fetch_ohlcv_sync(exchange, symbol, timeframe='5m', limit=40):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except:
        return pd.DataFrame()

def detect_market_regime(exchange):
    try:
        df_btc = fetch_ohlcv_sync(exchange, 'BTC/USDT', '1h', 24)
        if df_btc.empty:
            return {'regime': 'CALM'}
        returns = df_btc['close'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(24)
        slope = np.polyfit(np.arange(len(df_btc)), df_btc['close'], 1)[0]
        trend = slope / df_btc['close'].mean()
        
        if volatility > 0.04:
            return {'regime': 'HOT'}
        elif trend < -0.015:
            return {'regime': 'COLD'}
        else:
            return {'regime': 'CALM'}
    except:
        return {'regime': 'CALM'}

async def scan_gold_symbols(exchange_async, exchange_sync, symbols):
    candidates = []
    
    for sym in symbols[:GOLD_COUNT]:
        try:
            ticker = await exchange_async.fetch_ticker(sym)
            close = ticker.get('close', 0)
            if close <= 0:
                continue
            
            df = fetch_ohlcv_sync(exchange_sync, sym)
            if df.empty:
                continue
            
            fs = calculate_filter_score(df)
            if fs < MIN_FILTER_SCORE:
                continue
            
            alpha = calculate_alpha(df)
            target_pct = calculate_target_percentage(df)
            
            cand = {
                'symbol': sym,
                'entry_price': close,
                'filter_score': fs,
                'alpha': alpha,
                'target_pct': target_pct,
                'strategy_points': 3,
                'volume_confirm': True,
                'trend_confirm': True,
                'priority': 5,
                'df': df
            }
            
            is_explosive, score = check_explosion_criteria(cand)
            cand['is_explosive'] = is_explosive
            cand['explosion_score'] = score
            
            candidates.append(cand)
        except:
            continue
    
    candidates.sort(key=lambda x: (x['is_explosive'], x['alpha']), reverse=True)
    return candidates[:TOP_CANDIDATES_COUNT]

# =========================================================
# أوامر تيليجرام
# =========================================================
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, auto_paused_reason, trader_instance
    
    if trader_instance is None:
        await update.message.reply_text(f"{PROJECT_TAG} ⚠️ نظام التداول غير مهيأ.")
        return
    
    status_text = "🟢 نشط" if not is_paused else f"⏸️ متوقف ({auto_paused_reason or 'يدوي'})"
    stats = trader_instance.get_stats()
    
    if stats:
        msg = f"{PROJECT_TAG}\n🤖 حالة البوت: {status_text}\n"
        msg += f"💰 الرصيد: {trader_instance.cash:.2f}$\n"
        msg += f"📈 العائد: {stats['total_pnl']:.2f}$ ({stats['total_return_pct']:.2f}%)\n"
        msg += f"📋 صفقات: {stats['total_trades']} | ✅ {stats['win_count']} | ❌ {stats['loss_count']}\n"
        msg += f"🎯 نجاح: {stats['win_rate']:.2f}% | 🔓 مفتوحة: {stats['open_positions']}"
    else:
        msg = f"{PROJECT_TAG}\n🤖 حالة البوت: {status_text}\n💰 الرصيد: {trader_instance.cash:.2f}$"
    
    await update.message.reply_text(msg)

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global trader_instance
    
    if trader_instance is None:
        await update.message.reply_text(f"{PROJECT_TAG} ⚠️ نظام التداول غير مهيأ.")
        return
    
    now = datetime.now()
    last_24h = [t for t in trader_instance.closed_trades 
                if (now - datetime.fromisoformat(t['exit_time'])).total_seconds() < 86400]
    
    if not last_24h:
        await update.message.reply_text(f"{PROJECT_TAG} 📭 لا توجد صفقات في آخر 24 ساعة.")
        return
    
    wins = [t for t in last_24h if t['pnl'] > 0]
    losses = [t for t in last_24h if t['pnl'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in last_24h)
    win_rate = len(wins) / len(last_24h) * 100 if last_24h else 0
    
    msg = f"{PROJECT_TAG}\n📊 أداء آخر 24 ساعة:\n\n"
    msg += f"📋 صفقات: {len(last_24h)} | ✅ {len(wins)} | ❌ {len(losses)}\n"
    msg += f"🎯 نسبة نجاح: {win_rate:.1f}%\n"
    msg += f"💰 صافي الربح: {total_pnl:+.2f}$\n"
    msg += f"💵 رصيد حالي: {trader_instance.cash:.2f}$"
    
    await update.message.reply_text(msg)

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, auto_paused_reason
    is_paused = True
    auto_paused_reason = "يدوي"
    await update.message.reply_text(f"{PROJECT_TAG} ⏸️ تم إيقاف فتح الصفقات الجديدة.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, auto_paused_reason
    is_paused = False
    auto_paused_reason = None
    await update.message.reply_text(f"{PROJECT_TAG} ▶️ تم استئناف فتح الصفقات.")

# =========================================================
# حلقة التداول الرئيسية
# =========================================================
async def trading_loop():
    global gold_symbols, symbol_classification_time, trader_instance
    global is_paused, auto_paused_reason
    
    exchange_async = ccxt_async.gateio({'enableRateLimit': True})
    exchange_sync = ccxt.gateio({'enableRateLimit': True})
    
    # تحميل العملات
    markets = await exchange_async.load_markets()
    if markets:
        all_syms = [s for s in markets if s.endswith('/USDT') and '.d' not in s]
        gold_symbols = await classify_symbols(exchange_async, all_syms)
        symbol_classification_time = time.time()
    else:
        print(f"{PROJECT_TAG} ❌ فشل تحميل العملات")
        return
    
    trader = PaperTrader(initial_capital=INITIAL_CAPITAL)
    trader_instance = trader
    tracker = ScenarioTracker()
    
    last_report = time.time()
    last_gold_scan = 0
    last_price_update = 0
    last_backup = time.time()
    
    print(f"{PROJECT_TAG} 🤖 بدء نظام PROJET_100 - {datetime.now()}\n")
    await send_telegram_message(f"🚀 نظام PROJET_100 بدأ العمل!\n🥇 Gold: {len(gold_symbols)} عملة\n⚙️ الإعدادات المثلى مفعلة")
    
    # ⭐ نسخة احتياطية عند البدء
    backup_code()
    
    while True:
        try:
            current_time = time.time()
            
            # ⭐ فحص عطلة نهاية الأسبوع
            if WEEKEND_PAUSE and is_weekend():
                if not is_paused:
                    is_paused = True
                    auto_paused_reason = "عطلة نهاية الأسبوع"
                    await send_telegram_message("📅 تم إيقاف التداول تلقائياً (عطلة نهاية الأسبوع)")
                await asyncio.sleep(3600)
                continue
            
            # تحديث الأسعار
            if current_time - last_price_update >= PRICE_UPDATE_INTERVAL:
                prices = {}
                for trade in tracker.active_trades:
                    try:
                        ticker = exchange_sync.fetch_ticker(trade['symbol'])
                        if ticker:
                            prices[trade['symbol']] = ticker['last']
                    except:
                        pass
                tracker.update_prices(prices)
                
                # تحديث الصفقات المفتوحة
                pos_prices = {}
                for pos in trader.positions:
                    try:
                        ticker = exchange_sync.fetch_ticker(pos['symbol'])
                        if ticker:
                            pos_prices[pos['symbol']] = ticker['last']
                    except:
                        pass
                trader.update_positions(pos_prices)
                
                last_price_update = current_time
            
            # فحص الإيقاف
            if is_paused:
                await asyncio.sleep(10)
                continue
            
            market_ctx = detect_market_regime(exchange_sync)
            
            if market_ctx.get('regime') == 'COLD':
                print(f"{PROJECT_TAG} ⚠️ السوق بارد (COLD)، تخطي فتح الصفقات")
                await asyncio.sleep(60)
                continue
            
            # مسح Gold
            if current_time - last_gold_scan >= GOLD_SCAN_INTERVAL and gold_symbols:
                print(f"\n{PROJECT_TAG} 🥇 مسح Gold: {len(gold_symbols[:GOLD_COUNT])} عملة")
                candidates = await scan_gold_symbols(exchange_async, exchange_sync, gold_symbols)
                
                if candidates:
                    print(f"{PROJECT_TAG} ✅ تم اكتشاف {len(candidates)} عملة مرشحة")
                    
                    for cand in candidates:
                        market_ctx = detect_market_regime(exchange_sync)
                        cand['confidence'] = calculate_confidence_score(cand, market_ctx)
                        
                        # تسجيل في السيناريوهات
                        tracker.add_trade(
                            cand['symbol'],
                            cand['entry_price'],
                            datetime.now(),
                            cand.get('df')
                        )
                        
                        # فتح صفقة إذا كانت الثقة كافية
                        if cand['confidence'] >= MIN_CONFIDENCE_TO_TRADE:
                            entry_reason = ""
                            if cand['is_explosive']:
                                entry_reason = f"انفجار ({cand['explosion_score']}/4 معايير)"
                            else:
                                entry_reason = f"سكور عالي (ألفا: {cand['alpha']:.3f})"
                            
                            signal_type = 'explosion' if cand['is_explosive'] else 'alpha'
                            trader.open_position(cand, exchange_sync, signal_type, entry_reason)
                        
                        # إشعار للانفجارات
                        if cand['is_explosive']:
                            msg = f"🔥 انفجار وشيك: {cand['symbol']}\nسعر: {cand['entry_price']:.4f}\nألفا: {cand['alpha']:.3f}\nهدف: {cand['target_pct']:.2f}%\nثقة: {cand['confidence']}%"
                            await send_telegram_message(msg)
                
                last_gold_scan = current_time
            
            # تقرير كل ساعة
            if current_time - last_report >= 3600:
                prices = {}
                for pos in trader.positions:
                    try:
                        ticker = exchange_sync.fetch_ticker(pos['symbol'])
                        if ticker:
                            prices[pos['symbol']] = ticker['last']
                    except:
                        pass
                
                report = trader.generate_report(prices)
                if report:
                    stats = tracker.get_statistics()
                    if stats:
                        report += "\n\n📊 إحصائيات السيناريوهات:\n"
                        for scenario, s in stats.items():
                            if s['total'] > 0:
                                report += f"\n{scenario}: نجاح {s['win_rate']:.1f}% | عامل ربح {s['profit_factor']:.2f}"
                    
                    await send_telegram_message(report)
                
                # إرسال ملفات CSV
                if os.path.exists(trader.trades_csv):
                    asyncio.create_task(send_csv_file(trader.trades_csv, "📁 صفقات مغلقة"))
                if os.path.exists(trader.report_csv):
                    asyncio.create_task(send_csv_file(trader.report_csv, "📁 تقرير الأداء"))
                if os.path.exists(tracker.scenarios_csv):
                    asyncio.create_task(send_csv_file(tracker.scenarios_csv, "📁 نتائج السيناريوهات"))
                
                last_report = current_time
            
            # نسخ احتياطي كل 24 ساعة
            if current_time - last_backup >= 86400:
                backup_code()
                last_backup = current_time
            
            await asyncio.sleep(2)
            
        except KeyboardInterrupt:
            print(f"\n{PROJECT_TAG} 👋 إيقاف...")
            await send_telegram_message("⏹️ تم إيقاف البوت")
            break
        except Exception as e:
            print(f"{PROJECT_TAG} ❌ خطأ: {e}")
            await asyncio.sleep(30)
    
    await exchange_async.close()

# =========================================================
# الدالة الرئيسية
# =========================================================
async def main():
    global telegram_app
    
    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    await telegram_app.initialize()
    print(f"{PROJECT_TAG} 🤖 تطبيق Telegram جاهز...")
    
    # إضافة الأوامر
    telegram_app.add_handler(CommandHandler("status", status_command))
    telegram_app.add_handler(CommandHandler("performance", performance_command))
    telegram_app.add_handler(CommandHandler("pause", pause_command))
    telegram_app.add_handler(CommandHandler("resume", resume_command))
    
    await telegram_app.start()
    
    try:
        await trading_loop()
    except KeyboardInterrupt:
        print(f"\n{PROJECT_TAG} 👋 إيقاف...")
    finally:
        await telegram_app.stop()
        await telegram_app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
