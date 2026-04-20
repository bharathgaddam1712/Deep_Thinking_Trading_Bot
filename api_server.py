from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
import json
import os
import zmq
import sys
import time
from datetime import datetime
from local_broker import LocalBroker

# Add proto directory to path
PROTO_PATH = os.path.join(os.getcwd(), "Trading-Bot", "proto")
if os.path.exists(PROTO_PATH):
    sys.path.append(PROTO_PATH)
    try:
        import trading_pb2
    except Exception:
        trading_pb2 = None
else:
    trading_pb2 = None

app = FastAPI()

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

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

@app.get("/api/balance")
async def get_balance():
    try:
        from roostoo_client import RoostooClient
        r_client = RoostooClient()
        r_bal = r_client.get_balance()
        
        if r_bal.get("Success"):
            spot = r_bal.get("SpotWallet", {})
            usd_bal = spot.get("USD", {}).get("Free", 0)
            
            # Extract all coins for the tooltip/detail
            assets = {k: v.get("Free", 0) for k, v in spot.items() if v.get("Free", 0) > 0}
            
            return {
                "net_worth": usd_bal, 
                "bridge": "Active - Roostoo Platform",
                "is_live": True,
                "assets": assets
            }
        
        # Fallback to local
        broker = LocalBroker()
        summary = broker.get_summary()
        return {
            "net_worth": summary["net_worth"],
            "bridge": "Local Virtual Simulation",
            "is_live": False,
            "assets": {"USD": summary["cash"]}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/holdings")
async def get_holdings():
    try:
        from roostoo_client import RoostooClient
        r_client = RoostooClient()
        r_bal = r_client.get_balance()
        
        if not r_bal.get("Success"):
            return []

        spot_wallet = r_bal.get("SpotWallet", {})
        broker = LocalBroker()
        local_holdings = broker.data.get("holdings", {})
        
        holdings = []
        for coin, info in spot_wallet.items():
            qty = info.get("Free", 0)
            
            # Filter: Exclude USD and empty keys, only Free > 0
            if coin in ["USD", "", "VIRTUAL"] or qty <= 0:
                continue
                
            symbol = f"{coin}/USD"
            current_price = broker.get_price(symbol)
            
            # Get Entry Price from local history if exists, otherwise fallback to current
            entry_price = current_holdings.get(symbol, {}).get("avg_price") if (current_holdings := local_holdings) else None
            if not entry_price:
                 entry_price = current_price or 0.0

            if current_price and entry_price > 0:
                pnl = (current_price - entry_price) * qty
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
            else:
                pnl, pnl_pct = 0.0, 0.0

            holdings.append({
                "symbol": symbol,
                "qty": round(qty, 4),
                "entry": round(entry_price, 4),
                "current": round(current_price, 4) if current_price else 0.0,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2)
            })
            
        return holdings
    except Exception as e:
        print(f"Error in get_holdings: {e}")
        return []

@app.post("/api/execute")
async def execute_trade(data: Request):
    try:
        req = await data.json()
        pair = req.get("pair")
        side = req.get("side") # BUY or SELL
        quantity = float(req.get("quantity", 1.0))
        
        # 1. Direct High-Speed Execution via Roostoo API
        from roostoo_client import RoostooClient
        r_client = RoostooClient()
        
        print(f"[MANUAL] Initiating {side} for {quantity} units of {pair}...")
        res = r_client.place_order(pair, side, quantity)
        
        if res.get("Success"):
            # 2. Async update of local records
            try:
                broker = LocalBroker()
                fill_price = res.get("OrderDetail", {}).get("Price", 0.0)
                if side == "BUY":
                    # Local record only (Roostoo already has the asset)
                    broker.data["cash"] -= quantity * fill_price
                    holdings = broker.data["holdings"]
                    if pair in holdings:
                        qty_old = holdings[pair]["qty"]
                        avg_old = holdings[pair]["avg_price"]
                        holdings[pair] = {"qty": qty_old + quantity, "avg_price": ((qty_old * avg_old) + (quantity * fill_price)) / (qty_old + quantity)}
                    else:
                        holdings[pair] = {"qty": quantity, "avg_price": fill_price}
                else:
                    if pair in broker.data["holdings"]:
                        del broker.data["holdings"][pair]
                broker._save_portfolio(broker.data)
            except Exception as e:
                print(f"Post-Trade local record error: {e}")

            return {"status": "success", "message": f"ORDER FILLED: {side} {quantity} {pair}"}
        else:
            return {"status": "error", "message": f"Roostoo Rejection: {res.get('ErrMsg')}"}
            
    except Exception as e:
        print(f"Execution Error: {e}")
        return {"status": "error", "message": str(e)}


