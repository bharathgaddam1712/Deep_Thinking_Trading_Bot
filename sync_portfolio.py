import json
import os
from roostoo_client import RoostooClient
from local_broker import LocalBroker
from dotenv import load_dotenv

def sync_roostoo_to_local():
    """
    Fetches real balance and holdings from Roostoo API 
    and updates the local virtual_portfolio.json.
    """
    load_dotenv()
    print("[SYNC] SYNCING ROOSTOO PLATFORM -> LOCAL TERMINAL...")
    
    client = RoostooClient()
    balance_res = client.get_balance()
    
    if not balance_res.get("Success"):
        print(f"[ERROR] FAILED TO FETCH BALANCE: {balance_res.get('ErrMsg')}")
        return

    # Extract Balances
    wallet = balance_res.get("SpotWallet", {})
    real_usd = wallet.get("USD", {}).get("Free", 0)
    
    # Extract Holdings (Coins)
    holdings = {}
    for coin, data in wallet.items():
        qty = data.get("Free", 0)
        if qty > 0 and coin not in ["USD", "", "VIRTUAL"]:
            # Note: We don't have accurate avg_price from Roostoo API, so we try to get current price as entry for now
            symbol = f"{coin}/USD"
            holdings[symbol] = {
                "qty": qty,
                "avg_price": 0.0 # Will be updated below
            }

    # Fetch current prices for cost-basis initialization if missing
    broker = LocalBroker()
    for symbol in holdings:
        price = broker.get_price(symbol)
        holdings[symbol]["avg_price"] = price if price else 0.0

    # Prepare new portfolio data
    new_data = {
        "cash": real_usd,
        "holdings": holdings,
        "history": [] # History can't be fully reconstructed but new trades will be logged
    }
    
    # Overwrite local portfolio
    with open("virtual_portfolio.json", "w") as f:
        json.dump(new_data, f, indent=4)
    
    print(f"[OK] SYNC COMPLETE!")
    print(f"[CASH] REAL USD BALANCE: ${real_usd}")
    print(f"[HOLDINGS] ACTIVE HOLDINGS: {list(holdings.keys())}")

if __name__ == "__main__":
    sync_roostoo_to_local()
