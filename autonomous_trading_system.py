import time
import os
import json
from datetime import datetime, timedelta
from rich.console import Console
from rich.markdown import Markdown

# Import our custom modules
from config_manager import ROOSTOO_SYMBOLS, STOCK_SYMBOLS, get_yfinance_ticker
from momentum_scanner import get_top_10_tickers
from execution_manager import ExecutionManager
from trading_bot_opensource import (
    AgentState, InvestDebateState, RiskDebateState,
    market_analyst_node, social_analyst_node, news_analyst_node, fundamentals_analyst_node,
    run_analyst, bull_researcher_node, bear_researcher_node, research_manager_node,
    trader_node, risky_node, safe_node, neutral_node, risk_manager_node,
    signal_proc, config as default_config, HumanMessage, sanitize_text
)

console = Console()

class RateLimiter:
    """Manages delays between API calls to stay within free-tier limits."""
    def __init__(self, llm_delay=30, search_delay=10):
        self.llm_delay = llm_delay
        self.search_delay = search_delay
        self.last_llm_call = 0
        self.last_search_call = 0

    def throttle_llm(self):
        elapsed = time.time() - self.last_llm_call
        if elapsed < self.llm_delay:
            time.sleep(self.llm_delay - elapsed)
        self.last_llm_call = time.time()

    def throttle_search(self):
        elapsed = time.time() - self.last_search_call
        if elapsed < self.search_delay:
            time.sleep(self.search_delay - elapsed)
        self.last_search_call = time.time()

