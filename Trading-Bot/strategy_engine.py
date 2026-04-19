import time
import zmq
import sys
import os
import json

# Add proto directory to path to allow importing compiled pb2
sys.path.append(os.path.join(os.path.dirname(__file__), 'proto'))
import trading_pb2

from logic.indicators import SMACrossoverStrategy

class BiasManager:
    """Loads and manages high-level analyst signals from the Brain."""
    def __init__(self, bias_file="../trading_bias.json"):
        # The file is in the root, and this script is in Trading-Bot/
        self.bias_file = bias_file
        self.biases = {}
        self.last_load = 0
        self.load_interval = 30 # Check for new signals every 30 seconds

    def load_biases(self):
        now = time.time()
        if now - self.last_load >= self.load_interval:
            try:
                if os.path.exists(self.bias_file):
                    with open(self.bias_file, "r") as f:
                        self.biases = json.load(f)
                    # print(f"BiasManager: Loaded {len(self.biases)} analyst signals.")
                self.last_load = now
            except Exception as e:
                # Silently fail if file is being written to
                pass

    def get_bias(self, pair):
        self.load_biases()
        # Roostoo uses BTC/USD
        return self.biases.get(pair, {}).get("signal", "HOLD")

def main():
    print("Initializing Intelligence Bridge (Python Brain)...")
    
    # Initialize the Bias Manager to listen to the Analyst Part
    # Note: Running from Trading-Bot directory, so bias_file is in parent
    bias_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "trading_bias.json"))
    bias_manager = BiasManager(bias_file=bias_file_path)

    context = zmq.Context()

    # Inbound ZMQ_PULL socket for receiving MarketTicks from the Rust Engine
    pull_socket = context.socket(zmq.PULL)
    pull_socket.connect("tcp://127.0.0.1:5556")
    print("ZMQ_PULL connected to tcp://127.0.0.1:5556 (Market Data Incoming)")

    # Outbound ZMQ_PUSH socket for sending TradeSignals back to the Rust Engine
    push_socket = context.socket(zmq.PUSH)
    push_socket.bind("tcp://127.0.0.1:5557")
    print("ZMQ_PUSH bound on tcp://127.0.0.1:5557 (Trade Signals Outgoing)")

    # Map of pairs to their specific strategy state
    strategies = {}

    print("Intelligence Engine online. Awaiting ticks...")

    while True:
        try:
            # Blocking pull; Rust engine has already batched/buffered if needed
            raw_msg = pull_socket.recv()
            t0 = time.perf_counter()

            # Deserialize
            tick = trading_pb2.MarketTick()
            tick.ParseFromString(raw_msg)
            
            # Retrieve or initialize strategy state for this specific trading pair
            if tick.pair not in strategies:
                strategies[tick.pair] = SMACrossoverStrategy(short_window=5, long_window=20)
                print(f"[{tick.timestamp}] New pair initialized: {tick.pair} @ {tick.price:.2f}")
            
            strategy = strategies[tick.pair]
            
            # Execute Strategy Logic isolated from I/O layer
            technical_signal = strategy.update_price_and_check_signal(tick.price)

            if technical_signal:
                # --- INTEGRATION: Join Analyst Part (Macro) with Strategy Part (Micro) ---
                macro_bias = bias_manager.get_bias(tick.pair)
                
                # Check if the technical signal aligns with the Deep Thinking bias
                is_authorized = False
                if technical_signal == "BUY" and macro_bias == "BUY":
                    is_authorized = True
                elif technical_signal == "SELL" and macro_bias == "SELL":
                    is_authorized = True
                
                if is_authorized:
                    # We have an AUTHORIZED trading action
                    signal = trading_pb2.TradeSignal()
                    signal.pair = tick.pair
                    signal.side = technical_signal
                    signal.type = "MARKET"
                    signal.quantity = 1.0 
                    signal.source_timestamp = tick.timestamp

                    outbound_msg = signal.SerializeToString()
                    push_socket.send(outbound_msg)

                    # Total Processing Latency Calculation
                    t1 = time.perf_counter()
                    latency_ms = (t1 - t0) * 1000.0

                    print(f"[{tick.timestamp}] AUTHORIZED SIGNAL: {technical_signal} {tick.pair} @ {tick.price:.2f} | Latency: {latency_ms:.4f} ms")
                else:
                    # Inhibit signal because it contradicts the analyst's high-level view
                    # (Throttle log print to avoid spam)
                    if len(strategies[tick.pair].prices) % 20 == 0:
                        print(f"[{tick.timestamp}] INHIBITED: {technical_signal} {tick.pair} (Analyst Bias is {macro_bias})")

        except KeyboardInterrupt:
            print("\nShutting down Python Brain...")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")

if __name__ == "__main__":
    main()
