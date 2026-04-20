# =============================================================================
# Deep Thinking Multi-Agent Trading System — Open-Source Edition (FIXED)
# =============================================================================
# LLMs      : Groq (FREE) → LLaMA 3.3 70B (deep) + LLaMA 3.1 8B (quick)
# Embeddings: Local SentenceTransformers — NO API KEY, runs on CPU
# Search    : Tavily (free tier) for sentiment / fundamentals / macro
# News      : yfinance built-in news + RSS scraping (replaces Finnhub for .NS)
# Market    : Yahoo Finance (yfinance) — completely free
# Ticker    : RELIANCE.NS  (Reliance Industries, NSE India)
# Date      : 2025-03-15
#
# Keys read from .env file automatically — no interactive prompts
# Install:
#   pip install python-dotenv langchain langgraph langchain-groq
#               langchain-community tavily-python yfinance stockstats
#               beautifulsoup4 chromadb sentence-transformers pydantic
#               rich requests pandas
# =============================================================================

# -----------------------------------------------------------------------------
# PART 1 — Load .env, Config, LLMs, State, Tools, Memory
# -----------------------------------------------------------------------------

import os, sys, functools
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

# -- Load all keys from .env file (no interactive prompts) ---------------------
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    loaded = load_dotenv(dotenv_path=env_path, override=True)
    if loaded:
        print(f"OK: Loaded keys from {env_path}")
    else:
        print(f"WARN:  .env not found at {env_path} — falling back to system env vars")
except ImportError:
    print("WARN:  python-dotenv not installed. Run: pip install python-dotenv")
    print("   Falling back to system environment variables.")

# -- Validate required keys are present ----------------------------------------
REQUIRED_KEYS = ["GEMINI_API_KEY", "TAVILY_API_KEY"]
missing = [k for k in REQUIRED_KEYS if not os.environ.get(k)]
if missing:
    print(f"\nERROR: Missing required keys in .env: {missing}")
    print("   Add them to your .env file and re-run.")
    sys.exit(1)

if not os.environ.get("LANGSMITH_API_KEY"):
    print("WARN: LANGSMITH_API_KEY missing — tracing will be disabled.")
    os.environ["LANGSMITH_TRACING"] = "false"
else:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = "Deep-Trading-System-OpenSource"
# -- Config (Default - typically overridden by caller) -------------------------
from pprint import pprint

config = {
    "results_dir": "./results",
    "llm_provider": "groq",
    "deep_think_llm":  "llama-3.3-70b-versatile", # High intelligence for final decisions
    "quick_think_llm": "llama-3.1-8b-instant",     # High TPS for debate rounds
    "analyst_llm":     "llama-3.1-8b-instant",     # High TPS for tool execution
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    "online_tools": True,
    "data_cache_dir": "./data_cache",
    "PORTFOLIO_CAPITAL": 1000000, 
    "TICKER_LIST": [],
    "TRADE_DATE": datetime.now().strftime('%Y-%m-%d'),
}
os.makedirs(config["data_cache_dir"], exist_ok=True)
os.makedirs(config["results_dir"], exist_ok=True)

# -- LLMs: Groq (free tier) ------------------------------
from langchain_groq import ChatGroq

deep_thinking_llm = ChatGroq(
    model=config["deep_think_llm"],
    temperature=0.1,
    groq_api_key=os.environ.get("GROQ_API_KEY")
)
quick_thinking_llm = ChatGroq(
    model=config["quick_think_llm"],
    temperature=0.1,
    groq_api_key=os.environ.get("GROQ_API_KEY")
)
analyst_llm = ChatGroq(
    model=config["analyst_llm"],
    temperature=0.1,
    groq_api_key=os.environ.get("GROQ_API_KEY")
)

# Global tracker for  limiting across all agents
import time
import random
_last_llm_call_time = 0

def safe_llm_invoke(llm, prompt_or_msgs, max_retries=10):
    """Wrapper to handle API rate limits with automatic exponential backoff."""
    global _last_llm_call_time
    
    # ── MANDATORY THROTTLE ──
    # Gemini Flash Free Tier is 15 RPM (1 call every 4s). 
    # We enforce a strict 5s gap to account for tool-calling bursts.
    MIN_GAP = 5.0
    elapsed = time.time() - _last_llm_call_time
    if elapsed < MIN_GAP:
        time.sleep(MIN_GAP - elapsed)
    
    for i in range(max_retries):
        try:
            _last_llm_call_time = time.time()
            return llm.invoke(prompt_or_msgs)
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "rate limit" in err_str or "quota" in err_str:
                # Dynamic wait exponential backoff
                wait_time = (2 ** i) + random.random() * 5
                
                print(f"WARN: API Rate Limit Hit. Waiting {wait_time:.2f}s (Attempt {i+1}/{max_retries})...", flush=True)
                time.sleep(wait_time)
                continue
            
            # If it's a context window error, truncate and retry
            if "context_length" in err_str or "token" in err_str or "exceeded" in err_str:
                if isinstance(prompt_or_msgs, list):
                    print("WARN: Context window exceeded. Truncating message history...")
                    if len(prompt_or_msgs) > 2:
                        prompt_or_msgs = [prompt_or_msgs[0]] + prompt_or_msgs[int(len(prompt_or_msgs)/2):]
                        continue
            
            raise e
    raise Exception(f"Failed to invoke LLM after {max_retries} retries.")

