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


if __name__ == "__main__":
    unittest.main()
