import json
import time
import os
import random
from local_broker import LocalBroker
from datetime import datetime

class AutoExecutor:
    """
    The Tactical Automation Engine. 
    Monitors signals and executes mirror trades on Roostoo platform.
    """
    def __init__(self, bias_file="trading_bias.json", poll_interval=10):
        self.bias_file = bias_file
        self.poll_interval = poll_interval
        self.broker = LocalBroker()
        self.last_processed = {} # asset: timestamp

    def run(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] TACTICAL ENGINE: INITIALIZED")
        print(f"SETTINGS: Max Positions: 5 | Sizing: $1,200 - $2,000")
        
        while True:
            try:
                self.process_cycles()
            except Exception as e:
                print(f"Error in Tactical Loop: {e}")
            
            time.sleep(self.poll_interval)

    def process_cycles(self):
        if not os.path.exists(self.bias_file):
            return

        with open(self.bias_file, "r") as f:
            biases = json.load(f)

        portfolio = self.broker.data
        holdings = portfolio.get("holdings", {})
        open_positions_count = len(holdings)

        for asset, data in biases.items():
            signal = data.get("signal")
            timestamp = data.get("timestamp")
            
            # Check if we've already processed this specific signal timestamp
            if self.last_processed.get(asset) == timestamp:
                continue

            # --- AUTO SELL LOGIC ---
            if signal == "SELL" and asset in holdings:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] TACTICAL: SELL SIGNAL DETECTED FOR {asset}. EXITING POSITION...")
                res = self.broker.sell(asset)
                if res.get("success"):
                    print(f"SUCCESS: Sold {asset} | Profit/Loss calculation pending in UI.")
                else:
                    print(f"FAILED: Could not sell {asset}: {res.get('error')}")
                self.last_processed[asset] = timestamp

            # --- AUTO BUY LOGIC ---
            elif signal == "BUY" and asset not in holdings:
                if open_positions_count >= 5:
                    # Skip if we already have 5 positions
                    continue
                
                # Sizing: $1200 - $2000
                amount = round(random.uniform(1200, 2000), 2)
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] TACTICAL: BUY SIGNAL DETECTED FOR {asset}. EXECUTING ORDER (${amount})...")
                res = self.broker.buy(asset, amount)
                
                if res.get("success"):
                    print(f"SUCCESS: Bought {asset} | Amount: ${amount} | Qty: {res.get('qty')}")
                    open_positions_count += 1
                else:
                    print(f"FAILED: Could not buy {asset}: {res.get('error')}")
                
                self.last_processed[asset] = timestamp
            
            # Update last processed for non-actionable as well to avoid re-poking
            else:
                self.last_processed[asset] = timestamp

if __name__ == "__main__":
    executor = AutoExecutor()
    executor.run()
