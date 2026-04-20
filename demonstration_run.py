from autonomous_trading_system import AutonomousTradingSystem
from rich.console import Console

console = Console()

def run_demo():
    console.print("[bold green]=== END-TO-END DEMONSTRATION RUN ===[/bold green]")
    system = AutonomousTradingSystem()
    
    # We will test 1 Crypto and 1 Stock to show the "Multi-Market" logic
    test_symbols = ["BTC/USD", "NVDA"]
    
    console.print(f"Starting analysis for: {', '.join(test_symbols)}")
    
    # Run a LIGHT cycle (Technical + Decision) to keep it fast for the demo
    results = system.run_cycle(test_symbols, "DEMO CYCLE", deep_analysis=False)
    
    console.print("\n[bold yellow]--- FINAL DEMO RESULTS ---[/bold yellow]")
    for res in results:
        console.print(f"Asset: [bold]{res['ticker']}[/bold] | Signal: [bold]{res['signal']}[/bold]")

    # Execute the signals using our new Local Virtual Broker
    if results:
        console.print("\n[bold cyan]Triggering Local Virtual Execution...[/bold cyan]")
        system.executor.execute_signals(results)
    
    console.print("\n[bold green]Demo Complete. Your 'virtual_portfolio.json' has been updated![/bold green]")

if __name__ == "__main__":
    run_demo()