# -- Agent State ---------------------------------------------------------------
from typing import Annotated, List
from typing_extensions import TypedDict
from langgraph.graph import MessagesState

class InvestDebateState(TypedDict):
    bull_history: str
    bear_history: str
    history: str
    current_response: str
    judge_decision: str
    count: int

class RiskDebateState(TypedDict):
    risky_history: str
    safe_history: str
    neutral_history: str
    history: str
    latest_speaker: str
    current_risky_response: str
    current_safe_response: str
    current_neutral_response: str
    judge_decision: str
    count: int

class AgentState(MessagesState):
    company_of_interest: str
    trade_date: str
    sender: str
    market_report: str
    sentiment_report: str
    news_report: str
    fundamentals_report: str
    investment_debate_state: InvestDebateState
    investment_plan: str
    trader_investment_plan: str
    risk_debate_state: RiskDebateState
    final_trade_decision: str
    portfolio_capital: float

    final_trade_decision: str
    portfolio_capital: float

# -- High-Performance Crypto Data Provider (CCXT) ---------------------------------
from typing import Annotated
from langchain_core.tools import tool
from langchain_community.tools.tavily_search import TavilySearchResults
from stockstats import wrap as stockstats_wrap
from bs4 import BeautifulSoup

from ccxt_provider import CryptoDataProvider
_provider = CryptoDataProvider()

