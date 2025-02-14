import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import talib
import time
from datetime import datetime
from telegram import Bot
from sklearn.ensemble import RandomForestClassifier
import joblib

# Konfigurasi MetaTrader 5 & Telegram
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"
bot = Bot(token=TELEGRAM_TOKEN)

SYMBOL = "XAUUSD"
RISK_PER_TRADE = 0.02  # Risiko per trade (2% dari equity)
STOP_LOSS_ATR_MULTIPLIER = 2
TAKE_PROFIT_ATR_MULTIPLIER = 4
TRAILING_STOP_ATR_MULTIPLIER = 1.5
ADX_THRESHOLD = 25
TIMEFRAME_M15 = mt5.TIMEFRAME_M15
TIMEFRAME_H1 = mt5.TIMEFRAME_H1
TRADE_START_HOUR = 8  # Mulai trading jam 08:00
TRADE_END_HOUR = 20  # Selesai trading jam 20:00

def initialize_mt5():
    if not mt5.initialize():
        print("MT5 initialization failed!")
        return False
    return True

def get_equity():
    account_info = mt5.account_info()
    return account_info.equity if account_info else 0

def get_candlestick_data(symbol, timeframe, bars=200):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def detect_patterns(df):
    df['Bullish_Engulfing'] = talib.CDLENGULFING(df['open'], df['high'], df['low'], df['close'])
    df['Bearish_Engulfing'] = -talib.CDLENGULFING(df['open'], df['high'], df['low'], df['close'])
    df['RSI'] = talib.RSI(df['close'], timeperiod=14)
    df['ADX'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)
    df['ATR'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14)
    df['OBV'] = talib.OBV(df['close'], df['tick_volume'])
    return df

def check_trend():
    df_m15 = get_candlestick_data(SYMBOL, TIMEFRAME_M15)
    df_h1 = get_candlestick_data(SYMBOL, TIMEFRAME_H1)
    m15_trend = df_m15['close'].iloc[-1] > df_m15['close'].iloc[-2]
    h1_trend = df_h1['close'].iloc[-1] > df_h1['close'].iloc[-2]
    return m15_trend == h1_trend

def calculate_lot_size(risk_percentage, atr_value):
    equity = get_equity()
    risk_amount = equity * risk_percentage
    lot_size = risk_amount / (atr_value * 1000)
    return round(lot_size, 2)

def train_ml_model():
    df = get_candlestick_data(SYMBOL, TIMEFRAME_M15, 500)
    df = detect_patterns(df)
    features = df[['Bullish_Engulfing', 'Bearish_Engulfing', 'RSI', 'ADX', 'ATR', 'OBV']]
    df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, 0)
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(features, df['target'])
    joblib.dump(model, "ml_model.pkl")
    return model

def predict_signal(df):
    try:
        model = joblib.load("ml_model.pkl")
    except:
        model = train_ml_model()
    features = df[['Bullish_Engulfing', 'Bearish_Engulfing', 'RSI', 'ADX', 'ATR', 'OBV']].iloc[-1].values.reshape(1, -1)
    return model.predict(features)[0]

def place_order(order_type, atr_value):
    lot_size = calculate_lot_size(RISK_PER_TRADE, atr_value)
    price = mt5.symbol_info_tick(SYMBOL).ask if order_type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(SYMBOL).bid
    stop_loss = price - (STOP_LOSS_ATR_MULTIPLIER * atr_value) if order_type == mt5.ORDER_TYPE_BUY else price + (STOP_LOSS_ATR_MULTIPLIER * atr_value)
    take_profit = price + (TAKE_PROFIT_ATR_MULTIPLIER * atr_value) if order_type == mt5.ORDER_TYPE_BUY else price - (TAKE_PROFIT_ATR_MULTIPLIER * atr_value)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "sl": stop_loss,
        "tp": take_profit,
        "deviation": 10,
        "magic": 123456,
        "comment": "AI Candlestick Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        bot.send_message(TELEGRAM_CHAT_ID, f"✅ Trade Executed: {SYMBOL} {order_type} at {price}")
    else:
        bot.send_message(TELEGRAM_CHAT_ID, f"❌ Trade Failed: {result.comment}")

def run_trading_bot():
    if not initialize_mt5():
        return
    while True:
        now = datetime.now()
        if not (TRADE_START_HOUR <= now.hour < TRADE_END_HOUR):
            time.sleep(60)
            continue
        df = get_candlestick_data(SYMBOL, TIMEFRAME_M15)
        df = detect_patterns(df)
        atr_value = df['ATR'].iloc[-1]
        if check_trend():
            prediction = predict_signal(df)
            if prediction == 1:
                print("📈 ML Prediction: Buy Signal Detected!")
                place_order(mt5.ORDER_TYPE_BUY, atr_value)
            elif prediction == 0:
                print("📉 ML Prediction: Sell Signal Detected!")
                place_order(mt5.ORDER_TYPE_SELL, atr_value)
        time.sleep(60)

run_trading_bot()

