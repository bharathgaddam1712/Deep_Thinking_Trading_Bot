import numpy as np
import collections

class SMACrossoverStrategy:
    def __init__(self, short_window: int = 5, long_window: int = 20):
        self.short_window = short_window
        self.long_window = long_window
        # Use deque for fast O(1) appends and automatic length bounding
        self.prices = collections.deque(maxlen=long_window)
        self.last_short_sma = None
        self.last_long_sma = None

    def update_price_and_check_signal(self, price: float) -> str | None:
        """
        Updates the internal price queue and evaluates the MA crossover.
        Returns 'BUY' if the short SMA crosses above the long SMA.
        Returns 'SELL' if the short SMA crosses below the long SMA.
        Otherwise it returns None.
        """
        self.prices.append(price)

        if len(self.prices) < self.long_window:
            return None

        # Convert to numpy array for fast vectorized operations
        prices_arr = np.array(self.prices)

        # Calculate current SMAs
        current_short_sma = np.mean(prices_arr[-self.short_window:])
        current_long_sma = np.mean(prices_arr)

        signal = None

        if self.last_short_sma is not None and self.last_long_sma is not None:
            # Check for crossovers
            if self.last_short_sma <= self.last_long_sma and current_short_sma > current_long_sma:
                signal = "BUY"
            elif self.last_short_sma >= self.last_long_sma and current_short_sma < current_long_sma:
                signal = "SELL"

        self.last_short_sma = current_short_sma
        self.last_long_sma = current_long_sma

        return signal
