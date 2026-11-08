import unittest
from src.evaluations.scoring import assess,aggregate,percentile
from src.evaluations.contracts import DatasetInput,RunOptions

class ScoringTests(unittest.TestCase):
    def test_imported_complex_rules_are_preserved_but_not_silently_scored(self):
        from uuid import uuid4
        from src.evaluations.imports import ImportRequest,import_dataset
        doc=str(uuid4())
        source={"version":"synthetic-contract", "split_policy":{},"default_scope":{"as_of":"2026-10-31T23:59:59+08:00"},
            "cases":[{"id":"synthetic-acceptance","category":"financial","split":"acceptance","question":"Explain source units", "evidence":{"synthetic-original":[2]},"expected":{"values":{"protected":"CANARY_REFERENCE"}},"basis":"synthetic human review"}]}
        imported=import_dataset(ImportRequest(payload=source,source_documents={"synthetic-original":doc}))
        case=imported.cases[0].model_dump(mode="json")
        self.assertEqual(case["partition"],"acceptance")
        self.assertEqual(case["expected"]["manual_reference"]["original_expected"]["values"]["protected"],"CANARY_REFERENCE")
        result=assess(case,{"citations":[{"document_id":doc,"page_number":2}]})
        self.assertFalse(result["scored"]);self.assertFalse(result["passed"])
        with self.assertRaises(ValueError):import_dataset(ImportRequest(payload=source))
    def test_missing_data_is_unknown_not_zero_and_skips_are_counted(self):
        result=aggregate([{"status":"passed","elapsed_ms":10},{"status":"unsupported"},{"status":"timeout","elapsed_ms":100}])
        self.assertAlmostEqual(result["pass_rate_all"],1/3)
        self.assertIsNone(result["recall_at_5"]);self.assertIsNone(result["reported_tokens"])
        self.assertEqual(result["latency"]["samples"],2);self.assertEqual(percentile([10,100],.95),95.5)

    def test_exact_decimal_unit_period_and_tolerance(self):
        case={"target":"calculation","expected":{"number":{"value":"3654.33","tolerance":"0.001","unit":"millions","currency":"CNY","period_start":"2026-01-01"}}}
        result=assess(case,{"calculation":{"value":"3654.3301","unit":"millions","currency":"CNY","period_start":"2026-01-01"}})
        self.assertTrue(result["passed"])
        self.assertFalse(assess(case,{"calculation":{"value":"3654.33","unit":"ones"}})["passed"])

    def test_recall_is_page_not_chunk_count_and_leaks_fail(self):
        case={"target":"retrieval","expected":{"pages":[{"document_id":"x","page_number":2},{"document_id":"x","page_number":3}]}}
        result=assess(case,{"citations":[{"document_id":"x","page_number":2}]*5,"date_leaks":1})
        self.assertEqual(result["metrics"]["recall_at_5"],.5);self.assertFalse(result["passed"])
