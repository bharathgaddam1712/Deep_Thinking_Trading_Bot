import json
import os

# Filtered "Popular" Tickers (available on Binance/MEXC)
# Removed niche/mock tickers to avoid rate limiting and data issues.
POPULAR_SYMBOLS = [
    "AAVE/USD", "ADA/USD", "APT/USD", "ARB/USD", "AVAX/USD", "BNB/USD", "BONK/USD", 
    "BTC/USD", "CAKE/USD", "CFX/USD", "CRV/USD", "DOGE/USD", "DOT/USD", "EIGEN/USD", 
    "ENA/USD", "ETH/USD", "FET/USD", "FIL/USD", "FLOKI/USD", "HBAR/USD", "ICP/USD", 
    "LINK/USD", "LISTA/USD", "LTC/USD", "NEAR/USD", "OMNI/USD", "ONDO/USD", "PAXG/USD", 
    "PENDLE/USD", "PEPE/USD", "POL/USD", "S/USD", "SEI/USD", "SHIB/USD", "SOL/USD", 
    "SUI/USD", "TAO/USD", "TON/USD", "TRX/USD", "UNI/USD", "WIF/USD", "WLD/USD", 
    "XLM/USD", "XRP/USD", "ZEC/USD", "ZEN/USD"
]

ROOSTOO_SYMBOLS = POPULAR_SYMBOLS

def get_yfinance_ticker(roostoo_symbol):
    """Converts Roostoo symbol (COIN/USD) to yfinance format (COIN-USD)"""
    return roostoo_symbol.replace("/", "-")

def get_ccxt_symbol(roostoo_symbol):
    """Converts Roostoo symbol (COIN/USD) to CCXT standard (COIN/USDT)"""
    # Most tokens use USDT as the primary pair on CEXs
    coin = roostoo_symbol.split("/")[0]
    if coin in ["BTC", "ETH", "USDC"]:
        return f"{coin}/USDT"
    return f"{coin}/USDT"

def load_managed_symbols():
    return ROOSTOO_SYMBOLS

if __name__ == "__main__":
    print(f"Loaded {len(ROOSTOO_SYMBOLS)} popular symbols for analysis.")
    print(f"Example: {ROOSTOO_SYMBOLS[0]} -> {get_ccxt_symbol(ROOSTOO_SYMBOLS[0])}")
