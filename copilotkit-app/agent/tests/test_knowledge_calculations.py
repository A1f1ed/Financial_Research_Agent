"""Financial compatibility and exact Decimal arithmetic, no provider calls."""
import unittest
from uuid import uuid4
from pydantic import ValidationError
from src.knowledge.calculations import CalculationInput, FigureInput, arithmetic, check_unit, numeric_tokens, numeric_value, unit_spans


def figure(value="100", **changes):
    return {"value":value,"unit":"thousands","currency":"CNY","subject":"Synthetic company",
        "basis":"Consolidated","period_type":"duration","period_start":"2026-01-01","period_end":"2026-06-30",
        "metric":"Operating cash flow",**changes}


def request(operation,count=2,**values):
    return CalculationInput(operation=operation,figure_ids=[uuid4() for _ in range(count)],**values)


class CalculationTests(unittest.TestCase):
    def test_decimal_scale_conversion_does_not_change_currency(self):
        result=arithmetic(request("convert",1,target_unit="millions"),[figure("1234.56")])
        self.assertEqual((result["value"],result["currency"],result["unit"]),("1.23456","CNY","millions"))
        self.assertEqual(arithmetic(request("sum"),[figure("0.1"),figure("0.2")])["value"],"0.3")
        self.assertEqual(arithmetic(request("sum",signs=[1,-1]),[figure("100"),figure("40")])["value"],"60")

    def test_ratios_align_units_and_do_not_round_inputs(self):
        result=arithmetic(request("ratio_percent"),[figure("1000"),figure("2",unit="millions",metric="Net profit")])
        self.assertEqual(result["value"],"50");self.assertIsNone(result["currency"])
        self.assertEqual(arithmetic(request("difference"),[figure("100"),figure("0.05",unit="millions")])["value"],"50")

    def test_scope_currency_period_and_dimension_mismatches_fail(self):
        for changed in ({"currency":"HKD"},{"subject":"Another company"},{"basis":"Parent only"},
                        {"period_end":"2026-03-31"},{"period_type":"as_at"},{"unit":"percent","currency":None}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                arithmetic(request("ratio_percent"),[figure(),figure(**changed)])

    def test_zero_negative_and_noncomparable_growth_do_not_get_a_percentage(self):
        previous=figure("80",period_start="2025-01-01",period_end="2025-06-30")
        self.assertEqual(arithmetic(request("year_over_year_change"),[figure(),previous])["value"],"25")
        self.assertEqual(arithmetic(request("difference"),[figure(),previous])["value"],"20")
        for old in (figure("0",period_start="2025-01-01",period_end="2025-06-30"),
                    {**previous,"value":"-80"},{**previous,"metric":"Revenue"},
                    {**previous,"period_start":"2025-01-01","period_end":"2025-12-31"},figure("80")):
            with self.subTest(old=old),self.assertRaises(ValueError):arithmetic(request("percentage_change"),[figure(),old])
        with self.assertRaises(ValueError):arithmetic(request("ratio_percent"),[figure(),figure("0")])

    def test_generic_change_is_not_mislabeled_year_over_year(self):
        old=figure("80",period_start="2025-07-01",period_end="2025-12-31")
        self.assertEqual(arithmetic(request("percentage_change"),[figure(),old])["value"],"25")
        with self.assertRaises(ValueError):arithmetic(request("year_over_year_change"),[figure(),old])

    def test_percentage_points_are_distinct_from_percentage_change(self):
        result=arithmetic(request("difference"),[figure("17.4",unit="percent",currency=None),figure("17",unit="percent",currency=None)])
        self.assertEqual((result["value"],result["unit"]),("0.4","percentage_points"))
        with self.assertRaises(ValueError):arithmetic(request("convert",1,target_unit="ones"),[figure("17",unit="percent",currency=None)])

    def test_exact_units_do_not_accept_partial_or_ambiguous_currency(self):
        self.assertEqual([u["quote"] for u in unit_spans("100 千元人民币，100 RMB millions")],["千元人民币","RMB millions"])
        self.assertEqual(unit_spans("十亿元人民币 and RMB millionaires"),[])
        for text,currency,unit in [("人民幣千元","CNY","thousands"),("千元人民币","CNY","thousands"),("RMB’000","CNY","thousands"),("US$ million","USD","millions")]:
            check_unit(text,currency,unit)
        for text,currency,unit in [("人民币百万元","CNY","ones"),("RMB'000","CNY","millions"),("$ million","USD","millions")]:
            with self.subTest(text=text),self.assertRaises(ValueError):check_unit(text,currency,unit)

    def test_numeric_source_tokens_cannot_be_partial_or_nonfinite(self):
        tokens=numeric_tokens("Synthetic: 1,234.50\n(12.25)\n17.4%\n-5.0\n")
        self.assertEqual([t["text"] for t in tokens],["1,234.50","(12.25)","17.4%","-5.0"])
        self.assertEqual(str(numeric_value("(12.25)")),"-12.25")
        for value in ("NaN","Infinity","1e20","12,34","100000000000000000000000000"):
            with self.subTest(value=value),self.assertRaises(ValueError):numeric_value(value)

    def test_contracts_require_explicit_review_and_bounded_ordered_inputs(self):
        with self.assertRaises(ValidationError):CalculationInput(operation="difference",figure_ids=[uuid4()])
        repeated=uuid4()
        with self.assertRaises(ValidationError):CalculationInput(operation="sum",figure_ids=[repeated,repeated])
        with self.assertRaises(ValidationError):FigureInput(search_id=uuid4(),citation_id="K1",value_start=0,value_text="100",
            metric="Cash flow",unit="thousands",currency="CNY",unit_page_number=1,unit_start=0,unit_quote="RMB'000",
            period_type="duration",period_start="2026-01-01",period_end="2026-06-30",basis="Consolidated",reason="not confirmed")
