import unittest
import numpy as np
from indicators import TickerState

class TestTickerState(unittest.TestCase):
    def test_incremental_obv_and_tsi(self):
        state = TickerState("TEST_TICKER", max_window=50)
        prices = [100.0, 102.0, 101.0, 103.0, 105.0]
        volumes = [1000, 1500, 1200, 2000, 2500]

        for p, v in zip(prices, volumes):
            state.update(p, v)

        self.assertEqual(len(state.closes), 5)
        # OBV expected calculation:
        # candle 0: init -> 0
        # candle 1: 102 > 100 -> +1500
        # candle 2: 101 < 102 -> -1200 => 300
        # candle 3: 103 > 101 -> +2000 => 2300
        # candle 4: 105 > 103 -> +2500 => 4800
        self.assertEqual(state.obv, 4800.0)

    def test_sliding_window_max_len(self):
        state = TickerState("TEST_TICKER", max_window=20)
        for i in range(50):
            state.update(100.0 + i, 1000 + i)

        self.assertEqual(len(state.closes), 20)
        self.assertEqual(len(state.volumes), 20)
        self.assertEqual(len(state.obv_history), 20)

    def test_check_pattern_short_circuit(self):
        state = TickerState("TEST_TICKER", max_window=50)

        # Pre-warm state with low volume
        np.random.seed(42)
        price = 100.0
        for _ in range(40):
            price += float(np.random.normal(0, 0.05))
            state.update(price, 50000)

        # Before spike, check_pattern should return False (volume low)
        self.assertFalse(state.check_pattern())

        # Now simulate consolidation + TSI < 10 + OBV > SMA + Volume spike
        state.volumes[-1] = 150000  # volume spike
        state.tsi = -5.0            # TSI < 10
        state.obv = 1000000.0       # High OBV
        state.obv_history[-1] = 1000000.0

        # Now check pattern should pass
        self.assertTrue(state.check_pattern())

if __name__ == "__main__":
    unittest.main()
