def update_positions(self, current_prices):
    to_close = []
    for i, pos in enumerate(self.positions):
        symbol = pos['symbol']
        if symbol not in current_prices:
            continue
        price = current_prices[symbol]
        
        # تحديث أعلى سعر وصلت له العملة
        if 'highest_price' not in pos or price > pos['highest_price']:
            pos['highest_price'] = price
        
        # ⭐ الحصول على ATR الحالي (يمكن استخدام المخزن عند الدخول أو تحديثه)
        atr_value = pos.get('atr_value', price * 0.03)
        
        # ⭐ حساب وقف الخسارة المتحرك بناءً على ATR
        # نستخدم مضاعف 2.5 (يمكنك تعديله حسب رغبتك)
        atr_multiplier = 2.5
        trailing_stop = pos['highest_price'] - (atr_multiplier * atr_value)
        
        # ⭐ تأمين الأرباح: إذا ارتفع السعر 2% فوق الدخول، نحرك الوقف إلى نقطة التعادل
        breakeven_activated = pos.get('breakeven_activated', False)
        if not breakeven_activated and price >= pos['entry_price'] * 1.02:
            breakeven_activated = True
            pos['breakeven_activated'] = True
            # تعيين الوقف إلى نقطة الدخول كحد أدنى
            trailing_stop = max(trailing_stop, pos['entry_price'])
        
        # ضمان أن الوقف لا ينخفض أبداً (منطق التتبع)
        if 'current_stop' not in pos or trailing_stop > pos['current_stop']:
            pos['current_stop'] = trailing_stop
        
        final_stop = pos.get('current_stop', pos['stop_loss'])
        
        # شروط الإغلاق
        if price <= final_stop:
            reason = "وقف خسارة متحرك"
            if breakeven_activated and final_stop >= pos['entry_price']:
                reason = "وقف خسارة متحرك (نقطة التعادل)"
            to_close.append((i, price, reason))
        elif price <= pos['stop_loss']:  # وقف الخسارة الأصلي (احتياط)
            to_close.append((i, price, "وقف خسارة أولي"))
        elif price >= pos['take_profit']:
            to_close.append((i, price, "جني أرباح"))
            
    for i, price, reason in sorted(to_close, key=lambda x: x[0], reverse=True):
        self.close_position(i, price, reason)
