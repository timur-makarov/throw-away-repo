import unittest

import calc


class CalcTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(calc.add(2, 3), 5)

    def test_mul(self):
        self.assertEqual(calc.mul(2, 3), 6)

    def test_sub(self):
        self.assertEqual(calc.sub(5, 3), 2)
        self.assertEqual(calc.sub(3, 5), -2)

    def test_div(self):
        self.assertEqual(calc.div(6, 3), 2)
        self.assertEqual(calc.div(1, 4), 0.25)

    def test_div_by_zero_is_a_calc_error(self):
        with self.assertRaises(calc.CalcError):
            calc.div(1, 0)

    def test_power(self):
        self.assertEqual(calc.power(2, 10), 1024)
        self.assertEqual(calc.power(2, -1), 0.5)


if __name__ == "__main__":
    unittest.main()
