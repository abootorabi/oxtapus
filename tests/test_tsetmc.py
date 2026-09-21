import unittest
from unittest.mock import patch

from oxtapus.models.tsetmc import InsInfo, MarketWatch
from oxtapus.tsetmc import MWSections, TSETMC, _classify_market_watch


def market_watch_record(
    ins_code: str,
    ins_id: str,
    symbol: str,
    instrument_type: str | int | None = None,
    market_code: int | None = None,
):
    record = {
        "insCode": ins_code,
        "insID": ins_id,
        "lva": symbol,
        "lvc": symbol,
        "eps": 0,
        "pe": 0,
        "pmd": 0,
        "pmo": 0,
        "pf": 0,
        "pmx": 0,
        "pmn": 0,
        "pdv": 0,
        "pcl": 0,
        "py": 0,
        "qtc": 0,
        "qtj": 0,
        "ztt": 0,
        "pMax": 0,
        "pMin": 0,
        "ztd": 0,
        "bv": 0,
        "hEven": 0,
        "blDs": [
            {
                "n": 1,
                "zmd": 0,
                "qmd": 0,
                "pmd": 0,
                "pmo": 0,
                "qmo": 0,
                "zmo": 0,
            }
        ],
    }
    if instrument_type is not None:
        record["yVal"] = instrument_type
    if market_code is not None:
        record["flow"] = market_code
    return record


def client_type_record(ins_code: str):
    return {
        "insCode": ins_code,
        "buy_I_Volume": 0,
        "buy_N_Volume": 0,
        "buy_CountI": 0,
        "buy_CountN": 0,
        "sell_I_Volume": 0,
        "sell_N_Volume": 0,
        "sell_CountI": 0,
        "sell_CountN": 0,
    }


class TestMarketWatchClassification(unittest.TestCase):
    def test_classifies_instrument_types(self):
        cases = {
            "300": MWSections.stock,
            "313": MWSections.stock,
            "309": MWSections.ifb_paye,
            "307": MWSections.mortgage,
            "404": MWSections.cum_right,
            "706": MWSections.bond,
            "321": MWSections.options,
            "304": MWSections.futures,
            "380": MWSections.etf,
            "803": MWSections.commodity,
        }

        for instrument_type, expected in cases.items():
            with self.subTest(instrument_type=instrument_type):
                self.assertEqual(
                    _classify_market_watch(instrument_type, "UNKNOWN"), expected
                )

    def test_classifies_legacy_isin_prefixes(self):
        cases = {
            "IRO1AKOZ0001": MWSections.stock,
            "IRO7TEST0001": MWSections.ifb_paye,
            "IRO6TEST0001": MWSections.mortgage,
            "IRR3PGOP0101": MWSections.cum_right,
            "IRB3TEST0001": MWSections.bond,
            "IRO9TEST0001": MWSections.options,
            "IRO4TEST0001": MWSections.futures,
            "IRT1TEST0001": MWSections.etf,
            "IRBKTEST0001": MWSections.commodity,
            "IRK1TEST0001": MWSections.commodity,
        }

        for ins_id, expected in cases.items():
            with self.subTest(ins_id=ins_id):
                self.assertEqual(_classify_market_watch(None, ins_id), expected)

    def test_instrument_type_takes_precedence_over_isin(self):
        self.assertEqual(
            _classify_market_watch("400", "IRO1TEST0001"), MWSections.cum_right
        )
        self.assertIsNone(_classify_market_watch("999", "IRO1TEST0001"))

    def test_unknown_instrument_is_excluded(self):
        self.assertIsNone(_classify_market_watch(None, "UNKNOWN"))
        self.assertIsNone(_classify_market_watch(None, None))


class TestMarketWatchModels(unittest.TestCase):
    def test_market_watch_optional_fields(self):
        legacy = MarketWatch.model_validate(
            market_watch_record("1", "IRO1AKOZ0001", "آكو3")
        )
        current = MarketWatch.model_validate(
            market_watch_record("2", "IRR1RIIR0101", "خريختح", "400", 1)
        )

        self.assertIsNone(legacy.instrument_type)
        self.assertIsNone(legacy.market_code)
        self.assertEqual(current.instrument_type, "400")
        self.assertEqual(current.market_code, 1)

    def test_market_watch_normalizes_numeric_instrument_type(self):
        current = MarketWatch.model_validate(
            market_watch_record("1", "IRB3TEST0001", "bond", 301, 2)
        )

        self.assertEqual(current.instrument_type, "301")

    def test_ins_info_declares_optional_instrument_type(self):
        field = InsInfo.model_fields["instrument_type"]

        self.assertEqual(field.alias, "yVal")
        self.assertIsNone(field.default)


class TestMarketWatchFiltering(unittest.TestCase):
    def test_mw_filters_new_response_and_keeps_legacy_stock(self):
        records = [
            market_watch_record("1", "IRO1AKOZ0001", "آكو3"),
            market_watch_record("2", "IRR1RIIR0101", "خريختح", "400", 1),
            market_watch_record("3", "IRR3PGOP0101", "تفارسح", "403", 2),
            market_watch_record("4", "IRR5MOMS0101", "مهرمامح", "401", 2),
        ]
        client_types = [client_type_record(record["insCode"]) for record in records]

        def request(url, response="json"):
            if "GetMarketWatch" in url:
                return [{"marketwatch": records}]
            return [{"clientTypeAllDto": client_types}]

        tsetmc = TSETMC()
        with patch.object(tsetmc, "requests", side_effect=request):
            result = tsetmc.mw(MWSections.stock)

        self.assertEqual(result["symbol"].to_list(), ["آكو3"])
        self.assertIn("instrument_type", result.columns)
        self.assertIn("market_code", result.columns)
        self.assertEqual(result["instrument_type"].to_list(), [None])
        self.assertEqual(result["market_code"].to_list(), [None])

    def test_mw_keeps_union_of_requested_sections(self):
        records = [
            market_watch_record("1", "IRO1TEST0001", "stock", 300, 1),
            market_watch_record("2", "IRT1TEST0001", "fund", "305", 2),
            market_watch_record("3", "IRB3TEST0001", "bond", "301", 2),
        ]
        client_types = [client_type_record(record["insCode"]) for record in records]

        def request(url, response="json"):
            if "GetMarketWatch" in url:
                return [{"marketwatch": records}]
            return [{"clientTypeAllDto": client_types}]

        tsetmc = TSETMC()
        with patch.object(tsetmc, "requests", side_effect=request):
            result = tsetmc.mw([MWSections.stock, MWSections.etf])

        self.assertEqual(result["symbol"].to_list(), ["stock", "fund"])


if __name__ == "__main__":
    unittest.main()
