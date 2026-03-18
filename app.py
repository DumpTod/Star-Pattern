# =============================================================================
# MORNING STAR & EVENING STAR PATTERN SCANNER - FULL STRATEGY + AUTO-TOKEN
# =============================================================================
from flask import Flask, render_template, jsonify, request, redirect
from fyers_apiv3 import fyersModel
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os

app = Flask(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================
FYERS_APP_ID = os.environ.get('FYERS_APP_ID', '')
FYERS_SECRET_KEY = os.environ.get('FYERS_SECRET_KEY', '')
FYERS_REDIRECT_URL = os.environ.get('FYERS_REDIRECT_URL', '')
FYERS_ACCESS_TOKEN = os.environ.get('FYERS_ACCESS_TOKEN', '')

SYMBOL_MAP = {
    'NIFTY50': 'NSE:NIFTY50-INDEX',
    'BANKNIFTY': 'NSE:NIFTYBANK-INDEX',
    'SENSEX': 'BSE:SENSEX-INDEX'
}

TRADES_FILE = 'trades_history.json'

# =============================================================================
# TOKEN REFRESH ROUTES (FIXED)
# =============================================================================
@app.route('/login')
def login():
    """Starts the Fyers Login process"""
    try:
        session = fyersModel.SessionModel(
            client_id=FYERS_APP_ID,
            secret_key=FYERS_SECRET_KEY,
            redirect_uri=FYERS_REDIRECT_URL,
            response_type="code",
            grant_type="authorization_code"
        )
        auth_url = session.generate_authcode()  # FIXED: was generate_auth_code()
        return redirect(auth_url)
    except Exception as e:
        return f"<h2>❌ Error</h2><p>{str(e)}</p><p>Check your FYERS_APP_ID, FYERS_SECRET_KEY, and FYERS_REDIRECT_URL in Render environment variables.</p>"

@app.route('/callback')
def auth_callback():
    """Captures the code from Fyers and updates the Token automatically"""
    auth_code = request.args.get('auth_code')
    if not auth_code:
        return "<h2>❌ Error</h2><p>No auth code received from Fyers.</p>"

    try:
        session = fyersModel.SessionModel(
            client_id=FYERS_APP_ID,
            secret_key=FYERS_SECRET_KEY,
            redirect_uri=FYERS_REDIRECT_URL,
            response_type="code",
            grant_type="authorization_code"
        )
        session.set_token(auth_code)
        response = session.generate_token()
        
        if response.get('s') == 'ok' or 'access_token' in response:
            global FYERS_ACCESS_TOKEN
            FYERS_ACCESS_TOKEN = response['access_token']
            return """
            <html>
            <head>
                <style>
                    body { font-family: Arial; background: #FAF9F6; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
                    .card { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); text-align: center; }
                    h2 { color: #27ae60; }
                    p { color: #666; }
                    a { background: #4682B4; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; display: inline-block; margin-top: 20px; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h2>✅ Token Updated Successfully!</h2>
                    <p>The scanner is now ready to use.</p>
                    <a href="/">Go to Scanner</a>
                </div>
            </body>
            </html>
            """
        else:
            return f"<h2>❌ Token Generation Failed</h2><p>{response.get('message', response)}</p>"
    except Exception as e:
        return f"<h2>❌ Error</h2><p>{str(e)}</p>"

@app.route('/api/token-status')
def token_status():
    """Check if current token is valid"""
    try:
        if not FYERS_ACCESS_TOKEN:
            return jsonify({'success': True, 'valid': False, 'message': 'No token set'})
        
        fyers = get_fyers_client()
        profile = fyers.get_profile()
        
        if profile.get('s') == 'ok':
            return jsonify({
                'success': True,
                'valid': True,
                'user': profile.get('data', {}).get('name', 'Unknown')
            })
        else:
            return jsonify({'success': True, 'valid': False, 'message': profile.get('message', 'Invalid token')})
    except Exception as e:
        return jsonify({'success': True, 'valid': False, 'message': str(e)})

# =============================================================================
# FYERS CLIENT & DATA FUNCTIONS
# =============================================================================
def get_fyers_client():
    return fyersModel.FyersModel(client_id=FYERS_APP_ID, token=FYERS_ACCESS_TOKEN, is_async=False, log_path="")

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, indent=4)

