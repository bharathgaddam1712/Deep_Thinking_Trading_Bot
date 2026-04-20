import time
from roostoo_client import RoostooClient

class RoostooManager:
    """
    Data Fetching & Trade Validation Module.
    Implements 2s polling and position limit enforcement.
    """
    def __init__(self):
        self.client = RoostooClient()
        self.wallet_balance = 0.0
        self.open_trades = {}
        
    def fetch_data(self):
        """
        Parses get_balance() response.
        Updates wallet_balance and open_trades based on specific filtering logic.
        """
        data = self.client.get_balance()
        
        if not data.get("Success"):
            print(f"[ERROR] Fetch failed: {data.get('ErrMsg')}")
            return
        
        spot_wallet = data.get('SpotWallet', {})
        
        # 1. Update global wallet_balance specifically from USD Free
        self.wallet_balance = spot_wallet.get('USD', {}).get('Free', 0.0)
        
        # 2. Filtering Logic: Exclude 'USD' and '' keys, only include Free > 0
        self.open_trades = {
            coin: info for coin, info in spot_wallet.items() 
            if coin not in ['USD', ''] and info.get('Free', 0) > 0
        }

        print(self.open_trades)
        
        print(f"[SYNC] Balance: ${self.wallet_balance} | Open Trades: {len(self.open_trades)}")

    def buy_coin(self, pair, quantity):
        """
        Safety-wrapped trade execution.
        Enforces a maximum of 5 concurrent open positions.
        """
        # Trade Validation: Prevent execution if limit (5) reached
        if len(self.open_trades) >= 5:
            print(f"[REJECTED] Cannot buy {pair}. Position limit (5) reached.")
            return {"Success": False, "ErrMsg": "Position limit reached"}
            
        print(f"[EXECUTING] Buying {pair} Qty: {quantity}...")
        return self.client.place_order(pair, "BUY", quantity)

    def monitoring_loop(self):
        """Infinite loop refreshing data every 2 seconds."""
        print("[STARTING] Roostoo Monitoring Loop (2s Interval)")
        while True:
            try:
                self.fetch_data()
            except Exception as e:
                print(f"[LOOP ERROR] {e}")
            time.sleep(2)

if __name__ == "__main__":
    # Self-test implementation
    manager = RoostooManager()
    
    # 1. Start the monitoring loop (Blocking)
    # Note: In production you might run this in a thread
    manager.monitoring_loop()