# -- Tool 1: Crypto OHLCV data (CCXT) -------------------------------------------
# -- Tool 1: Market Data OHLCV ---------------------------------------------------
@tool
def get_yfinance_data(
    symbol: Annotated[str, "Ticker symbol (e.g. AAPL or BTC/USD)"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date:   Annotated[str, "End date   yyyy-mm-dd"],
) -> str:
    """Retrieve market price OHLCV data."""
    try:
        df = _provider.fetch_ohlcv_to_df(symbol)
        if df.empty:
            return f"No data found for '{symbol}'."
        return df.tail(15).to_csv()
    except Exception as e:
        return f"Error fetching market data: {e}"

# -- Tool 2: Technical indicators via stockstats (free, local) -----------------
@tool
def get_technical_indicators(
    symbol: Annotated[str, "Ticker symbol (e.g. AAPL or BTC/USD)"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date:   Annotated[str, "End date   yyyy-mm-dd"],
) -> str:
    """Compute MACD, RSI-14, Bollinger Bands, 50/200 SMA locally."""
    try:
        df = _provider.fetch_ohlcv_to_df(symbol, limit=200) # Get enough for averages
        if df.empty:
            return "No data to calculate indicators."
        stock_df = stockstats_wrap(df)
        indicators = stock_df[['macd', 'rsi_14', 'boll', 'boll_ub', 'boll_lb', 'close_50_sma', 'close_200_sma']]
        return indicators.tail(5).to_csv()
    except Exception as e:
        return f"Error calculating technical indicators: {e}"

# -- Tool 3: Company news via yfinance + Yahoo RSS (FREE, replaces Finnhub) ----
# Finnhub does not cover Indian (NSE) stocks well. yfinance news is free and
# covers RELIANCE.NS, TCS.NS etc. directly. Falls back to Finnhub if key exists.
@tool
def get_stock_news(ticker: str, start_date: str, end_date: str) -> str:
    """Get recent crypto project news and updates (free)."""
    try:
        # Treat as crypto ticker (e.g. BTC/USD or BTC-USD)
        clean_ticker = ticker.replace("/", "-").split("-")[0]
        
        # Primary: yfinance built-in news
        yf_ticker = yf.Ticker(f"{clean_ticker}-USD")
        news_items = []

        raw_news = getattr(yf_ticker, 'news', []) or []
        for item in raw_news[:6]:
            title   = item.get('title', item.get('headline', ''))
            summary = item.get('summary', item.get('description', ''))[:500]
            if title:
                news_items.append(f"Headline: {title}\nSummary: {summary}...")

        # Secondary: Global Crypto News RSS / Search Fallback
        if len(news_items) < 3:
            query = f"{clean_ticker} cryptocurrency project news updates bitcoinist coindesk"
            search_res = tavily_tool.invoke({"query": query})
            return str(search_res)

        # Secondary: Yahoo Finance RSS for Indian stocks
        if len(news_items) < 3:
            clean = ticker.split(".")[0]
            rss_urls = [
                f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=IN&lang=en-IN",
                f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}",
            ]
            for rss_url in rss_urls:
                try:
                    resp = requests.get(rss_url, timeout=6,
                                        headers={"User-Agent": "Mozilla/5.0"})
                    if resp.ok:
                        soup = BeautifulSoup(resp.text, "xml")
                        for item in soup.find_all("item")[:5]:
                            title   = item.find("title")
                            desc    = item.find("description")
                            t = title.text.strip()   if title else ""
                            d = desc.text.strip()[:500] if desc  else ""
                            if t and t not in [n.split("\n")[0].replace("Headline: ", "") for n in news_items]:
                                news_items.append(f"Headline: {t}\nSummary: {d}...")
                    if len(news_items) >= 5:
                        break
                except Exception:
                    pass

        # Tertiary fallback: Finnhub (only if key available)
        if len(news_items) < 2 and FINNHUB_KEY:
            try:
                import finnhub
                clean_ticker = ticker.split(".")[0]
                fh = finnhub.Client(api_key=FINNHUB_KEY)
                fh_news = fh.company_news(clean_ticker, _from=start_date, to=end_date)
                for n in fh_news[:5]:
                    news_items.append(f"Headline: {n['headline']}\nSummary: {n['summary']}")
            except Exception:
                pass

        return "\n\n".join(news_items[:6]) if news_items else "No recent news found via any source."
    except Exception as e:
        return f"Error fetching stock news: {e}"

# -- Tavily web search instance (free tier) ------------------------------------
tavily_tool = TavilySearchResults(max_results=3)

# -- Tool 4: Social media sentiment via Tavily search (free tier) --------------
@tool
def get_social_media_sentiment(ticker: str, trade_date: str) -> str:
    """Live web search for social media sentiment (X, Reddit, WallStreetBets)."""
    from config_manager import is_crypto
    if is_crypto(ticker):
        query = f"{ticker} crypto sentiment reddit twitter X.com CryptoCurrency discussion {trade_date}"
    else:
        query = f"{ticker} stock sentiment wallstreetbets reddit twitter X.com discussion {trade_date}"
    return tavily_tool.invoke({"query": query})

# -- Tool 5: Fundamental analysis via Tavily search (free tier) ----------------
@tool
def get_fundamental_analysis(ticker: str, trade_date: str) -> str:
    """Live web search for financials (Stocks) or tokenomics (Crypto)."""
    from config_manager import is_crypto
    if is_crypto(ticker):
        query = f"{ticker} crypto project tokenomics TVL total value locked developer activity github {trade_date}"
    else:
        query = f"{ticker} stock company financial health revenue earnings P/E ratio balance sheet {trade_date}"
    return tavily_tool.invoke({"query": query})

# -- Tool 6: Macroeconomic news via Tavily search (free tier) ------------------
@tool
def get_macroeconomic_news(trade_date: str) -> str:
    """Live web search for Global Macro, FED news, and market trends."""
    query = f"Global market macro news FED inflation interest rates market trends {trade_date}"
    return tavily_tool.invoke({"query": query})

# -- Toolkit -------------------------------------------------------------------
class Toolkit:
    def __init__(self, config):
        self.config                     = config
        self.get_yfinance_data          = get_yfinance_data
        self.get_technical_indicators   = get_technical_indicators
        self.get_stock_news             = get_stock_news          # replaces get_finnhub_news
        self.get_social_media_sentiment = get_social_media_sentiment
        self.get_fundamental_analysis   = get_fundamental_analysis
        self.get_macroeconomic_news     = get_macroeconomic_news

toolkit = Toolkit(config)
print("OK: Toolkit ready — all tools are free (Yahoo Finance, Tavily, RSS).")

# -----------------------------------------------------------------------------
# MEMORY — Local SentenceTransformers, zero cost, no API
# -----------------------------------------------------------------------------
import chromadb
from chromadb.utils import embedding_functions

class FinancialSituationMemory:
    def __init__(self, name, config):
        # all-MiniLM-L6-v2 runs on CPU, auto-downloads ~90MB on first use
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self.chroma_client = chromadb.Client(chromadb.config.Settings(allow_reset=True))
        self.situation_collection = self.chroma_client.create_collection(
            name=name, embedding_function=self.embedding_fn
        )

    def add_situations(self, situations_and_advice):
        if not situations_and_advice:
            return
        offset = self.situation_collection.count()
        ids            = [str(offset + i) for i, _ in enumerate(situations_and_advice)]
        situations     = [s for s, _ in situations_and_advice]
        recommendations = [r for _, r in situations_and_advice]
        self.situation_collection.add(
            documents=situations,
            metadatas=[{"recommendation": rec} for rec in recommendations],
            ids=ids,
        )

    def get_memories(self, current_situation, n_matches=1):
        if self.situation_collection.count() == 0:
            return []
        results = self.situation_collection.query(
            query_texts=[current_situation],
            n_results=min(n_matches, self.situation_collection.count()),
            include=["metadatas"],
        )
        return [{"recommendation": m["recommendation"]} for m in results["metadatas"][0]]

bull_memory         = FinancialSituationMemory("bull_memory",         config)
bear_memory         = FinancialSituationMemory("bear_memory",         config)
trader_memory       = FinancialSituationMemory("trader_memory",       config)
invest_judge_memory = FinancialSituationMemory("invest_judge_memory", config)
risk_manager_memory = FinancialSituationMemory("risk_manager_memory", config)
print("OK: Memory ready (local SentenceTransformers, no API key).")


# -----------------------------------------------------------------------------
# PART 2 — Analyst Team (ReAct pattern)
# -----------------------------------------------------------------------------
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

def create_analyst_node(llm, toolkit, system_message, tools, output_field):
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a helpful AI assistant collaborating with other assistants."
         " Use the provided tools to answer the question."
         " Tools available: {tool_names}.\n{system_message}"
         " Current date: {current_date}. Company: {ticker}."),
        MessagesPlaceholder(variable_name="messages"),
    ])
    prompt = prompt.partial(system_message=system_message)
    prompt = prompt.partial(tool_names=", ".join([t.name for t in tools]))
    llm_with_tools = llm.bind_tools(tools)   # LLaMA 3.x on Groq supports tool calling

    def analyst_node(state):
        p = prompt.partial(current_date=state["trade_date"], ticker=state["company_of_interest"])
        # STRICTOR: Remind the model again of its specific tools to avoid hallucinations
        p = p.partial(system_message=system_message + "\nCRITICAL: You MUST ONLY use the tools listed below. DO NOT attempt to call tools that are not in this list (e.g., NO 'brave_search', NO 'google', NO 'get_current_price'). Use ONLY the symbols provided (e.g., BTC/USD).")
        # Truncate history to avoid Groq TPM limits (keep first message + last 6)
        msgs = state.get("messages", [])
        if len(msgs) > 7:
            msgs = [msgs[0]] + msgs[-6:]
            
        result = safe_llm_invoke(llm_with_tools, msgs)
        report = "" if result.tool_calls else result.content
        # Sanitize report for terminal display
        report = sanitize_text(report)
        return {"messages": [result], output_field: report}
    return analyst_node

