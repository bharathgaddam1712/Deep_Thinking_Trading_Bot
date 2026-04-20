import os
from local_broker import LocalBroker

from config_manager import is_crypto
import ccxt

class ExecutionManager:
    def __init__(self):
        # Local Virtual Broker (Zero-KYC Stock Trading)
        self.local_broker = LocalBroker()
        print("Virtual Local Broker initialized (Zero-KYC mode)")

        # CCXT Setup (Still useful for Crypto data/execution)
        self.crypto_exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY', ''),
            'secret': os.getenv('BINANCE_SECRET_KEY', ''),
            'enableRateLimit': True,
        })
        
        # Position Sizing
        self.default_stock_position = 5000.0 # Spend $5000 per BUY

    def execute_signals(self, results):
        """
        Executes a list of signals (BUY/SELL/HOLD).
        results format: [{'ticker': 'AAPL', 'signal': 'BUY', 'trader_plan': '...'}]
        """
        print(f"\n--- {datetime.now().strftime('%H:%M:%S')} | STARTING EXECUTION ENGINE ---")
        
        for res in results:
            ticker = res['ticker']
            signal = res['signal']
            
            if signal == "HOLD":
                continue

            if is_crypto(ticker):
                self._execute_crypto(ticker, signal)
            else:
                self._execute_stock(ticker, signal)

    def _execute_stock(self, ticker, signal):
        try:
            if signal == "BUY":
                print(f"Virtual Broker: Executing BUY for {ticker}...")
                res = self.local_broker.buy(ticker, self.default_stock_position)
            else: # SELL
                print(f"Virtual Broker: Executing SELL for {ticker}...")
                res = self.local_broker.sell(ticker)

            if res["success"]:
                print(f"Success: {signal} {ticker} at {res['price']:.2f}")
                summary = self.local_broker.get_summary()
                print(f"Portfolio Status: Net Worth ${summary['net_worth']:,.2f} | Cash ${summary['cash']:,.2f}")
            else:
                print(f"Virtual Broker Error for {ticker}: {res['error']}")
        except Exception as e:
            print(f"Execution Error for {ticker}: {e}")

    def _execute_crypto(self, ticker, signal):
        try:
            coin = ticker.split("/")[0]
            ccxt_sym = f"{coin}/USDT"
            side = 'buy' if signal == "BUY" else 'sell'
            
            print(f"CCXT: Executing {side.upper()} order for {ccxt_sym}...")
            # For real trades, you'd want to handle position sizing carefully
            # self.crypto_exchange.create_market_order(ccxt_sym, side, amount=...)
            print(f"Simulated CCXT execution for {ccxt_sym} (Keys: {self.crypto_exchange.apiKey[:5]}...)")
        except Exception as e:
            print(f"CCXT Error for {ticker}: {e}")

from datetime import datetime
