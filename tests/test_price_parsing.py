import unittest

from app import parse_optional_csv_price


class PriceParsingTests(unittest.TestCase):
    def test_accepts_philippine_currency_formats(self):
        accepted_prices = {
            "₱83,700.00": 83700.0,
            "?83,700.00": 83700.0,
            "₱ 2,950.00": 2950.0,
            "PHP 3,050.00": 3050.0,
            "Php 2,280.00": 2280.0,
            "21,050.00": 21050.0,
            "10500": 10500.0,
            "₱\u00a027,400.00": 27400.0,
            45500: 45500.0,
        }

        for value, expected in accepted_prices.items():
            with self.subTest(value=value):
                self.assertEqual(parse_optional_csv_price(value), expected)

    def test_blank_and_project_prices_remain_unpriced(self):
        for value in ("", None, "-", "N/A", "Project pricing", "For quotation"):
            with self.subTest(value=value):
                self.assertIsNone(parse_optional_csv_price(value))

    def test_negative_and_invalid_prices_are_not_imported(self):
        for value in ("-1", "₱-2,950.00", "not a price", "83?700.00"):
            with self.subTest(value=value):
                self.assertIsNone(parse_optional_csv_price(value))


if __name__ == "__main__":
    unittest.main()
