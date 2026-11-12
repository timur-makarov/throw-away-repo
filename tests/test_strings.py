import unittest

from calc import strings


class StringsTest(unittest.TestCase):
    def test_shout(self):
        self.assertEqual(strings.shout("ab"), "AB!")


if __name__ == "__main__":
    unittest.main()
