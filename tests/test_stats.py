import unittest

import calc
from calc import stats


class StatsTest(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(stats.mean([1, 2, 3]), 2)

    def test_the_mean_of_no_numbers_is_a_calc_error(self):
        with self.assertRaises(calc.CalcError):
            stats.mean([])


if __name__ == "__main__":
    unittest.main()