# Market Analyst — price + technical indicators
market_analyst_node = create_analyst_node(
    analyst_llm, toolkit,
    "You are a professional market analyst. "
    "Analyze the asset's price action, momentum, and volatility. "
    "If it is a stock, look for traditional technical patterns. If crypto, look for liquidity and volatility. "
    "STRICTLY report all prices and targets in USD. "
    "Use your tools to fetch historical data, then write a report with a summary table.",
    [toolkit.get_yfinance_data, toolkit.get_technical_indicators],
    "market_report",
)

# Social Media Analyst - public sentiment
social_analyst_node = create_analyst_node(
    analyst_llm, toolkit,
    "You are a crypto social media analyst. "
    "Search for investor discussions on Crypto-Twitter (X), Reddit (r/CryptoCurrency, etc.), and Discord. "
    "STRICTLY use USD. No mention of Indian markets. "
    "Write a report on public sentiment and 'hype' levels with a summary table.",
    [toolkit.get_social_media_sentiment],
    "sentiment_report",
)

# News Analyst - company news + macro (uses free tools only)
news_analyst_node = create_analyst_node(
    analyst_llm, toolkit,
    "You are a crypto news analyst. "
    "Gather recent crypto news, protocol updates, and global macro news (FED, Inflation, Bitcoin ETF flows). "
    "STRICTLY use USD. FORBIDDEN: NSE-style reporting. "
    "Compile a comprehensive report with a summary table.",
    [toolkit.get_stock_news, toolkit.get_macroeconomic_news],
    "news_report",
)

# Fundamentals Analyst - financial health
fundamentals_analyst_node = create_analyst_node(
    analyst_llm, toolkit,
    "You are a fundamental research analyst. "
    "For STOCKS: Research revenue, earnings, P/E ratio, and company roadmap. "
    "For CRYPTO: Research tokenomics, total value locked (TVL), and network security. "
    "STRICTLY report in USD. "
    "Write a detailed fundamental report with a summary table.",
    [toolkit.get_fundamental_analysis],
    "fundamentals_report",
)
print("OK: Analyst nodes created.")

# -- ReAct loop helper ---------------------------------------------------------
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage
from rich.console import Console
from rich.markdown import Markdown

console = Console()

ALL_TOOLS = [
    toolkit.get_yfinance_data,
    toolkit.get_technical_indicators,
    toolkit.get_stock_news,
    toolkit.get_social_media_sentiment,
    toolkit.get_fundamental_analysis,
    toolkit.get_macroeconomic_news,
]

