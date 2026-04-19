import time
from config_manager import ROOSTOO_SYMBOLS
from ccxt_provider import CryptoDataProvider

# Initialize the global CCXT provider
_provider = CryptoDataProvider()

def get_momentum_scores(symbols, period="1d"):
    """
    Ranks symbols by performance using the High-Speed CCXT provider.
    - No more yfinance rate limits.
    - Single request for all 46 tickers.
    """
    momentum_results = _provider.get_latest_momentum(symbols)
    return momentum_results

def get_top_10_tickers():
    all_scores = get_momentum_scores(ROOSTOO_SYMBOLS)
    if not all_scores:
        print("Warning: No momentum data fetched from CCXT. Falling back to default selection.")
        return ROOSTOO_SYMBOLS[:10]
        
    top_10 = [s['roostoo_symbol'] for s in all_scores[:10]]
    return top_10

if __name__ == "__main__":
    top_10 = get_top_10_tickers()
    print("\nTop 10 Momentum Leaders (CCXT):")
    for i, sym in enumerate(top_10, 1):
        print(f"{i}. {sym}")
