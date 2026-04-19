from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import json
import os
import zmq
import sys
import time
from datetime import datetime

# Add proto directory to path
PROTO_PATH = os.path.join(os.getcwd(), "Trading-Bot", "proto")
if os.path.exists(PROTO_PATH):
    sys.path.append(PROTO_PATH)
    try:
        import trading_pb2
    except ImportError:
        trading_pb2 = None
else:
    trading_pb2 = None

app = FastAPI()

# Files to watch
BIAS_FILE = "trading_bias.json"
STATUS_FILE = "status.json"

# Initialize ZeroMQ for trade execution (Push only)
context = zmq.Context()
push_socket = context.socket(zmq.PUSH)
try:
    push_socket.connect("tcp://127.0.0.1:5557")
    print("ZMQ_PUSH connected to tcp://127.0.0.1:5557 (Trade Execution Bridge)")
except Exception as e:
    print(f"WARN: Could not connect to ZMQ socket: {e}")

@app.get("/api/biases")
async def get_biases():
    if not os.path.exists(BIAS_FILE):
        return {}
    with open(BIAS_FILE, "r") as f:
        return json.load(f)

@app.get("/api/status")
async def get_status():
    if not os.path.exists(STATUS_FILE):
        return {"state": "Offline", "details": "Bot not detected."}
    with open(STATUS_FILE, "r") as f:
        return json.load(f)

