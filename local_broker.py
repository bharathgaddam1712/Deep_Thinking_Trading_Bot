import json
import os
import yfinance as yf
from datetime import datetime

class LocalBroker:
    def __init__(self, portfolio_file="virtual_portfolio.json", initial_cash=100000.0):
        self.portfolio_file = portfolio_file
        self.initial_cash = initial_cash
        self.data = self._load_portfolio()
        
        # CCXT for Crypto Prices (Binance)
        import ccxt
        from roostoo_client import RoostooClient
        
        # 1. Public Broker (unauthenticated) for high-speed price fetching
        self.crypto_public = ccxt.binance({
            'enableRateLimit': True,
        })
        
        # 2. Private Broker (authenticated) for execution mirroring
        self.crypto_private = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY', ''),
            'secret': os.getenv('BINANCE_SECRET_KEY', ''),
            'enableRateLimit': True,
        })
        
        self.roostoo = RoostooClient()
        self.ticker_cache = {} # symbol: ticker_obj
        
        # Auto-sync with Roostoo if keys are present
        if self.roostoo.api_key:
            self._sync_with_roostoo()

    def _sync_with_roostoo(self):
        """Internal method to align local state with real Roostoo state."""
        try:
            res = self.roostoo.get_balance()
            if res.get("Success"):
                wallet = res.get("SpotWallet", {})
                self.data["cash"] = wallet.get("USD", {}).get("Free", 0)
                # Note: We don't overwrite holdings here to preserve local avg_price tracking,
                # but we ensure the USD balance is 100% accurate.
                self._save_portfolio(self.data)
        except Exception:
            pass

    def _load_portfolio(self):
        if os.path.exists(self.portfolio_file):
            try:
                with open(self.portfolio_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        
        # Default starting state
        default_state = {
            "cash": self.initial_cash,
            "holdings": {}, # symbol: {"qty": 0, "avg_price": 0.0}
            "history": []
        }
        self._save_portfolio(default_state)
        return default_state

    def _save_portfolio(self, data):
        with open(self.portfolio_file, "w") as f:
            json.dump(data, f, indent=4)

    def get_price(self, symbol):
        """Fetches latest price for execution. Uses CCXT for Crypto, yfinance for Stocks."""
        try:
            # 1. Check if it's a crypto pair (COIN/USD)
            if "/" in symbol:
                coin = symbol.split("/")[0]
                binance_sym = f"{coin}/USDT"
                
                # Use public instance for price to avoid credential issues
                try:
                    ticker_data = self.crypto_public.fetch_ticker(binance_sym)
                except Exception as api_err:
                    print(f"LocalBroker: API Ticker Error for {binance_sym}: {api_err}")
                    # Fallback to cache if possible
                    return self.ticker_cache.get(binance_sym, {}).get('last', 0.0)
                
                self.ticker_cache[binance_sym] = ticker_data
                return ticker_data['last']
            
            # 2. Fallback to yfinance for Stocks
            if symbol not in self.ticker_cache or not isinstance(self.ticker_cache[symbol], yf.Ticker):
                self.ticker_cache[symbol] = yf.Ticker(symbol)
            
            ticker = self.ticker_cache[symbol]
            price = ticker.info.get('regularMarketPrice') or ticker.info.get('currentPrice')
            if price is None:
                hist = ticker.history(period="1d")
                if not hist.empty:
                    price = hist['Close'].iloc[-1]
            return price
        except Exception as e:
            print(f"LocalBroker: Error fetching price for {symbol}: {e}")
            return None

    def buy(self, symbol, amount_usd):
        """Simulates buying shares worth a specific USD amount."""
        price = self.get_price(symbol)
        if price is None or price <= 0:
            return {"success": False, "error": f"Invalid price for {symbol}"}

        qty = amount_usd / price
        if self.data["cash"] < amount_usd:
            return {"success": False, "error": "Insufficient virtual cash"}

        # Update Cash
        self.data["cash"] -= amount_usd
        
        # Update Holdings
        holdings = self.data["holdings"]
        if symbol in holdings:
            current_qty = holdings[symbol]["qty"]
            current_avg = holdings[symbol]["avg_price"]
            new_qty = current_qty + qty
            new_avg = ((current_qty * current_avg) + (qty * price)) / new_qty
            holdings[symbol] = {"qty": new_qty, "avg_price": new_avg}
        else:
            holdings[symbol] = {"qty": qty, "avg_price": price}

        self.data["history"].append({
            "timestamp": datetime.now().isoformat(),
            "side": "BUY",
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "amount_usd": amount_usd
        })
        
        # Mirror to Roostoo API
        self.roostoo.place_order(symbol, "BUY", qty)
        
        self._save_portfolio(self.data)
        return {"success": True, "qty": qty, "price": price}

    def sell(self, symbol, qty_to_sell=None):
        """Simulates selling holdings."""
        if symbol not in self.data["holdings"]:
            return {"success": False, "error": f"No holdings for {symbol}"}

        price = self.get_price(symbol)
        if price is None or price <= 0:
            return {"success": False, "error": f"Invalid price for {symbol}"}

        current_holdings = self.data["holdings"][symbol]
        qty = qty_to_sell if qty_to_sell else current_holdings["qty"]
        
        if qty > current_holdings["qty"]:
            return {"success": False, "error": "Insufficient shares to sell"}

        amount_usd = qty * price
        self.data["cash"] += amount_usd
        
        if qty == current_holdings["qty"]:
            del self.data["holdings"][symbol]
        else:
            current_holdings["qty"] -= qty

        self.data["history"].append({
            "timestamp": datetime.now().isoformat(),
            "side": "SELL",
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "amount_usd": amount_usd
        })
        
        # Mirror to Roostoo API
        self.roostoo.place_order(symbol, "SELL", qty)
        
        self._save_portfolio(self.data)
        return {"success": True, "qty": qty, "price": price, "amount_usd": amount_usd}

    def get_summary(self):
        """Calculates total net worth."""
        total_holdings_value = 0
        for sym, data in self.data["holdings"].items():
            price = self.get_price(sym) or data["avg_price"]
            total_holdings_value += data["qty"] * price
            
        return {
            "cash": self.data["cash"],
            "holdings_value": total_holdings_value,
            "net_worth": self.data["cash"] + total_holdings_value,
            "holdings_count": len(self.data["holdings"])
        }

if __name__ == "__main__":
    # Internal Test
    broker = LocalBroker()
    print("Initial State:", broker.get_summary())
    # Test Buy
    res = broker.buy("AAPL", 5000)
    print("Buy Result:", res)
    print("Post-Buy State:", broker.get_summary())