def sanitize_text(text: str) -> str:
    """Helper to remove characters that break Windows legacy terminals (CP1252)."""
    if not text:
        return ""
    # Map common problematic characters to ASCII equivalents
    replacements = {
        '\u20b9': 'INR',
        '\u2500': '-',
        '\u2502': '|',
        '\u250c': '+',
        '\u2510': '+',
        '\u2514': '+',
        '\u2518': '+',
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text

def run_analyst(analyst_node_fn, state):
    # Manual tool mapping to avoid LangGraph ToolNode configuration issues
    tool_map = {tool.name: tool for tool in ALL_TOOLS}
    import time
    
    for _ in range(5):
        output = analyst_node_fn(state)
        ai_message = output["messages"][-1]
        state["messages"].append(ai_message)
        
        if hasattr(ai_message, "tool_calls") and ai_message.tool_calls:
            for tc in ai_message.tool_calls:
                name = tc["name"]
                args = tc["args"]
                func = tool_map.get(name)
                if func:
                    print(f"Executing tool: {name}")
                    obs = func.invoke(args)
                    # Truncate large tool outputs to prevent TPM overflow (approx 3000 chars ~ 750 tokens)
                    obs_str = str(obs)
                    if len(obs_str) > 3000:
                        obs_str = obs_str[:3000] + "... [TRUNCATED]"
                    
                    from langchain_core.messages import ToolMessage
                    t_msg = ToolMessage(content=obs_str, tool_call_id=tc["id"], name=name)
                    state["messages"].append(t_msg)
                else:
                    # Handle hallucinated tool name
                    print(f"WARN: Hallucinated tool '{name}'. Correcting model...")
                    from langchain_core.messages import ToolMessage
                    error_msg = f"Error: Tool '{name}' does not exist. Your ONLY valid tools are: {list(tool_map.keys())}. Please try again using ONLY these."
                    state["messages"].append(ToolMessage(content=error_msg, tool_call_id=tc["id"], name=name))
        else:
            return output
    return output


# -----------------------------------------------------------------------------
# PART 3 — Bull vs Bear Research Debate
# -----------------------------------------------------------------------------

def create_researcher_node(llm, memory, role_prompt, agent_name):
    def node(state):
        situation = (
            f"Market: {state['market_report']}\n"
            f"Sentiment: {state['sentiment_report']}\n"
            f"News: {state['news_report']}\n"
            f"Fundamentals: {state['fundamentals_report']}"
        )
        memories    = memory.get_memories(situation)
        memory_str  = "\n".join(m["recommendation"] for m in memories) or "No past memories."
        debate      = state["investment_debate_state"]

        prompt = (
            f"{role_prompt}\n\n"
            f"Current analysis:\n{situation}\n\n"
            f"Debate history:\n{debate['history']}\n\n"
            f"Opponent's last argument:\n{debate['current_response']}\n\n"
            f"Your past lessons:\n{memory_str}\n\n"
            "Make your argument conversationally."
        )
        response = safe_llm_invoke(llm, prompt)
        argument = f"{agent_name}: {response.content}"

        d = state["investment_debate_state"].copy()
        d["history"] += "\n" + argument
        if agent_name == "Bull Analyst":
            d["bull_history"] += "\n" + argument
        else:
            d["bear_history"] += "\n" + argument
        d["current_response"] = argument
        d["count"] += 1
        return {"investment_debate_state": d}
    return node

def create_research_manager(llm, memory):
    def node(state):
        prompt = (
            "As Research Manager, synthesise the Bull vs Bear debate and give a final "
            "Buy / Sell / Hold recommendation with a detailed rationale and action plan "
            "for the Trader.\n\n"
            f"Debate:\n{state['investment_debate_state']['history']}"
        )
        return {"investment_plan": safe_llm_invoke(llm, prompt).content}
    return node

bull_researcher_node  = create_researcher_node(quick_thinking_llm, bull_memory,
                            "You are the Bull Analyst. Argue FOR buying the stock. "
                            "Focus on growth, competitive advantage, positive signals. "
                            "Rebut the Bear's points specifically.", "Bull Analyst")
bear_researcher_node  = create_researcher_node(quick_thinking_llm, bear_memory,
                            "You are the Bear Analyst. Argue AGAINST buying the stock. "
                            "Focus on risks, overvaluation, macro headwinds. "
                            "Rebut the Bull's points specifically.", "Bear Analyst")
research_manager_node = create_research_manager(deep_thinking_llm, invest_judge_memory)
print("OK: Researcher and Research Manager nodes ready.")


# -----------------------------------------------------------------------------
# PART 4 — Trader + Risk Management
# -----------------------------------------------------------------------------
import functools

def create_trader(llm, memory):
    def node(state, name):
        prompt = (
            "You are a Trader Agent. Convert the investment plan into a concrete, "
            "actionable trading proposal. State entry price, position sizing, and stop-loss. "
            "End your response with exactly: 'FINAL TRANSACTION PROPOSAL: **BUY**', "
            "'FINAL TRANSACTION PROPOSAL: **SELL**', or 'FINAL TRANSACTION PROPOSAL: **HOLD**'.\n\n"
            f"Investment Plan:\n{state['investment_plan']}"
        )
        return {"trader_investment_plan": llm.invoke(prompt).content, "sender": name}
    return node

def create_risk_debator(llm, role_prompt, agent_name):
    def node(state):
        rs = state["risk_debate_state"]
        opp = []
        if agent_name != "Risky Analyst"   and rs["current_risky_response"]:
            opp.append(f"Risky:   {rs['current_risky_response']}")
        if agent_name != "Safe Analyst"    and rs["current_safe_response"]:
            opp.append(f"Safe:    {rs['current_safe_response']}")
        if agent_name != "Neutral Analyst" and rs["current_neutral_response"]:
            opp.append(f"Neutral: {rs['current_neutral_response']}")

        prompt = (
            f"{role_prompt}\n\n"
            f"Trader's plan:\n{state['trader_investment_plan']}\n\n"
            f"Debate so far:\n{rs['history']}\n\n"
            f"Opponents' last arguments:\n{chr(10).join(opp)}\n\n"
            "Critique or support the plan from your perspective."
        )
        response = safe_llm_invoke(llm, prompt).content
        nrs = rs.copy()
        nrs["history"]        += f"\n{agent_name}: {response}"
        nrs["latest_speaker"]  = agent_name
        if agent_name == "Risky Analyst":
            nrs["current_risky_response"]   = response
        elif agent_name == "Safe Analyst":
            nrs["current_safe_response"]    = response
        else:
            nrs["current_neutral_response"] = response
        nrs["count"] += 1
        return {"risk_debate_state": nrs}
    return node

def create_risk_manager(llm, memory):
    def node(state):
        prompt = (
            "You are the Portfolio Manager. Make the final, binding trading decision. "
            "Review the Trader's proposal and the Risk team's debate. "
            "Give a clear Buy / Sell / Hold verdict with brief justification.\n\n"
            f"Trader's Plan:\n{state['trader_investment_plan']}\n\n"
            f"Risk Debate:\n{state['risk_debate_state']['history']}"
        )
        return {"final_trade_decision": safe_llm_invoke(llm, prompt).content}
    return node

class StockAllocation(BaseModel):
    ticker: str = Field(description="NSE Ticker symbol")
    signal: str = Field(description="BUY, SELL, or HOLD")
    allocation_percentage: float = Field(description="Percentage of capital to allocate (0-100)")
    suggested_shares: int = Field(description="Calculated shares based on price and allocation")
    rationale: str = Field(description="Brief reason for this specific allocation")

class PortfolioAllocationReport(BaseModel):
    total_capital: float = Field(description="Total capital available for investment")
    allocations: List[StockAllocation] = Field(description="List of stock-specific allocations")
    unallocated_cash: float = Field(description="Remaining cash after allocations")
    summary: str = Field(description="Executive summary of the portfolio strategy")

def create_portfolio_advisor(llm):
    def node(results_list: List[dict], total_capital: float):
        reports_context = []
        for res in results_list:
            reports_context.append(
                f"TICKER: {res['ticker']}\n"
                f"VERDICT: {res['decision']}\n"
                f"TRADER PLAN: {res['trader_plan']}\n"
                "-----------------------------------"
            )
        
        prompt = (
            "You are the Senior Portfolio Strategist. Review the individual analyses for these stocks. "
            "Suggest how to allocate the total capital among them. "
            "Prioritize BUY signals with strong conviction. If a stock is a HOLD or SELL, allocate 0% or very little. "
            f"Total Capital available: INR {total_capital}\n\n"
            "Analyst Reports:\n" + "\n".join(reports_context)
        )
        # Use safe_llm_invoke on the structured chain
        chain = llm.with_structured_output(PortfolioAllocationReport)
        return safe_llm_invoke(chain, prompt)
    return node

trader_node_fn    = create_trader(quick_thinking_llm, trader_memory)
trader_node       = functools.partial(trader_node_fn, name="Trader")

risky_node        = create_risk_debator(quick_thinking_llm,
                        "You are the Risky Risk Analyst. Push for maximum returns. "
                        "Advocate bold, aggressive position sizing.", "Risky Analyst")
safe_node         = create_risk_debator(quick_thinking_llm,
                        "You are the Safe Risk Analyst. Prioritise capital preservation. "
                        "Prefer tight stop-losses and small initial positions.", "Safe Analyst")
neutral_node      = create_risk_debator(quick_thinking_llm,
                        "You are the Neutral Risk Analyst. Provide a balanced view, "
                        "weighing upside vs downside objectively.", "Neutral Analyst")
risk_manager_node = create_risk_manager(deep_thinking_llm, risk_manager_memory)

# -- Extraction Helpers --------------------------------------------------------
class SignalProcessor:
    def __init__(self, llm):
        self.llm = llm

    def process_signal(self, text: str) -> str:
        prompt = [
            ("system", "Extract the final investment decision from the text. "
                       "Reply with exactly one word: BUY, SELL, or HOLD."),
            ("human", text),
        ]
        result = safe_llm_invoke(self.llm, prompt).content.strip().upper()
        # Clean potential markdown or debris from LLM response
        for s in ("BUY", "SELL", "HOLD"):
            if s in result: return s
        return "ERROR_UNPARSABLE_SIGNAL"

signal_proc  = SignalProcessor(quick_thinking_llm)


# -----------------------------------------------------------------------------
# PART 5 — Full LangGraph Workflow
# -----------------------------------------------------------------------------
from langchain_core.messages import RemoveMessage
from langgraph.graph import StateGraph, END

class ConditionalLogic:
    def __init__(self, max_debate_rounds, max_risk_discuss_rounds):
        self.max_debate_rounds        = max_debate_rounds
        self.max_risk_discuss_rounds  = max_risk_discuss_rounds

    def should_continue_analyst(self, state: AgentState):
        # If the last message contains tool calls → call tools; else → continue
        return "tools" if tools_condition(state) == "tools" else "continue"

    def should_continue_debate(self, state: AgentState) -> str:
        deb = state["investment_debate_state"]
        if deb["count"] >= 2 * self.max_debate_rounds:
            return "Research Manager"
        return "Bear Researcher" if deb["current_response"].startswith("Bull") else "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        rs = state["risk_debate_state"]
        if rs["count"] >= 3 * self.max_risk_discuss_rounds:
            return "Risk Judge"
        spk = rs["latest_speaker"]
        if spk == "Risky Analyst":  return "Safe Analyst"
        if spk == "Safe Analyst":   return "Neutral Analyst"
        return "Risky Analyst"

def _msg_clear_node(state):
    """Clear messages between analysts to prevent context bleed."""
    return {
        "messages": [RemoveMessage(id=m.id) for m in state["messages"]]
                   + [HumanMessage(content="Continue")]
    }

cl = ConditionalLogic(
    max_debate_rounds=config["max_debate_rounds"],
    max_risk_discuss_rounds=config["max_risk_discuss_rounds"],
)

tool_node_graph = ToolNode(ALL_TOOLS)

wf = StateGraph(AgentState)

# -- Nodes ---------------------------------------------------------------------
wf.add_node("Market Analyst",       market_analyst_node)
wf.add_node("Msg Clear 1",          _msg_clear_node)
wf.add_node("Social Analyst",       social_analyst_node)
wf.add_node("Msg Clear 2",          _msg_clear_node)
wf.add_node("News Analyst",         news_analyst_node)
wf.add_node("Msg Clear 3",          _msg_clear_node)
wf.add_node("Fundamentals Analyst", fundamentals_analyst_node)

# -- Each analyst gets its OWN dedicated tool node to avoid multi-edge conflicts
wf.add_node("tools_market",      ToolNode(ALL_TOOLS))
wf.add_node("tools_social",      ToolNode(ALL_TOOLS))
wf.add_node("tools_news",        ToolNode(ALL_TOOLS))
wf.add_node("tools_fundamentals",ToolNode(ALL_TOOLS))

wf.add_node("Bull Researcher",   bull_researcher_node)
wf.add_node("Bear Researcher",   bear_researcher_node)
wf.add_node("Research Manager",  research_manager_node)
wf.add_node("Trader",            trader_node)
wf.add_node("Risky Analyst",     risky_node)
wf.add_node("Safe Analyst",      safe_node)
wf.add_node("Neutral Analyst",   neutral_node)
wf.add_node("Risk Judge",        risk_manager_node)

# -- Edges ---------------------------------------------------------------------
wf.set_entry_point("Market Analyst")

# Market Analyst ReAct loop → own tool node
wf.add_conditional_edges("Market Analyst", cl.should_continue_analyst,
                          {"tools": "tools_market", "continue": "Msg Clear 1"})
wf.add_edge("tools_market", "Market Analyst")
wf.add_edge("Msg Clear 1", "Social Analyst")

# Social Analyst ReAct loop → own tool node
wf.add_conditional_edges("Social Analyst", cl.should_continue_analyst,
                          {"tools": "tools_social", "continue": "Msg Clear 2"})
wf.add_edge("tools_social", "Social Analyst")
wf.add_edge("Msg Clear 2", "News Analyst")

# News Analyst ReAct loop → own tool node
wf.add_conditional_edges("News Analyst", cl.should_continue_analyst,
                          {"tools": "tools_news", "continue": "Msg Clear 3"})
wf.add_edge("tools_news", "News Analyst")
wf.add_edge("Msg Clear 3", "Fundamentals Analyst")

# Fundamentals Analyst ReAct loop → own tool node
wf.add_conditional_edges("Fundamentals Analyst", cl.should_continue_analyst,
                          {"tools": "tools_fundamentals", "continue": "Bull Researcher"})
wf.add_edge("tools_fundamentals", "Fundamentals Analyst")

# Research debate loop
wf.add_conditional_edges("Bull Researcher", cl.should_continue_debate)
wf.add_conditional_edges("Bear Researcher", cl.should_continue_debate)
wf.add_edge("Research Manager", "Trader")

# Risk debate loop
wf.add_edge("Trader", "Risky Analyst")
wf.add_conditional_edges("Risky Analyst",   cl.should_continue_risk_analysis)
wf.add_conditional_edges("Safe Analyst",    cl.should_continue_risk_analysis)
wf.add_conditional_edges("Neutral Analyst", cl.should_continue_risk_analysis)
wf.add_edge("Risk Judge", END)

trading_graph = wf.compile()

try:
    from IPython.display import Image, display
    display(Image(trading_graph.get_graph().draw_png()))
except Exception as e:
    print(f"   (Graph visualisation skipped: {e})")


# -----------------------------------------------------------------------------
# FINAL EXECUTION — Multi-Ticker Portfolio Suggestion
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import time

    portfolio_advisor = create_portfolio_advisor(deep_thinking_llm)
    all_ticker_results = []
    macro_news_context = toolkit.get_macroeconomic_news.invoke({"trade_date": config["TRADE_DATE"]})

    print(f"\n[bold green]>>> STARTING PORTFOLIO ANALYSIS FOR {len(config['TICKER_LIST'])} STOCKS <<<[/bold green]")
    print(f"Target Date: {config['TRADE_DATE']} | Capital: INR {config['PORTFOLIO_CAPITAL']}")

    for ticker in config["TICKER_LIST"]:
        print(f"\n\n{'='*60}")
        print(f" ANALYSING: {ticker}")
        print(f"{'='*60}")
        
        # 1. Manual Analyst Nodes (Sequential) - using shared macro if possible
        st = AgentState(
            messages=[HumanMessage(content=f"Analyse {ticker} for trading on {config['TRADE_DATE']}")],
            company_of_interest=ticker,
            trade_date=config["TRADE_DATE"],
            portfolio_capital=config["PORTFOLIO_CAPITAL"],
            investment_debate_state=InvestDebateState(history="", current_response="", count=0, bull_history="", bear_history="", judge_decision=""),
            risk_debate_state=RiskDebateState(history="", latest_speaker="", count=0, current_risky_response="", current_safe_response="", current_neutral_response="", risky_history="", safe_history="", neutral_history="", judge_decision=""),
        )
        
        print(f"RUNning: Market Analyst...")
        st.update(run_analyst(market_analyst_node, st))
        
        print(f"RUNning: Social Analyst...")
        st.update(run_analyst(social_analyst_node, st))
        
        # Inject Macro news to skip the tool call if desired, or just run it (it's free)
        print(f"RUNning: News Analyst...")
        st.update(run_analyst(news_analyst_node, st))
        
        print(f"RUNning: Fundamentals Analyst...")
        st.update(run_analyst(fundamentals_analyst_node, st))
        
        # 2. Sequential Debate (Bull/Bear)
        print("RUNning: Researcher Debate...")
        for _ in range(config["max_debate_rounds"]):
            st.update(bull_researcher_node(st))
            st.update(bear_researcher_node(st))
        
        st.update(research_manager_node(st))
        console.print("\n[bold cyan]-- Investment Plan --[/bold cyan]")
        console.print(Markdown(sanitize_text(st["investment_plan"][:500] + "..."))) # Truncate for console
        
        # 3. Trader + Risk
        st.update(trader_node(st))
        for _ in range(config["max_risk_discuss_rounds"]):
            st.update(risky_node(st))
            st.update(safe_node(st))
            st.update(neutral_node(st))
        
        st.update(risk_manager_node(st))
        
        # 4. Extract Signal
        decision_text = st["final_trade_decision"]
        signal = signal_proc.process_signal(decision_text)
        
        all_ticker_results.append({
            "ticker": ticker,
            "decision": decision_text,
            "signal": signal,
            "trader_plan": st["trader_investment_plan"]
        })
        
        print(f"FINISH: Result for {ticker}: {signal}")
        
        # Respect rate limits between stocks
        if ticker != config["TICKER_LIST"][-1]:
            print("Waiting 10 seconds for Groq rate limit reset...")
            time.sleep(10)

    # 5. Final Portfolio Synthesis
    print("\nRUNning: Final Portfolio Allocation...")
    final_portfolio = portfolio_advisor(all_ticker_results, config["PORTFOLIO_CAPITAL"])

    print("\n" + "="*60)
    print("      PROPOSED PORTFOLIO SUGGESTIONS")
    print("="*60)
    print(f"Initial Capital: INR {final_portfolio.total_capital:,.2f}")
    print(f"Unallocated:     INR {final_portfolio.unallocated_cash:,.2f}")
    print("-" * 60)

    for alloc in final_portfolio.allocations:
        print(f"STOCK: {alloc.ticker:12} | {alloc.signal:5} | {alloc.allocation_percentage:5.1f}% | {alloc.suggested_shares:4} Shares")
        print(f"Rationale: {sanitize_text(alloc.rationale)}\n")

    print("-" * 60)
    print(f"SUMMARY: {sanitize_text(final_portfolio.summary)}")
    print("="*60)
    print("OK: All done.")