class AutonomousTradingSystem:
    def __init__(self):
        self.crypto_symbols = ROOSTOO_SYMBOLS
        self.stock_symbols = STOCK_SYMBOLS
        self.all_symbols = self.crypto_symbols + self.stock_symbols
        
        self.bias_file = "trading_bias.json"
        self.rate_limiter = RateLimiter(llm_delay=0) # Handled globally in trading_bot_opensource.py
        self.last_full_scan = datetime.min
        self.results_dir = "./results"
        self.status_file = "status.json"
        
        self.executor = ExecutionManager()
        
        os.makedirs(self.results_dir, exist_ok=True)
        self.update_status("Online", "System initialized.")

    def update_status(self, state, details=""):
        """Updates a status file for the dashboard."""
        try:
            with open(self.status_file, "w") as f:
                json.dump({
                    "state": state,
                    "details": details,
                    "timestamp": datetime.now().isoformat()
                }, f, indent=4)
        except Exception:
            pass

    def save_biases(self, all_ticker_results):
        """Saves signals to a JSON file for the execution engine."""
        try:
            # Load existing biases to merge
            if os.path.exists(self.bias_file):
                with open(self.bias_file, "r") as f:
                    data = json.load(f)
            else:
                data = {}

            for res in all_ticker_results:
                data[res['ticker']] = {
                    "signal": res['signal'],
                    "timestamp": datetime.now().isoformat(),
                    "trader_plan": res['trader_plan'] 
                }

            with open(self.bias_file, "w") as f:
                json.dump(data, f, indent=4)
            console.print(f"[bold green]OK: Saved {len(all_ticker_results)} signals to {self.bias_file}[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Error saving biases: {e}[/bold red]")

    def run_cycle(self, ticker_list, cycle_name, deep_analysis=True):
        """
        Performs agentic analysis on a list of tickers.
        Supports 'Light' (Technical only) or 'Deep' (Multi-agent) modes.
        """
        console.print(f"\n[bold yellow]>>> STARTING {cycle_name} ({'DEEP' if deep_analysis else 'LIGHT'}) FOR {len(ticker_list)} ASSETS <<<[/bold yellow]")
        all_ticker_results = []
        
        trade_date = datetime.now().strftime('%Y-%m-%d')
        
        for ticker in ticker_list:
            console.print(f"\n[bold blue]Analysing: {ticker}[/bold blue]")
            self.update_status("Analysing", f"Currently researching {ticker} ({cycle_name})")
            yf_ticker = get_yfinance_ticker(ticker)
            
            st = AgentState(
                messages=[HumanMessage(content=f"Analyse {ticker} for trading on {trade_date}")],
                company_of_interest=ticker,
                trade_date=trade_date,
                portfolio_capital=default_config.get("PORTFOLIO_CAPITAL", 100000),
                investment_debate_state=InvestDebateState(history="", current_response="", count=0, bull_history="", bear_history="", judge_decision=""),
                risk_debate_state=RiskDebateState(history="", latest_speaker="", count=0, current_risky_response="", current_safe_response="", current_neutral_response="", risky_history="", safe_history="", neutral_history="", judge_decision=""),
            )
            
            try:
                # 1. Analyst Nodes (Always Market, others only if Deep)
                analysts = [market_analyst_node]
                if deep_analysis:
                    analysts += [social_analyst_node, news_analyst_node, fundamentals_analyst_node]
                
                for node in analysts:
                    self.rate_limiter.throttle_llm()
                    st.update(run_analyst(node, st))
                    time.sleep(5)
                
                # 2. Researcher Debate (Only if Deep)
                if deep_analysis:
                    for _ in range(default_config["max_debate_rounds"]):
                        self.rate_limiter.throttle_llm()
                        st.update(bull_researcher_node(st))
                        time.sleep(2)
                        self.rate_limiter.throttle_llm()
                        st.update(bear_researcher_node(st))
                        time.sleep(2)
                
                self.rate_limiter.throttle_llm()
                st.update(research_manager_node(st))
                time.sleep(10 if deep_analysis else 2)
                
                # 3. Trader + Risk (Always run, but fewer rounds if Light)
                self.rate_limiter.throttle_llm()
                st.update(trader_node(st))
                time.sleep(5)
                
                risk_rounds = default_config["max_risk_discuss_rounds"] if deep_analysis else 0
                for _ in range(risk_rounds):
                    self.rate_limiter.throttle_llm()
                    st.update(risky_node(st))
                    self.rate_limiter.throttle_llm()
                    st.update(safe_node(st))
                    self.rate_limiter.throttle_llm()
                    st.update(neutral_node(st))
                    time.sleep(2)
                
                self.rate_limiter.throttle_llm()
                st.update(risk_manager_node(st))
                
                # 4. Extract Signal
                decision_text = st["final_trade_decision"]
                signal = signal_proc.process_signal(decision_text)
                
                all_ticker_results.append({
                    "ticker": ticker,
                    "signal": signal,
                    "trader_plan": st["trader_investment_plan"]
                })
                
                console.print(f"[bold green]FINISH: Result for {ticker}: {signal}[/bold green]")
                
            except Exception as e:
                if "429" in str(e) or "rate limit" in str(e).lower():
                    console.print(f"[bold red]API Rate Limit Hit for {ticker}. Pausing for 60s...[/bold red]")
                    time.sleep(60)
                    # Simple one-time retry
                    try:
                        console.print(f"[bold yellow]Retrying {ticker} once...[/bold yellow]")
                        self.rate_limiter.throttle_llm()
                        # Redo the inner loop logic (Simplified for retry)
                        for node in [market_analyst_node, social_analyst_node, news_analyst_node, fundamentals_analyst_node]:
                            self.rate_limiter.throttle_llm()
                            st.update(run_analyst(node, st))
                        self.rate_limiter.throttle_llm()
                        st.update(research_manager_node(st))
                        self.rate_limiter.throttle_llm()
                        st.update(trader_node(st))
                        self.rate_limiter.throttle_llm()
                        st.update(risk_manager_node(st))
                        
                        decision_text = st["final_trade_decision"]
                        signal = signal_proc.process_signal(decision_text)
                        all_ticker_results.append({
                            "ticker": ticker,
                            "signal": signal,
                            "trader_plan": st["trader_investment_plan"]
                        })
                        console.print(f"[bold green]RETRY SUCCESS: Result for {ticker}: {signal}[/bold green]")
                    except Exception as e2:
                        console.print(f"[bold red]Retry failed for {ticker}: {e2}[/bold red]")
                else:
                    console.print(f"[bold red]Error in analysis for {ticker}: {e}[/bold red]")
                
            # Periodic save to avoid data loss
            self.save_biases(all_ticker_results)
            
        return all_ticker_results

    def start(self):
        console.print("[bold green]Autonomous Trading System Online.[/bold green]")
        self.update_status("Online", "Initial Gap Analysis...")
        
        while True:
            now = datetime.now()
            
            # Load current biases to find gaps
            current_biases = {}
            if os.path.exists(self.bias_file):
                try:
                    with open(self.bias_file, "r") as f:
                        current_biases = json.load(f)
                except Exception:
                    pass

            # Identify missing symbols
            missing = [s for s in self.all_symbols if s not in current_biases]
            
            # Identify symbols to refresh (Oldest first)
            stale = sorted(
                [s for s in self.all_symbols if s in current_biases],
                key=lambda s: current_biases[s].get("timestamp", "1970-01-01")
            )
            
            # Form the queue: Missing first, then Stale
            queue = missing + stale
            
            if missing:
                console.print(f"\n[bold yellow]FOUND GAPS: {len(missing)} missing assets identified.[/bold yellow]")
                # Process all missing immediately in batches of 5 to show progress
                for i in range(0, len(missing), 5):
                    batch = missing[i:min(i+5, len(missing))]
                    self.run_cycle(batch, "GAP FILLING", deep_analysis=True)
            else:
                # Regular Refresh Cycle
                console.print(f"\n[bold cyan]Time: {now.strftime('%H:%M:%S')} | Refreshing oldest data...[/bold cyan]")
                # Refresh top 5 oldest/stale ones
                top_refresh = stale[:5]
                self.run_cycle(top_refresh, "STALE REFRESH", deep_analysis=True)
            
            # Wait for next priority check
            console.print("\n[italic yellow]Cycle complete. Next gap/stale check in 10 minutes...[/italic yellow]")
            time.sleep(600)


if __name__ == "__main__":
    system = AutonomousTradingSystem()
    system.start()