@app.post("/api/execute")
async def execute_trade(data: Request):
    req = await data.json()
    pair = req.get("pair")
    side = req.get("side") # BUY or SELL
    quantity = float(req.get("quantity", 1.0))

    if not trading_pb2:
        raise HTTPException(status_code=500, detail="Trading Protobufs not loaded.")

    try:
        # Create Protobuf Message
        signal = trading_pb2.TradeSignal()
        signal.pair = pair
        signal.side = side
        signal.type = "MARKET"
        signal.quantity = quantity
        signal.source_timestamp = datetime.now().strftime("%H:%M:%S")

        # Send via ZMQ
        outbound_msg = signal.SerializeToString()
        push_socket.send(outbound_msg)
        
        print(f"EXECUTION SENT: {side} {quantity} {pair}")
        return {"status": "success", "message": f"Sent {side} order for {quantity} {pair}"}
    except Exception as e:
        print(f"EXECUTION ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Premium HTML Dashboard (Upgraded with Execution UI)
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Deep Thinking Trading Command Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=Outfit:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.7);
            --accent: #38bdf8;
            --buy: #22c55e;
            --sell: #ef4444;
            --hold: #94a3b8;
            --text: #f8fafc;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: var(--bg);
            color: var(--text);
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(56, 189, 248, 0.05) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(139, 92, 246, 0.05) 0%, transparent 40%);
        }

        .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; }
        .logo h1 { font-family: 'Outfit', sans-serif; font-size: 1.5rem; background: linear-gradient(to right, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

        .system-status { display: flex; align-items: center; gap: 0.75rem; background: var(--card-bg); padding: 0.5rem 1rem; border-radius: 99px; font-size: 0.85rem; border: 1px solid rgba(255, 255, 255, 0.1); }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 10px #22c55e; }

        .grid { display: grid; grid-template-columns: 1fr 400px; gap: 2rem; }
        .card { background: var(--card-bg); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 16px; padding: 1.5rem; backdrop-filter: blur(12px); }
        
        .signal-item { display: grid; grid-template-columns: 1fr 80px 100px auto; align-items: center; padding: 1rem; background: rgba(255, 255, 255, 0.03); border-radius: 12px; margin-bottom: 0.75rem; cursor: pointer; border: 1px solid transparent; transition: all 0.2s; }
        .signal-item:hover { background: rgba(255, 255, 255, 0.06); border-color: var(--accent); }
        .ticker { font-weight: 700; color: var(--accent); }
        
        .badge { padding: 4px 10px; border-radius: 6px; font-size: 0.7rem; font-weight: 800; text-transform: uppercase; text-align: center; }
        .badge-buy { background: rgba(34, 197, 94, 0.1); color: #22c55e; border: 1px solid #22c55e; }
        .badge-sell { background: rgba(239, 68, 68, 0.1); color: #ef4444; border: 1px solid #ef4444; }
        .badge-hold { background: rgba(148, 163, 184, 0.1); color: #94a3b8; border: 1px solid #94a3b8; }

        /* Detail Panel */
        .detail-pane { position: sticky; top: 2rem; height: calc(100vh - 4rem); display: flex; flex-direction: column; gap: 1rem; }
        .plan-box { flex-grow: 1; overflow-y: auto; font-size: 0.9rem; line-height: 1.6; color: #cbd5e1; white-space: pre-wrap; margin-bottom: 1rem; }
        
        /* Execution UI */
        .execution-box { background: rgba(255, 255, 255, 0.05); border-radius: 12px; padding: 1.25rem; border: 1px solid rgba(56, 189, 248, 0.2); }
        .exec-controls { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 1rem; }
        input { background: #0f172a; border: 1px solid #334155; color: white; padding: 0.75rem; border-radius: 8px; width: 100%; margin-bottom: 0.5rem; text-align: center; font-family: inherit; }
        
        button { border: none; padding: 0.75rem; border-radius: 8px; font-weight: 700; cursor: pointer; transition: opacity 0.2s; font-family: inherit; }
        .btn-buy { background: var(--buy); color: white; }
        .btn-sell { background: var(--sell); color: white; }
        button:hover { opacity: 0.8; }
        button:disabled { opacity: 0.3; cursor: not-allowed; }

        .thinking-card { background: linear-gradient(135deg, rgba(56, 189, 248, 0.1) 0%, rgba(129, 140, 248, 0.1) 100%); border: 1px solid rgba(56, 189, 248, 0.2); margin-bottom: 1rem; }

        #toast { position: fixed; bottom: 2rem; right: 2rem; padding: 1rem 2rem; border-radius: 8px; font-weight: 600; transform: translateY(100px); transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275); z-index: 1000; }
        #toast.visible { transform: translateY(0); }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo"><h1>Deep Thinking Center (USD)</h1></div>
            <div class="system-status">
                <div class="status-dot"></div>
                <span id="system-state">Online</span>
            </div>
        </header>

        <div class="grid">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                    <h2 style="font-family: 'Outfit';">Market Intelligence</h2>
                    <span id="last-update" style="font-size: 0.8rem; color: #64748b;">Syncing...</span>
                </div>
                <div id="signal-container">
                    <!-- Signals go here -->
                </div>
            </div>

            <div class="detail-pane">
                <div class="card thinking-card">
                    <p style="font-weight: 600; color: var(--accent); font-size: 0.85rem;" id="current-task">Awaiting Data...</p>
                    <p id="thinking-details" style="font-size: 0.8rem; color: #94a3b8; margin-top: 0.25rem;">Waiting for cycle start.</p>
                </div>

                <div class="card" id="detail-panel" style="display: none;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                        <h2 id="detail-ticker" style="font-family: 'Outfit';">--</h2>
                        <span id="detail-badge" class="badge">--</span>
                    </div>
                    <div class="plan-box" id="detail-plan">Select an asset to view the investment plan.</div>
                    
                    <div class="execution-box">
                        <p style="font-size: 0.75rem; font-weight: 800; color: #64748b; margin-bottom: 0.75rem; text-transform: uppercase;">Direct Roostoo Execution</p>
                        <input type="number" id="exec-qty" value="1.0" step="0.1" min="0">
                        <div class="exec-controls">
                            <button class="btn-buy" id="btn-buy" onclick="sendOrder('BUY')">BUY</button>
                            <button class="btn-sell" id="btn-sell" onclick="sendOrder('SELL')">SELL</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div id="toast" class="">Trade Signal Sent!</div>

    <script>
        let selectedTicker = null;
        let lastTimestamp = null;

        async function updateDashboard() {
            try {
                const bR = await fetch('/api/biases');
                const biases = await bR.json();
                const sR = await fetch('/api/status');
                const status = await sR.json();

                document.getElementById('system-state').innerText = status.state;
                document.getElementById('current-task').innerText = status.state === 'Analysing' ? 'Analyzing Assets' : status.state;
                document.getElementById('thinking-details').innerText = status.details;

                const container = document.getElementById('signal-container');
                const tickers = Object.keys(biases).sort((a,b) => new Date(biases[b].timestamp) - new Date(biases[a].timestamp));

                if (tickers.length === 0) {
                    container.innerHTML = '<div style="text-align: center; color: #64748b; padding: 3rem;">No signals generated yet. Scan in progress...</div>';
                } else {
                    container.innerHTML = '';
                    tickers.forEach(t => {
                        const d = biases[t];
                        const div = document.createElement('div');
                        div.className = 'signal-item';
                        div.style.borderColor = selectedTicker === t ? 'var(--accent)' : 'transparent';
                        div.onclick = () => showDetail(t, d);
                        const bClass = `badge-${d.signal.toLowerCase()}`;
                        div.innerHTML = `
                            <span class="ticker">${t}</span>
                            <span class="badge ${bClass}">${d.signal}</span>
                            <span style="font-size: 0.8rem; color: #64748b;">${new Date(d.timestamp).toLocaleTimeString()}</span>
                            <span style="color: var(--accent); font-size: 0.8rem; font-weight: 700;">REVIEW →</span>
                        `;
                        container.appendChild(div);
                    });
                }
                document.getElementById('last-update').innerText = `Synced: ${new Date().toLocaleTimeString()}`;
            } catch (e) {}
        }

        function showDetail(t, d) {
            selectedTicker = t;
            const p = document.getElementById('detail-panel');
            p.style.display = 'flex';
            document.getElementById('detail-ticker').innerText = t;
            document.getElementById('detail-badge').innerText = d.signal;
            document.getElementById('detail-badge').className = `badge badge-${d.signal.toLowerCase()}`;
            document.getElementById('detail-plan').innerText = d.trader_plan.replace(/\\*\\*/g, '');
            
            // Re-render list to show selection border
            updateDashboard();
        }

        async function sendOrder(side) {
            if (!selectedTicker) return;
            const qty = document.getElementById('exec-qty').value;
            const btn = document.getElementById(`btn-${side.toLowerCase()}`);
            btn.disabled = true;

            try {
                const r = await fetch('/api/execute', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ pair: selectedTicker, side: side, quantity: qty })
                });
                const res = await r.json();
                showToast(res.message || "Order Sent!");
            } catch (e) {
                showToast("Execution Error");
            } finally {
                btn.disabled = false;
            }
        }

        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.className = 'visible';
            t.style.background = msg.includes("Error") ? 'var(--sell)' : 'var(--buy)';
            setTimeout(() => t.className = '', 3000);
        }

        setInterval(updateDashboard, 5000);
        updateDashboard();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return HTML_CONTENT

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
