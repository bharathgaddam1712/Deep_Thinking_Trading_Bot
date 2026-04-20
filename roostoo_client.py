import hmac
import hashlib
import time
import requests
import json
import os
from dotenv import load_dotenv

class RoostooClient:
    """
    Python client for the Roostoo Mock Trading API.
    Based on the Roostoo API documentation and Rust implementation.
    """
    def __init__(self, api_key=None, secret_key=None):
        load_dotenv()
        self.api_key = api_key or os.getenv("API_KEY")
        self.secret_key = secret_key or os.getenv("SECRET_KEY")
        self.base_url = "https://mock-api.roostoo.com"
        
        if not self.api_key or not self.secret_key:
            print("RoostooClient: Warning - API_KEY or SECRET_KEY missing in .env")

    def _generate_signature(self, params):
        """
        Generates HMAC-SHA256 signature for Roostoo API.
        1. Sort parameters lexicographically by key.
        2. Create query string.
        3. HMAC with secret key.
        """
        # Lexicographical sort
        sorted_keys = sorted(params.keys())
        query_parts = []
        for k in sorted_keys:
            query_parts.append(f"{k}={params[k]}")
        
        query_string = "&".join(query_parts)
        
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature, query_string

    def get_balance(self):
        """Fetches account balance (mock funds)."""
        if not self.api_key: return {"success": False, "error": "No API Key"}
        
        endpoint = "/v3/balance"
        params = {
            "timestamp": int(time.time() * 1000)
        }
        
        signature, query_string = self._generate_signature(params)
        
        headers = {
            "RST-API-KEY": self.api_key,
            "MSG-SIGNATURE": signature
        }
        
        try:
            url = f"{self.base_url}{endpoint}?{query_string}"
            response = requests.get(url, headers=headers, timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def place_order(self, pair, side, quantity, order_type="MARKET"):
        """Places a mock trade on the Roostoo platform."""
        if not self.api_key: return {"success": False, "error": "No API Key"}
        
        endpoint = "/v3/place_order"
        params = {
            "pair": pair,
            "side": side.upper(),
            "quantity": str(quantity),
            "type": order_type.upper(),
            "timestamp": int(time.time() * 1000)
        }
        
        signature, _ = self._generate_signature(params)
        
        headers = {
            "RST-API-KEY": self.api_key,
            "MSG-SIGNATURE": signature,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            url = f"{self.base_url}{endpoint}"
            # POST parameters should be sent as form-encoded for this specific API
            response = requests.post(url, headers=headers, data=params, timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_exchange_info(self):
        """Gets trading pair metadata (precision, mini order, etc)."""
        endpoint = "/v3/exchangeInfo"
        try:
            response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

if __name__ == "__main__":
    client = RoostooClient()
    print("Testing Roostoo Connectivity...")
    balance = client.get_balance()
    print("Balance Response:", json.dumps(balance, indent=2))
