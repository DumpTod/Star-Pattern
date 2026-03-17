# =============================================================================
# MORNING STAR & EVENING STAR PATTERN SCANNER
# =============================================================================
from flask import Flask, render_template, jsonify, request
from fyers_apiv3 import fyersModel
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
import threading
import time

app = Flask(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================
FYERS_APP_ID = os.environ.get('FYERS_APP_ID', '')
FYERS_SECRET_KEY = os.environ.get('FYERS_SECRET_KEY', '')
FYERS_ACCESS_TOKEN = os.environ.get('FYERS_ACCESS_TOKEN', '')
FYERS_REDIRECT_URL = os.environ.get('FYERS_REDIRECT_URL', '')

# =============================================================================
# FYERS CLIENT
# =============================================================================
def get_fyers_client():
    """Initialize Fyers client"""
    try:
        fyers = fyersModel.FyersModel(
            client_id=FYERS_APP_ID,
            is_async=False,
            token=FYERS_ACCESS_TOKEN,
            log_path=""
        )
        return fyers
    except Exception as e:
        print(f"Error initializing Fyers: {e}")
        return None

# =============================================================================
# DATA FETCHING
# =============================================================================
def get_historical_data(fyers, symbol, resolution, from_date, to_date):
    """Fetch historical data from Fyers API"""
    try:
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": from_date.strftime('%Y-%m-%d'),
            "range_to": to_date.strftime('%Y-%m-%d'),
            "cont_flag": "1"
        }
        
        response = fyers.history(data=data)
        
        if response.get('s') == 'ok' and response.get('candles'):
            df = pd.DataFrame(
                response['candles'],
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
            df.set_index('datetime', inplace=True)
            return df
        return None
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def get_current_price(fyers, symbol):
    """Get current market price"""
    try:
        data = {"symbols": symbol}
        response = fyers.quotes(data)
        if response.get('s') == 'ok' and response.get('d'):
            return response['d'][0]['v']['lp']
        return None
    except Exception as e:
        print(f"Error getting price: {e}")
        return None

# =============================================================================
# PATTERN DETECTION
# =============================================================================
def is_bullish(open_price, close_price):
    return close_price > open_price

def is_bearish(open_price, close_price):
    return close_price < open_price

def detect_morning_star(c1, c2, c3):
    """Detect Morning Star (Bullish)"""
    o1, h1, l1, c1_close = c1['open'], c1['high'], c1['low'], c1['close']
    o2, h2, l2, c2_close = c2['open'], c2['high'], c2['low'], c2['close']
    o3, h3, l3, c3_close = c3['open'], c3['high'], c3['low'], c3['close']
    
    first_bearish = is_bearish(o1, c1_close)
    second_gap_down = l2 < l1
    third_bullish = is_bullish(o3, c3_close)
    third_low_condition = l3 < l1 and l3 >= l2
    
    if first_bearish and second_gap_down and third_bullish and third_low_condition:
        return True
    return False

def detect_evening_star(c1, c2, c3):
    """Detect Evening Star (Bearish)"""
    o1, h1, l1, c1_close = c1['open'], c1['high'], c1['low'], c1['close']
    o2, h2, l2, c2_close = c2['open'], c2['high'], c2['low'], c2['close']
    o3, h3, l3, c3_close = c3['open'], c3['high'], c3['low'], c3['close']
    
    first_bullish = is_bullish(o1, c1_close)
    second_gap_up = h2 > h1
    third_bearish = is_bearish(o3, c3_close)
    third_high_condition = h3 > h1 and h3 <= h2
    
    if first_bullish and second_gap_up and third_bearish and third_high_condition:
        return True
    return False

def calculate_regime(df):
    """Calculate market regime"""
    if len(df) < 50:
        return 'UNKNOWN'
    
    df = df.copy()
    df['SMA_20'] = df['close'].rolling(window=20).mean()
    df['SMA_50'] = df['close'].rolling(window=50).mean()
    
    last = df.iloc[-1]
    
    if pd.isna(last['SMA_20']) or pd.isna(last['SMA_50']):
        return 'UNKNOWN'
    
    above_sma20 = last['close'] > last['SMA_20']
    above_sma50 = last['close'] > last['SMA_50']
    sma20_above_sma50 = last['SMA_20'] > last['SMA_50']
    
    if above_sma20 and above_sma50 and sma20_above_sma50:
        return 'STRONG_BULLISH'
    elif not above_sma20 and not above_sma50 and not sma20_above_sma50:
        return 'STRONG_BEARISH'
    elif above_sma20:
        return 'BULLISH'
    elif not above_sma20:
        return 'BEARISH'
    else:
        return 'SIDEWAYS'

# =============================================================================
# SCANNER
# =============================================================================
def scan_patterns():
    """Scan all symbols for patterns"""
    fyers = get_fyers_client()
    if not fyers:
        return []
    
    patterns = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=10)
    
    for name, symbol in SYMBOL_MAP.items():
        try:
            # Get hourly data
            hourly_df = get_historical_data(fyers, symbol, '60', start_date, end_date)
            
            if hourly_df is None or len(hourly_df) < 3:
                continue
            
            # Get current price
            current_price = get_current_price(fyers, symbol)
            if current_price is None:
                current_price = hourly_df.iloc[-1]['close']
            
            # Calculate regime
            regime = calculate_regime(hourly_df)
            
            # Check last 3 candles for pattern
            c1 = hourly_df.iloc[-3]
            c2 = hourly_df.iloc[-2]
            c3 = hourly_df.iloc[-1]
            
            pattern_time = hourly_df.index[-1]
            
            # Check Morning Star
            if detect_morning_star(c1, c2, c3):
                entry_price = c3['close']
                target_price = entry_price * 1.005  # 0.5%
                stoploss_price = entry_price * 0.997  # 0.3%
                
                patterns.append({
                    'id': f"{name}_{pattern_time.strftime('%Y%m%d%H%M')}",
                    'symbol': name,
                    'symbol_full': symbol,
                    'pattern': 'MORNING_STAR',
                    'signal': 'BUY',
                    'pattern_time': pattern_time.strftime('%Y-%m-%d %H:%M'),
                    'entry_price': round(entry_price, 2),
                    'current_price': round(current_price, 2),
                    'target_price': round(target_price, 2),
                    'stoploss_price': round(stoploss_price, 2),
                    'regime': regime,
                    'status': 'ACTIVE',
                    'result': None,
                    'exit_price': None,
                    'exit_time': None,
                    'pnl_points': None,
                    'pnl_percent': None,
                    'scanned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
            
            # Check Evening Star
            if detect_evening_star(c1, c2, c3):
                entry_price = c3['close']
                target_price = entry_price * 0.995  # 0.5%
                stoploss_price = entry_price * 1.003  # 0.3%
                
                patterns.append({
                    'id': f"{name}_{pattern_time.strftime('%Y%m%d%H%M')}",
                    'symbol': name,
                    'symbol_full': symbol,
                    'pattern': 'EVENING_STAR',
                    'signal': 'SELL',
                    'pattern_time': pattern_time.strftime('%Y-%m-%d %H:%M'),
                    'entry_price': round(entry_price, 2),
                    'current_price': round(current_price, 2),
                    'target_price': round(target_price, 2),
                    'stoploss_price': round(stoploss_price, 2),
                    'regime': regime,
                    'status': 'ACTIVE',
                    'result': None,
                    'exit_price': None,
                    'exit_time': None,
                    'pnl_points': None,
                    'pnl_percent': None,
                    'scanned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                
        except Exception as e:
            print(f"Error scanning {name}: {e}")
    
    return patterns

# =============================================================================
# TRADE HISTORY MANAGEMENT
# =============================================================================
def load_trades():
    """Load trades from file"""
    try:
        if os.path.exists(TRADES_FILE):
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading trades: {e}")
    return []

def save_trades(trades):
    """Save trades to file"""
    try:
        with open(TRADES_FILE, 'w') as f:
            json.dump(trades, f, indent=2)
    except Exception as e:
        print(f"Error saving trades: {e}")

def add_trade(trade):
    """Add new trade to history"""
    trades = load_trades()
    
    # Check if trade already exists
    existing_ids = [t['id'] for t in trades]
    if trade['id'] not in existing_ids:
        trades.append(trade)
        save_trades(trades)
        return True
    return False

def update_trade(trade_id, updates):
    """Update existing trade"""
    trades = load_trades()
    for i, trade in enumerate(trades):
        if trade['id'] == trade_id:
            trades[i].update(updates)
            save_trades(trades)
            return True
    return False

def rescan_trade(trade):
    """Rescan a trade to check if target/SL hit"""
    fyers = get_fyers_client()
    if not fyers:
        return trade
    
    symbol = trade['symbol_full']
    entry_price = trade['entry_price']
    target_price = trade['target_price']
    stoploss_price = trade['stoploss_price']
    signal = trade['signal']
    pattern_time = datetime.strptime(trade['pattern_time'], '%Y-%m-%d %H:%M')
    
    # Get data from pattern time to now
    end_date = datetime.now()
    start_date = pattern_time - timedelta(hours=1)
    
    try:
        df = get_historical_data(fyers, symbol, '5', start_date, end_date)
        
        if df is None or len(df) == 0:
            return trade
        
        # Filter data after pattern time
        df = df[df.index > pattern_time]
        
        if len(df) == 0:
            return trade
        
        current_price = get_current_price(fyers, symbol)
        if current_price is None:
            current_price = df.iloc[-1]['close']
        
        trade['current_price'] = round(current_price, 2)
        
        # Check if entry was triggered
        entry_triggered = False
        for idx, row in df.iterrows():
            if signal == 'BUY':
                if row['low'] <= entry_price <= row['high']:
                    entry_triggered = True
                    break
            else:
                if row['low'] <= entry_price <= row['high']:
                    entry_triggered = True
                    break
        
        if not entry_triggered:
            # Check direction
            if current_price > entry_price:
                trade['status'] = 'ENTRY_MISSED_UP'
            else:
                trade['status'] = 'ENTRY_MISSED_DOWN'
            trade['result'] = 'MISSED'
            return trade
        
        # Entry was triggered, check for target/SL
        for idx, row in df.iterrows():
            if signal == 'BUY':
                # Check SL first
                if row['low'] <= stoploss_price:
                    trade['status'] = 'CLOSED'
                    trade['result'] = 'STOPLOSS'
                    trade['exit_price'] = round(stoploss_price, 2)
                    trade['exit_time'] = idx.strftime('%Y-%m-%d %H:%M')
                    trade['pnl_points'] = round(stoploss_price - entry_price, 2)
                    trade['pnl_percent'] = round((stoploss_price - entry_price) / entry_price * 100, 4)
                    return trade
                # Check Target
                if row['high'] >= target_price:
                    trade['status'] = 'CLOSED'
                    trade['result'] = 'TARGET'
                    trade['exit_price'] = round(target_price, 2)
                    trade['exit_time'] = idx.strftime('%Y-%m-%d %H:%M')
                    trade['pnl_points'] = round(target_price - entry_price, 2)
                    trade['pnl_percent'] = round((target_price - entry_price) / entry_price * 100, 4)
                    return trade
            else:  # SELL
                # Check SL first
                if row['high'] >= stoploss_price:
                    trade['status'] = 'CLOSED'
                    trade['result'] = 'STOPLOSS'
                    trade['exit_price'] = round(stoploss_price, 2)
                    trade['exit_time'] = idx.strftime('%Y-%m-%d %H:%M')
                    trade['pnl_points'] = round(entry_price - stoploss_price, 2)
                    trade['pnl_percent'] = round((entry_price - stoploss_price) / entry_price * 100, 4)
                    return trade
                # Check Target
                if row['low'] <= target_price:
                    trade['status'] = 'CLOSED'
                    trade['result'] = 'TARGET'
                    trade['exit_price'] = round(target_price, 2)
                    trade['exit_time'] = idx.strftime('%Y-%m-%d %H:%M')
                    trade['pnl_points'] = round(entry_price - target_price, 2)
                    trade['pnl_percent'] = round((entry_price - target_price) / entry_price * 100, 4)
                    return trade
        
        # Neither target nor SL hit - check direction
        trade['status'] = 'ACTIVE'
        if signal == 'BUY':
            if current_price > entry_price:
                trade['result'] = 'IN_PROFIT'
                trade['pnl_points'] = round(current_price - entry_price, 2)
            else:
                trade['result'] = 'IN_LOSS'
                trade['pnl_points'] = round(current_price - entry_price, 2)
        else:
            if current_price < entry_price:
                trade['result'] = 'IN_PROFIT'
                trade['pnl_points'] = round(entry_price - current_price, 2)
            else:
                trade['result'] = 'IN_LOSS'
                trade['pnl_points'] = round(entry_price - current_price, 2)
        
        trade['pnl_percent'] = round(trade['pnl_points'] / entry_price * 100, 4)
        
    except Exception as e:
        print(f"Error rescanning trade: {e}")
    
    return trade

# =============================================================================
# ROUTES
# =============================================================================
@app.route('/')
def index():
    """Main scanner page"""
    return render_template('index.html')

@app.route('/history')
def history():
    """Trade history page"""
    return render_template('history.html')

@app.route('/api/scan', methods=['GET'])
def api_scan():
    """API endpoint to scan for patterns"""
    try:
        patterns = scan_patterns()
        
        # Add new patterns to history
        for pattern in patterns:
            add_trade(pattern)
        
        return jsonify({
            'success': True,
            'patterns': patterns,
            'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/trades', methods=['GET'])
def api_trades():
    """Get all trades"""
    try:
        trades = load_trades()
        return jsonify({
            'success': True,
            'trades': trades
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/rescan', methods=['POST'])
def api_rescan():
    """Rescan all active trades"""
    try:
        trades = load_trades()
        updated_trades = []
        
        for trade in trades:
            if trade['status'] == 'ACTIVE' or trade['result'] in ['IN_PROFIT', 'IN_LOSS', None]:
                trade = rescan_trade(trade)
            updated_trades.append(trade)
        
        save_trades(updated_trades)
        
        return jsonify({
            'success': True,
            'trades': updated_trades,
            'rescan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/rescan/<trade_id>', methods=['POST'])
def api_rescan_single(trade_id):
    """Rescan a single trade"""
    try:
        trades = load_trades()
        
        for i, trade in enumerate(trades):
            if trade['id'] == trade_id:
                trades[i] = rescan_trade(trade)
                save_trades(trades)
                return jsonify({
                    'success': True,
                    'trade': trades[i]
                })
        
        return jsonify({
            'success': False,
            'error': 'Trade not found'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/delete/<trade_id>', methods=['DELETE'])
def api_delete_trade(trade_id):
    """Delete a trade"""
    try:
        trades = load_trades()
        trades = [t for t in trades if t['id'] != trade_id]
        save_trades(trades)
        
        return jsonify({
            'success': True
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/clear', methods=['DELETE'])
def api_clear_trades():
    """Clear all trades"""
    try:
        save_trades([])
        return jsonify({
            'success': True
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/stats', methods=['GET'])
def api_stats():
    """Get trading statistics"""
    try:
        trades = load_trades()
        
        total = len(trades)
        closed = [t for t in trades if t['status'] == 'CLOSED']
        active = [t for t in trades if t['status'] == 'ACTIVE']
        
        targets = [t for t in closed if t['result'] == 'TARGET']
        stoplosses = [t for t in closed if t['result'] == 'STOPLOSS']
        
        total_pnl = sum([t['pnl_points'] or 0 for t in closed])
        
        win_rate = len(targets) / len(closed) * 100 if closed else 0
        
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
        return jsonify({
            'success': False,
            'error': str(e)
        })

# =============================================================================
# MAIN
# =============================================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
