import ccxt
import pandas as pd
import yfinance as yf
import time
import os
from datetime import datetime, timedelta

class MarketDataProvider:
    def __init__(self, primary_exchange='binance', secondary_exchange='mexc'):
        # Initialize primary exchange (Binance)
        self.primary = getattr(ccxt, primary_exchange)({
            'enableRateLimit': True,
            'apiKey': os.getenv('BINANCE_API_KEY', ''),
            'secret': os.getenv('BINANCE_SECRET_KEY', ''),
        })
        
        # Initialize secondary for broader coverage (MEXC)
        self.secondary = getattr(ccxt, secondary_exchange)({
            'enableRateLimit': True,
        })
        
    def fetch_ohlcv_to_df(self, symbol, timeframe='1d', limit=100):
        """
        Fetches OHLCV data. 
        Auto-detects Crypto (COIN/USD) vs Stocks (AAPL) and uses CCXT or yfinance.
        """
        if "/" in symbol:
            # CRYPTO PATH (CCXT)
            return self._fetch_crypto_ohlcv(symbol, timeframe, limit)
        else:
            # STOCK PATH (yfinance)
            return self._fetch_stock_ohlcv(symbol, timeframe, limit)

    def _fetch_crypto_ohlcv(self, symbol, timeframe, limit):
        exchange = self.primary
        try:
            coin = symbol.split("/")[0]
            ccxt_symbol = f"{coin}/USDT"
            ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
        except Exception:
            try:
                exchange = self.secondary
                coin = symbol.split("/")[0]
                ccxt_symbol = f"{coin}/USDT"
                ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            except Exception as e:
                print(f"Error fetching {symbol} from CCXT: {e}")
                return pd.DataFrame()

        if not ohlcv: return pd.DataFrame()
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    def _fetch_stock_ohlcv(self, symbol, timeframe, limit):
        """Fetches stock data using yfinance."""
        try:
            # Map timeframe (ccxt format) to yfinance format
            yf_intervals = {"1m": "1m", "5m": "5m", "1h": "1h", "1d": "1d"}
            interval = yf_intervals.get(timeframe, "1d")
            
            # yfinance doesn't take 'limit', it takes 'period' or 'start/end'
            # 100 days for 1d, 100 hours for 1h etc.
            if interval == "1d": period = f"{limit}d"
            elif interval == "1h": period = "7d" # yfinance limit for hourly
            else: period = "1d"

            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            
            if df.empty: return pd.DataFrame()
            
            # Standardize columns to lowercase for stockstats compatibility
            df.columns = [c.lower() for c in df.columns]
            return df
        except Exception as e:
            print(f"Error fetching {symbol} from yfinance: {e}")
            return pd.DataFrame()

    def get_latest_momentum(self, symbols):
        """
        Calculates momentum for a list of symbols. 
        Handles hybrid list of Crypto and Stocks.
        """
        crypto_symbols = [s for s in symbols if "/" in s]
        stock_symbols = [s for s in symbols if "/" not in s]
        
        momentum_data = []
        
        # 1. Crypto Momentum (Batch via CCXT)
        if crypto_symbols:
            try:
                tickers = self.primary.fetch_tickers()
                for sym in crypto_symbols:
                    coin = sym.split("/")[0]
                    ccxt_sym = f"{coin}/USDT"
                    if ccxt_sym in tickers:
                        t = tickers[ccxt_sym]
                        price_change = t.get('percentage', 0)
                        volume_24h = t.get('quoteVolume', 0) 
                        score = (price_change * 0.7) + (min(volume_24h / 1e6, 100) * 0.3)
                        momentum_data.append({"symbol": sym, "score": score, "type": "crypto"})
            except Exception as e:
                print(f"Error in CCXT crypto momentum: {e}")

        # 2. Stock Momentum (Individual via yfinance)
        for sym in stock_symbols:
            try:
                ticker = yf.Ticker(sym)
                info = ticker.history(period="2d")
                if len(info) >= 2:
                    change = ((info['Close'].iloc[-1] - info['Close'].iloc[-2]) / info['Close'].iloc[-2]) * 100
                    volume = info['Volume'].iloc[-1]
                    # Simplified score for stocks
                    score = (change * 0.8) + (min(volume / 1e7, 10) * 0.2)
                    momentum_data.append({"symbol": sym, "score": score, "type": "stock"})
            except Exception:
                pass
                
        return sorted(momentum_data, key=lambda x: x['score'], reverse=True)

class CryptoDataProvider(MarketDataProvider):
    """Backwards compatibility for existing imports."""
    pass

if __name__ == "__main__":
    provider = MarketDataProvider()
    print("Testing Stock Fetch (AAPL):")
    df = provider.fetch_ohlcv_to_df("AAPL", limit=5)
    print(df.tail())
    
    print("\nTesting Hybrid Momentum:")
    momentum = provider.get_latest_momentum(["BTC/USD", "NVDA", "ETH/USD", "AAPL"])
    for m in momentum:
        print(f"{m['symbol']} ({m['type']}): {m['score']:.2f}")
