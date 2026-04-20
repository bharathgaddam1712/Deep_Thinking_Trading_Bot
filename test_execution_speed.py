import requests
import time
import json

def test_manual_execution_speed():
    """
    Simulates a manual BUY order from the frontend
    and measures the exact system response time.
    """
    url = "http://127.0.0.1:8000/api/execute"
    payload = {
        "pair": "ADA/USD",
        "side": "BUY",
        "quantity": 5.0
    }
    
    print("[TEST] SENDING MANUAL BUY ORDER FOR 5 ADA...")
    
    start_time = time.time()
    try:
        response = requests.post(url, json=payload, timeout=15)
        end_time = time.time()
        
        latency = (end_time - start_time) * 1000 # in ms
        data = response.json()
        
        print("\n" + "="*40)
        print(f"RESULTS:")
        print(f"Status: {data.get('status').upper()}")
        print(f"Response: {data.get('message')}")
        print(f"Latency: {latency:.2f} ms")
        print("="*40 + "\n")
        
        if latency < 500:
            print("[SPEED] STATUS: HIGH SPEED (ZERO LATENCY FEEL)")
        else:
            print("[NORMAL] STATUS: NORMAL (NETWORK LATENCY)")
            
    except Exception as e:
        print(f"[FAIL] TEST FAILED: {e}")

if __name__ == "__main__":
    # Give the server a moment to warm up
    time.sleep(2)
    test_manual_execution_speed()