def fetch_ohlc(symbol, timeframe, days=5):
    try:
        fyers = get_fyers_client()
        data = {
            "symbol": SYMBOL_MAP.get(symbol, symbol),
            "resolution": timeframe,
            "date_format": "1",
            "range_from": (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'),
            "range_to": datetime.now().strftime('%Y-%m-%d'),
            "cont_flag": "1"
        }
        response = fyers.history(data=data)
        if response and response.get('s') == 'ok':
            df = pd.DataFrame(response.get('candles'), columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s').dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
            return df
        return None
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def get_current_price(symbol):
    try:
        fyers = get_fyers_client()
        data = {"symbols": SYMBOL_MAP.get(symbol, symbol)}
        response = fyers.quotes(data)
        if response.get('s') == 'ok' and response.get('d'):
            return response['d'][0]['v']['lp']
        return None
    except:
        return None

# =============================================================================
# PATTERN DETECTION
# =============================================================================
def is_morning_star(df):
    if df is None or len(df) < 3:
        return False
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    cond1 = c1['close'] < c1['open']  # First candle bearish
    cond2 = c2['low'] < c1['low']      # Second candle gaps down
    cond3 = c3['close'] > c3['open']   # Third candle bullish
    cond4 = c3['low'] < c1['low'] and c3['low'] >= c2['low']  # Third low condition
    return all([cond1, cond2, cond3, cond4])

def is_evening_star(df):
    if df is None or len(df) < 3:
        return False
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    cond1 = c1['close'] > c1['open']   # First candle bullish
    cond2 = c2['high'] > c1['high']    # Second candle gaps up
    cond3 = c3['close'] < c3['open']   # Third candle bearish
    cond4 = c3['high'] > c1['high'] and c3['high'] <= c2['high']  # Third high condition
    return all([cond1, cond2, cond3, cond4])

def classify_regime(df):
    if df is None or len(df) < 50:
        return "UNKNOWN"
    close = df['close']
    sma20 = close.rolling(window=20).mean()
    sma50 = close.rolling(window=50).mean()
    curr_p, curr_20, curr_50 = close.iloc[-1], sma20.iloc[-1], sma50.iloc[-1]
    prev_20 = sma20.iloc[-2]
    
    if curr_p > curr_20 > curr_50:
        return "STRONG_BULLISH" if curr_20 > prev_20 else "BULLISH"
    if curr_p < curr_20 < curr_50:
        return "STRONG_BEARISH" if curr_20 < prev_20 else "BEARISH"
    if curr_20 > curr_50:
        return "WEAK_BULLISH"
    if curr_20 < curr_50:
        return "WEAK_BEARISH"
    return "SIDEWAYS"

# =============================================================================
# PAGE ROUTES
# =============================================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/history')
def history():
    return render_template('history.html')

# =============================================================================
# API ROUTES
# =============================================================================
@app.route('/api/scan', methods=['GET'])
def api_scan():
    try:
        results = []
        for symbol in SYMBOL_MAP.keys():
            df_1h = fetch_ohlc(symbol, "60", days=10)
            if df_1h is not None and len(df_1h) >= 3:
                regime = classify_regime(df_1h)
                pattern = None
                signal = None
                
                if is_morning_star(df_1h):
                    pattern = "MORNING_STAR"
                    signal = "BUY"
                elif is_evening_star(df_1h):
                    pattern = "EVENING_STAR"
                    signal = "SELL"
                
                if pattern:
                    entry_price = round(df_1h['close'].iloc[-1], 2)
                    if signal == "BUY":
                        target_price = round(entry_price * 1.005, 2)
                        stoploss_price = round(entry_price * 0.997, 2)
                    else:
                        target_price = round(entry_price * 0.995, 2)
                        stoploss_price = round(entry_price * 1.003, 2)
                    
                    current_price = get_current_price(symbol) or entry_price
                    
                    trade = {
                        'id': f"{symbol}_{datetime.now().strftime('%Y%m%d%H%M')}",
                        'symbol': symbol,
                        'pattern': pattern,
                        'signal': signal,
                        'regime': regime,
                        'entry_price': entry_price,
                        'current_price': round(current_price, 2),
                        'target_price': target_price,
                        'stoploss_price': stoploss_price,
                        'pattern_time': df_1h['timestamp'].iloc[-1].strftime('%Y-%m-%d %H:%M'),
                        'status': 'ACTIVE',
                        'result': None,
                        'pnl_points': None,
                        'scanned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    results.append(trade)
                    
                    # Auto-add to history
                    trades = load_trades()
                    existing_ids = [t['id'] for t in trades]
                    if trade['id'] not in existing_ids:
                        trades.append(trade)
                        save_trades(trades)
        
        return jsonify({'success': True, 'patterns': results, 'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trades', methods=['GET'])
def api_trades():
    try:
        trades = load_trades()
        return jsonify({'success': True, 'trades': trades})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/rescan', methods=['POST'])
def api_rescan():
    try:
        trades = load_trades()
        updated = []
        
        for trade in trades:
            if trade['status'] != 'CLOSED':
                trade = rescan_trade(trade)
            updated.append(trade)
        
        save_trades(updated)
        return jsonify({'success': True, 'trades': updated, 'rescan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/rescan/<trade_id>', methods=['POST'])
def api_rescan_single(trade_id):
    try:
        trades = load_trades()
        for i, trade in enumerate(trades):
            if trade['id'] == trade_id:
                trades[i] = rescan_trade(trade)
                save_trades(trades)
                return jsonify({'success': True, 'trade': trades[i]})
        return jsonify({'success': False, 'error': 'Trade not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete/<trade_id>', methods=['DELETE'])
def api_delete(trade_id):
    try:
        trades = load_trades()
        trades = [t for t in trades if t['id'] != trade_id]
        save_trades(trades)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear', methods=['DELETE'])
def api_clear():
    try:
        save_trades([])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/stats', methods=['GET'])
def api_stats():
    try:
        trades = load_trades()
        total = len(trades)
        closed = [t for t in trades if t['status'] == 'CLOSED']
        active = [t for t in trades if t['status'] == 'ACTIVE']
        targets = [t for t in closed if t.get('result') == 'TARGET']
        stoplosses = [t for t in closed if t.get('result') == 'STOPLOSS']
        
        win_rate = (len(targets) / len(closed) * 100) if closed else 0
        total_pnl = sum([t.get('pnl_points', 0) or 0 for t in closed])
        
        return jsonify({
            'success': True,
            'stats': {
                'total_trades': total,
                'active_trades': len(active),
                'closed_trades': len(closed),
                'targets_hit': len(targets),
                'stoplosses_hit': len(stoplosses),
                'win_rate': round(win_rate, 1),
                'total_pnl': round(total_pnl, 2)
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# =============================================================================
# RESCAN TRADE LOGIC
# =============================================================================
def rescan_trade(trade):
    try:
        symbol = trade['symbol']
        entry_price = trade['entry_price']
        target_price = trade['target_price']
        stoploss_price = trade['stoploss_price']
        signal = trade['signal']
        
        # Get current price
        current_price = get_current_price(symbol)
        if current_price:
            trade['current_price'] = round(current_price, 2)
        
        # Get 5-min data to check if target/SL hit
        df = fetch_ohlc(symbol, "5", days=2)
        if df is None or len(df) == 0:
            return trade
        
        pattern_time = datetime.strptime(trade['pattern_time'], '%Y-%m-%d %H:%M')
        pattern_time = pattern_time.replace(tzinfo=df['timestamp'].iloc[0].tzinfo)
        
        # Filter data after pattern time
        df_after = df[df['timestamp'] > pattern_time]
        
        if len(df_after) == 0:
            return trade
        
        # Check each candle
        for _, row in df_after.iterrows():
            if signal == 'BUY':
                if row['low'] <= stoploss_price:
                    trade['status'] = 'CLOSED'
                    trade['result'] = 'STOPLOSS'
                    trade['exit_price'] = stoploss_price
                    trade['exit_time'] = row['timestamp'].strftime('%Y-%m-%d %H:%M')
                    trade['pnl_points'] = round(stoploss_price - entry_price, 2)
                    trade['pnl_percent'] = round((stoploss_price - entry_price) / entry_price * 100, 4)
                    return trade
                elif row['high'] >= target_price:
                    trade['status'] = 'CLOSED'
                    trade['result'] = 'TARGET'
                    trade['exit_price'] = target_price
                    trade['exit_time'] = row['timestamp'].strftime('%Y-%m-%d %H:%M')
                    trade['pnl_points'] = round(target_price - entry_price, 2)
                    trade['pnl_percent'] = round((target_price - entry_price) / entry_price * 100, 4)
                    return trade
            else:  # SELL
                if row['high'] >= stoploss_price:
                    trade['status'] = 'CLOSED'
                    trade['result'] = 'STOPLOSS'
                    trade['exit_price'] = stoploss_price
                    trade['exit_time'] = row['timestamp'].strftime('%Y-%m-%d %H:%M')
                    trade['pnl_points'] = round(entry_price - stoploss_price, 2)
                    trade['pnl_percent'] = round((entry_price - stoploss_price) / entry_price * 100, 4)
                    return trade
                elif row['low'] <= target_price:
                    trade['status'] = 'CLOSED'
                    trade['result'] = 'TARGET'
                    trade['exit_price'] = target_price
                    trade['exit_time'] = row['timestamp'].strftime('%Y-%m-%d %H:%M')
                    trade['pnl_points'] = round(entry_price - target_price, 2)
                    trade['pnl_percent'] = round((entry_price - target_price) / entry_price * 100, 4)
                    return trade
        
        # Still active - check direction
        if current_price:
            if signal == 'BUY':
                trade['pnl_points'] = round(current_price - entry_price, 2)
                trade['result'] = 'IN_PROFIT' if current_price > entry_price else 'IN_LOSS'
            else:
                trade['pnl_points'] = round(entry_price - current_price, 2)
                trade['result'] = 'IN_PROFIT' if current_price < entry_price else 'IN_LOSS'
            trade['pnl_percent'] = round(trade['pnl_points'] / entry_price * 100, 4)
        
        return trade
    except Exception as e:
        print(f"Rescan error: {e}")
        return trade

# =============================================================================
# MAIN
# =============================================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
