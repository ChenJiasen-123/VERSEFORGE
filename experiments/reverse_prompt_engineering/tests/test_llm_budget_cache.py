import json
import tempfile
import unittest
from pathlib import Path

from experiments.reverse_prompt_engineering.config import load_config
from experiments.reverse_prompt_engineering.llm import (
    Budget, BudgetExhausted, JsonlLedger, LLM, LLMCache, parse_json_object,
)
from experiments.reverse_prompt_engineering.mock import MockRPELLM


CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


class LLMCacheBudgetTests(unittest.TestCase):
    def test_cache_hit_does_not_consume_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            budget = Budget(10, 100000)
            cache = LLMCache(tmp / "cache.jsonl")
            ledger = JsonlLedger(tmp / "ledger.jsonl")
            llm = LLM(MockRPELLM(seed=1), budget, cache, ledger)
            first, meta1 = llm.call_text(
                purpose="test", system="system", user=json.dumps({"kind": "rpe_generate_poem", "topic": "雨"}, ensure_ascii=False),
                max_tokens=200, temperature=0.0, cache_variant="v1",
            )
            second, meta2 = llm.call_text(
                purpose="test", system="system", user=json.dumps({"kind": "rpe_generate_poem", "topic": "雨"}, ensure_ascii=False),
                max_tokens=200, temperature=0.0, cache_variant="v1",
            )
            self.assertEqual(first, second)
            self.assertFalse(meta1["cache_hit"])
            self.assertTrue(meta2["cache_hit"])
            self.assertEqual(budget.calls, 1)
            self.assertEqual(budget.cache_hits, 1)
            rows = ledger.entries()
            self.assertEqual(len(rows), 2)
            self.assertEqual(sum(1 for row in rows if row["cache_hit"]), 1)

    def test_budget_stops_before_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            budget = Budget(1, 100000)
            llm = LLM(
                MockRPELLM(seed=2), budget, LLMCache(tmp / "c.jsonl"), JsonlLedger(tmp / "l.jsonl"),
            )
            llm.call_text(purpose="test", system="s", user=json.dumps({"kind": "rpe_generate_poem", "topic": "a"}),
                          max_tokens=100, temperature=0.0, cache_variant="a")
            with self.assertRaises(BudgetExhausted):
                llm.call_text(purpose="test", system="s", user=json.dumps({"kind": "rpe_generate_poem", "topic": "b"}),
                              max_tokens=100, temperature=0.0, cache_variant="b")

    def test_json_parser_recovers_first_balanced_object(self):
        self.assertEqual(parse_json_object('{"a": 1}{"b": 2}'), {"a": 1})
        self.assertEqual(parse_json_object('前缀 {"a": {"b": 2}} 后缀'), {"a": {"b": 2}})
        with self.assertRaises(ValueError):
            parse_json_object('not json')

    def test_restore_budget_from_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ledger_path = tmp / "ledger.jsonl"
            ledger = JsonlLedger(ledger_path)
            ledger.append({"cache_hit": False, "input_tokens": 10, "output_tokens": 20, "estimated_cost": 0.5})
            ledger.append({"cache_hit": True, "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0})
            from experiments.reverse_prompt_engineering.llm import restore_budget_from_ledger
            budget = Budget(10, 1000)
            restore_budget_from_ledger(budget, ledger_path)
            self.assertEqual((budget.calls, budget.input_tokens, budget.output_tokens, budget.cache_hits), (1, 10, 20, 1))
            self.assertAlmostEqual(budget.cost, 0.5)


if __name__ == "__main__":
    unittest.main()
