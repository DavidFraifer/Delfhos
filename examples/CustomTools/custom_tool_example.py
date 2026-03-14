"""Example: creating custom tools with @tool only."""

import sys
import os

# Add the local package to the path if running directly from source
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from delfhos import Agent, tool


@tool(kind="read")
async def get_weather(location: str) -> str:
    """Mock weather API call"""
    weather_data = {
        "New York": "Sunny, 25°C",
        "London": "Rainy, 15°C",
        "Tokyo": "Cloudy, 22°C"
    }
    return weather_data.get(location, "Unknown location")

@tool(kind="read")
async def get_stock_price(ticker: str) -> str:
    """Fetch the current stock price for a given ticker symbol."""
    prices = {
        "AAPL": "$150.00",
        "GOOG": "$2800.00",
        "MSFT": "$300.00"
    }
    return f"The current price of {ticker} is {prices.get(ticker.upper(), 'Unknown')}"


def main():
    # Initialize the agent with our custom tools
    # NOTE: In reality, you'd also include Connections like GmailConnection, etc.
    agent = Agent(
        tools=[get_weather, get_stock_price],
        confirm="read",
        system_prompt="You are a helpful assistant that can fetch weather and stock prices."
    )
    
    print("\n--- Running Agent ---")
    
    # Run the agent
    agent.start()
    
    print("\nPrompt: 'What is the weather in London and how much is Apple stock?'")
    agent.run("What is the weather in London and how much is Apple stock?", timeout=120)

    agent.stop()


if __name__ == "__main__":
    main()