# Premium HTML Dashboard (Upgraded with Execution UI)
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ROOSTOO | Deep Thinking Command Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;600;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-black: #000000;
            --card-bg: rgba(17, 24, 39, 0.6);
            --roostoo-amber: #fbbf24;
            --roostoo-amber-dim: rgba(251, 191, 36, 0.2);
            --neon-green: #4ade80;
            --neon-red: #f87171;
            --text-main: #f3f4f6;
            --text-dim: #9ca3af;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background-color: var(--bg-black);
            color: var(--text-main);
            font-family: 'Space Grotesk', sans-serif;
            min-height: 100vh;
            overflow-x: hidden;
            background-image: 
                linear-gradient(rgba(251, 191, 36, 0.03) 1px, transparent 1px),
                linear-gradient(90deg, rgba(251, 191, 36, 0.03) 1px, transparent 1px);
            background-size: 50px 50px;
        }

        .container { max-width: 1600px; margin: 0 auto; padding: 1.5rem; }
        
        header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 2rem; 
            padding: 1rem;
            border-bottom: 1px solid var(--roostoo-amber-dim);
        }

        .logo { display: flex; align-items: center; gap: 1rem; }
        .logo h1 { 
            font-family: 'Space Grotesk', sans-serif; 
            font-size: 1.8rem; 
            letter-spacing: -1px;
            color: var(--roostoo-amber);
            text-transform: uppercase;
            font-weight: 800;
        }
        .logo .brand { color: white; opacity: 0.5; font-weight: 300; font-size: 0.8rem; letter-spacing: 2px; }

        .system-status { 
            display: flex; 
            align-items: center; 
            gap: 1rem; 
            background: var(--roostoo-amber-dim); 
            padding: 0.5rem 1.5rem; 
            border-radius: 4px; 
            border: 1px solid var(--roostoo-amber);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            color: var(--roostoo-amber);
        }
        .status-pulse { width: 8px; height: 8px; background: var(--neon-green); border-radius: 50%; box-shadow: 0 0 10px var(--neon-green); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }

        .dashboard-grid { display: grid; grid-template-columns: 1fr 500px; gap: 1.5rem; align-items: start; }
        
        .card { 
            background: var(--card-bg); 
            border: 1px solid var(--roostoo-amber-dim); 
            border-radius: 4px; 
            padding: 1.5rem; 
            backdrop-filter: blur(10px);
            position: relative;
            overflow: hidden;
        }
        .card::before {
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 100%;
            height: 2px;
            background: linear-gradient(90deg, var(--roostoo-amber), transparent);
            opacity: 0.3;
        }

        .section-header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 2rem; 
            border-left: 4px solid var(--roostoo-amber);
            padding-left: 1rem;
        }
        .section-header h2 { font-size: 1.2rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }

        /* Signal Components */
        .signal-list { display: flex; flex-direction: column; gap: 0.75rem; }
        .signal-item { 
            display: grid; 
            grid-template-columns: 140px 100px 1fr auto; 
            align-items: center; 
            padding: 1rem 1.5rem; 
            background: rgba(255, 255, 255, 0.02); 
            border: 1px solid rgba(255, 255, 255, 0.05);
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: pointer;
            font-family: 'JetBrains Mono', monospace;
        }
        .signal-item:hover { 
            background: var(--roostoo-amber-dim); 
            border-color: var(--roostoo-amber);
            transform: scale(1.01);
        }
        .signal-ticker { font-weight: 700; color: var(--roostoo-amber); font-size: 1rem; }
        
        .badge { 
            padding: 4px 12px; 
            font-size: 0.65rem; 
            font-weight: 800; 
            text-transform: uppercase; 
            border-radius: 2px;
            text-align: center;
        }
        .badge-buy { background: rgba(74, 222, 128, 0.1); color: var(--neon-green); border: 1px solid var(--neon-green); }
        .badge-sell { background: rgba(248, 113, 113, 0.1); color: var(--neon-red); border: 1px solid var(--neon-red); }
        .badge-hold { background: rgba(156, 163, 175, 0.1); color: var(--text-dim); border: 1px solid var(--text-dim); }

        .timestamp { font-size: 0.75rem; color: var(--text-dim); margin-left: 2rem; }
        .action-hint { font-size: 0.7rem; color: var(--roostoo-amber); opacity: 0; transition: opacity 0.2s; font-weight: 800; }
        .signal-item:hover .action-hint { opacity: 1; }

        /* Details Pane */
        .detail-pane { position: sticky; top: 1.5rem; display: flex; flex-direction: column; gap: 1.5rem; }
        
        .thinking-module { 
            background: rgba(251, 191, 36, 0.05); 
            border: 1px dashed var(--roostoo-amber);
            padding: 1rem;
            font-family: 'JetBrains Mono', monospace;
        }
        .thinking-label { font-size: 0.65rem; color: var(--roostoo-amber); font-weight: 800; margin-bottom: 0.5rem; text-transform: uppercase; }
        .thinking-text { font-size: 0.8rem; color: var(--text-dim); }

        .proposal-card { display: flex; flex-direction: column; height: 70vh; }
        .proposal-body { 
            flex-grow: 1; 
            overflow-y: auto; 
            font-family: 'Space Grotesk', sans-serif;
            font-size: 1rem;
            line-height: 1.8;
            color: var(--text-main);
            padding-right: 1rem;
            white-space: pre-wrap;
        }
        .proposal-body::-webkit-scrollbar { width: 4px; }
        .proposal-body::-webkit-scrollbar-thumb { background: var(--roostoo-amber); }

        /* Execution Module */
        .execution-module { 
            margin-top: 1.5rem; 
            padding-top: 1.5rem; 
            border-top: 1px solid var(--roostoo-amber-dim);
        }
        .exec-header { font-size: 0.7rem; font-weight: 800; color: var(--text-dim); text-transform: uppercase; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; }
        .exec-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.75rem; }
        
        input { 
            background: var(--bg-black); 
            border: 1px solid var(--roostoo-amber-dim); 
            color: var(--roostoo-amber); 
            padding: 0.8rem; 
            font-family: 'JetBrains Mono', monospace;
            font-size: 1rem;
            width: 100%;
        }
        input:focus { border-color: var(--roostoo-amber); outline: none; }

        .btn { 
            border: 1px solid transparent; 
            padding: 0.8rem; 
            font-weight: 800; 
            cursor: pointer; 
            text-transform: uppercase; 
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            transition: all 0.2s;
        }
        .btn-buy { color: var(--neon-green); border-color: var(--neon-green); background: transparent; }
        .btn-buy:hover { background: rgba(74, 222, 128, 0.1); }
        .btn-sell { color: var(--neon-red); border-color: var(--neon-red); background: transparent; }
        .btn-sell:hover { background: rgba(248, 113, 113, 0.1); }
        .btn:disabled { opacity: 0.2; cursor: not-allowed; }

        #toast { 
            position: fixed; 
            bottom: 2rem; 
            right: 2rem; 
            background: var(--roostoo-amber); 
            color: black; 
            padding: 1rem 2rem; 
            font-weight: 800; 
            font-family: 'JetBrains Mono', monospace;
            transform: translateY(150px);
            transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            z-index: 9999;
        }
        #toast.visible { transform: translateY(0); }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <h1>Roostoo</h1>
                <span class="brand">DEEP THINKING TERMINAL</span>
            </div>
            <div class="system-status">
                <div class="status-pulse"></div>
                <span id="system-state">INITIALIZING...</span>
                <span style="opacity: 0.3">|</span>
                <span id="thinking-details">AWAITING CYCLE</span>
                <span style="opacity: 0.3">|</span>
                <span id="account-balance" style="font-weight: 800; color: white;">BAL: $---</span>
                <button onclick="updateBalance()" style="background: none; border: none; color: var(--roostoo-amber); font-family: 'JetBrains Mono'; font-size: 0.6rem; cursor: pointer; text-decoration: underline;">REFRESH</button>
            </div>
        </header>

        <div class="dashboard-grid">
            <div class="card main-data">
                <div class="section-header">
                    <h2>Market Intelligence</h2>
                    <span id="last-update" style="font-family: 'JetBrains Mono'; font-size: 0.7rem; color: var(--text-dim);">--:--:--</span>
                </div>
                <div id="signal-container" class="signal-list">
                    <!-- Dynamic Signals -->
                </div>
            </div>

            <div class="detail-pane">
                <div class="thinking-module">
                    <div class="thinking-label">Tactical Combat Engine</div>
                    <div id="thinking-summary" class="thinking-text">Initializing autonomous execution loop...</div>
                </div>

                <div class="card portfolio-card">
                    <div class="section-header" style="margin-bottom: 1rem;">
                        <h2>Combat Portfolio</h2>
                    </div>
                    <table style="width: 100%; border-collapse: collapse; font-family: 'JetBrains Mono'; font-size: 0.75rem;">
                        <thead>
                            <tr style="text-align: left; color: var(--text-dim); border-bottom: 1px solid var(--roostoo-amber-dim);">
                                <th style="padding: 0.5rem 0;">ASSET</th>
                                <th style="text-align: right;">ENTRY</th>
                                <th style="text-align: right;">PNL%</th>
                            </tr>
                        </thead>
                        <tbody id="portfolio-body">
                            <!-- Dynamic Holdings -->
                        </tbody>
                    </table>
                </div>

                <div class="card proposal-card" id="detail-panel" style="display: none;">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 2rem;">
                        <div>
                            <h2 id="detail-ticker" style="font-size: 2rem; letter-spacing: -2px; color: var(--roostoo-amber);">--</h2>
                            <p style="font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; margin-top: 0.25rem;">Research Manager Proposal</p>
                        </div>
                        <span id="detail-badge" class="badge">--</span>
                    </div>

                    <div class="proposal-body" id="detail-plan">
                        Select an instrument from the terminal list to decode the full research proposal.
                    </div>
                    
                    <div class="execution-module">
                        <div class="exec-header">
                            <span style="color: var(--roostoo-amber)">⚡</span> Direct Execution Protocol
                        </div>
                        <div class="exec-grid">
                            <input type="number" id="exec-qty" value="1.0" step="0.1" min="0">
                            <button class="btn btn-buy" id="btn-buy" onclick="sendOrder('BUY')">Execute Buy</button>
                            <button class="btn btn-sell" id="btn-sell" onclick="sendOrder('SELL')">Execute Sell</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div id="toast">PROTOCOL INITIATED</div>

    <script>
        let selectedTicker = null;

        async function updateDashboard() {
            try {
                const bR = await fetch('/api/biases');
                const biases = await bR.json();
                const sR = await fetch('/api/status');
                const status = await sR.json();

                document.getElementById('system-state').innerText = status.state.toUpperCase();
                document.getElementById('thinking-summary').innerText = status.details;

                const container = document.getElementById('signal-container');
                const tickers = Object.keys(biases).sort((a,b) => new Date(biases[b].timestamp) - new Date(biases[a].timestamp));

                if (tickers.length === 0) {
                    container.innerHTML = `<div style="text-align: center; color: var(--text-dim); padding: 5rem; font-family: 'JetBrains Mono'; font-size: 0.8rem; border: 1px dashed rgba(255,255,255,0.05);">[ TERMINAL IDLE - SCANNING IN PROGRESS ]</div>`;
                } else {
                    container.innerHTML = '';
                    tickers.forEach(t => {
                        const d = biases[t];
                        const div = document.createElement('div');
                        div.className = 'signal-item';
                        if (selectedTicker === t) div.style.borderColor = 'var(--roostoo-amber)';
                        div.onclick = () => showDetail(t, d);
                        const bClass = `badge-${d.signal.toLowerCase()}`;
                        div.innerHTML = `
                            <span class="signal-ticker">${t}</span>
                            <span class="badge ${bClass}">${d.signal}</span>
                            <span class="timestamp">${new Date(d.timestamp).toLocaleTimeString()}</span>
                            <span class="action-hint">DECODE PROPOSAL _</span>
                        `;
                        container.appendChild(div);
                    });
                }
                document.getElementById('last-update').innerText = `SYNC_OK // ${new Date().toLocaleTimeString()}`;
            } catch (e) {}
        }

        function showDetail(t, d) {
            selectedTicker = t;
            const p = document.getElementById('detail-panel');
            p.style.display = 'flex';
            p.style.flexDirection = 'column';
            document.getElementById('detail-ticker').innerText = t;
            document.getElementById('detail-badge').innerText = d.signal;
            document.getElementById('detail-badge').className = `badge badge-${d.signal.toLowerCase()}`;
            document.getElementById('detail-plan').innerText = d.trader_plan.replace(/\\\\*\\\\*/g, '');
            
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
                showToast(res.message || "PROTOCOL SENT");
            } catch (e) {
                showToast("COMMS ERROR");
            } finally {
                btn.disabled = false;
            }
        }

        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.className = 'visible';
            setTimeout(() => t.className = '', 3000);
        }

        async function updateBalance() {
            try {
                const r = await fetch('/api/balance');
                const d = await r.json();
                document.getElementById('account-balance').innerText = `BAL: $${d.net_worth.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                document.getElementById('thinking-details').innerText = d.bridge;
                
                // Tooltip for other assets
                let assetsStr = Object.entries(d.assets).map(([k,v]) => `${k}: ${v.toFixed(4)}`).join(' | ');
                document.getElementById('account-balance').title = assetsStr;

                if (d.is_live) {
                    document.getElementById('system-state').style.color = '#4ade80';
                    document.getElementById('system-state').innerText = 'BRIDGE ONLINE';
                }
            } catch (e) {}
        }

        async function updatePortfolio() {
            try {
                const r = await fetch('/api/holdings');
                const holdings = await r.json();
                const container = document.getElementById('portfolio-body');
                
                if (holdings.length === 0) {
                    container.innerHTML = `<tr><td colspan="3" style="text-align: center; padding: 2rem; color: var(--text-dim);">NO ACTIVE POSITIONS</td></tr>`;
                    return;
                }

                container.innerHTML = '';
                holdings.forEach(h => {
                    const tr = document.createElement('tr');
                    tr.style.borderBottom = '1px solid rgba(255,255,255,0.03)';
                    const pnlColor = h.pnl_pct >= 0 ? 'var(--neon-green)' : 'var(--neon-red)';
                    tr.innerHTML = `
                        <td style="padding: 0.8rem 0;">
                            <div style="font-weight: 700; color: white;">${h.symbol}</div>
                            <div style="font-size: 0.6rem; color: var(--text-dim);">${h.qty} UNITS</div>
                        </td>
                        <td style="text-align: right; color: var(--text-dim);">$${h.entry.toLocaleString()}</td>
                        <td style="text-align: right; font-weight: 700; color: ${pnlColor};">
                            ${h.pnl_pct > 0 ? '+' : ''}${h.pnl_pct}%
                        </td>
                    `;
                    container.appendChild(tr);
                });
            } catch (e) {}
        }

        setInterval(updateDashboard, 5000);
        setInterval(updateBalance, 10000);
        setInterval(updatePortfolio, 5000);
        updateDashboard();
        updateBalance();
        updatePortfolio();
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
