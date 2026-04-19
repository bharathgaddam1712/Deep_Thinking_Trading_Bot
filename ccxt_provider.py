import ccxt
import pandas as pd
import time
import os
from datetime import datetime, timedelta

class CryptoDataProvider:
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
        
    def fetch_ohlcv_to_df(self, symbol, timeframe='1d', limit=30):
        """Fetches OHLCV data and returns it as a formatted Pandas DataFrame."""
        exchange = self.primary
        
        # Try primary exchange first
        try:
            # We assume symbols passed are in Roostoo format (COIN/USD)
            # We map to CCXT format (COIN/USDT)
            coin = symbol.split("/")[0]
            ccxt_symbol = f"{coin}/USDT"
            
            # Fetch data
            ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
        except Exception:
            # Fallback to secondary (MEXC)
            try:
                exchange = self.secondary
                coin = symbol.split("/")[0]
                ccxt_symbol = f"{coin}/USDT"
                ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            except Exception as e:
                print(f"Error fetching {symbol} from CCXT: {e}")
                return pd.DataFrame()

        if not ohlcv:
            return pd.DataFrame()

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    def get_latest_momentum(self, symbols):
        """Fetches tickers for a list of symbols and ranks them by 24h performance."""
        print(f"CCXT: Scanning {len(symbols)} tickers for momentum...")
        momentum_data = []
        
        try:
            # Use fetch_tickers to get all data in one request (extremely fast)
            tickers = self.primary.fetch_tickers()
            
            for sym in symbols:
                coin = sym.split("/")[0]
                ccxt_sym = f"{coin}/USDT"
                
                if ccxt_sym in tickers:
                    t = tickers[ccxt_sym]
                    # ROC: Price Change %
                    # Volume: 24h volume
                    price_change = t.get('percentage', 0)
                    volume_24h = t.get('quoteVolume', 0) 
                    
                    # We'll calculate a simple score similar to before
                    # (Volume Spike is harder from just a ticker, but we'll use 24h total vol)
                    score = (price_change * 0.7) + (min(volume_24h / 1e6, 100) * 0.3)
                    
                    momentum_data.append({
                        "roostoo_symbol": sym,
                        "price_change": price_change,
                        "volume_24h": volume_24h,
                        "score": score
                    })
            
            # Sort by score
            return sorted(momentum_data, key=lambda x: x['score'], reverse=True)
            
        except Exception as e:
            print(f"Error in CCXT ticker scan: {e}")
            return []

if __name__ == "__main__":
    provider = CryptoDataProvider()
    # Test fetch
    df = provider.fetch_ohlcv_to_df("BTC/USD", timeframe='1h', limit=5)
    print("BTC Hourly Data (CCXT):")
    print(df)
    
    # Test momentum
    momentum = provider.get_latest_momentum(["BTC/USD", "ETH/USD", "SOL/USD"])
    print("\nMomentum Test:")
    for m in momentum:
        print(f"{m['roostoo_symbol']}: Score {m['score']:.2f}")
