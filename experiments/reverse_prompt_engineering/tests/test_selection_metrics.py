import unittest
from unittest.mock import patch

from experiments.reverse_prompt_engineering import evaluator, metrics
from experiments.reverse_prompt_engineering.benchmark import compare_qualified
from experiments.reverse_prompt_engineering.config import DEFAULTS
from experiments.reverse_prompt_engineering.optimizer import Optimizer
from experiments.reverse_prompt_engineering.validation import JUDGE_DIMENSIONS


def judged(score=3):
    return {"dimensions": {key: {"score": score, "uncertainty": "low"} for key in JUDGE_DIMENSIONS}}


def row(topic, repetition, style, eligible):
    components = evaluator._per_poem_fitness(
        DEFAULTS, {"score": style}, judged(), eligible, {"copy_flag": False},
    )
    components["style_score"] = style
    return {"topic_id": topic, "repetition": repetition, "ok": True, "components": components,
            "rouge1_diagnostic": {"mean_f1": 0.0}}


def group(rows):
    summary = evaluator.aggregate_evaluations({"id": "test"}, rows, DEFAULTS)
    return {"aggregate": summary, "evaluations": rows}


class SelectionMetricsTests(unittest.TestCase):
    def test_progression_proxy_stays_diagnostic_while_judge_progression_has_weight(self):
        original = metrics.profile("我的灯亮着\n我出门了")
        altered = dict(original, progression_proxy=1 - original["progression_proxy"])
        self.assertEqual(metrics.compare_profiles(original, original)["score"],
                         metrics.compare_profiles(altered, original)["score"])
        judge = judged()
        def score():
            return evaluator._per_poem_fitness(DEFAULTS, {"score": 50}, judge, True, {"copy_flag": False})
        before = score()
        judge["dimensions"]["progression"]["score"] = 5
        self.assertGreater(score()["style_score"], before["style_score"])

    def test_missing_and_ineligible_poems_lower_pass_rate(self):
        mixed = group([row("a", 0, 40, True), row("b", 0, 90, False), {"ok": False}])["aggregate"]
        self.assertEqual((mixed["eligible_rate"], mixed["eligible_style"]), (1 / 3, 40))
        complete = group([row("a", 0, 30, True)])["aggregate"]
        self.assertGreater(Optimizer.rank_key(dict(complete, id="a")), Optimizer.rank_key(dict(mixed, id="b")))
        self.assertIsNone(group([row("a", 0, 99, False)])["aggregate"]["eligible_style"])

    def test_paired_scores_weight_topics_equally_and_allow_ties(self):
        a = group([row("x", 0, 50, True), row("x", 1, 50, True), row("y", 0, 50, True)])
        c = group([row("x", 0, 55, True), row("x", 1, 55, True), row("y", 0, 45, True)])
        report = compare_qualified({"A": a, "B": a, "C": c})
        self.assertEqual(report["ranks"], [["C"], ["A", "B"]])
        pair = report["paired_C_minus_baseline"]["A"]
        self.assertEqual((pair["matched_topics"], pair["matched_samples"], pair["mean_style_delta"]), (2, 3, 0))
        self.assertEqual(pair["leave_one_topic_out_range"], [-5, 5])
        report = compare_qualified({"A": a, "B": group([]), "C": c})
        self.assertIsNone(report["paired_C_minus_baseline"]["B"]["mean_style_delta"])

    def test_held_out_style_and_training_copy_are_checked_separately(self):
        text = "从深夜的站台望见最后一辆蓝色电车"
        held = "玻璃瓶滚落\n水声消失"
        selection = {"references": [{"text": text}], "held_out": [{"text": held}]}
        topic = {"id": "t", "topic": "夜班"}
        poem = {"ok": True, "form_ok": True, "text": text}
        with patch.object(evaluator, "generate_poem", return_value=poem), patch.object(
                evaluator, "judge_poem", return_value=(judged(), {})):
            result = evaluator.evaluate_candidate(object(), DEFAULTS, {"id": "c", "prompt": "p"},
                                                  [topic], selection, kind="held_out")
        record = result["evaluations"][0]
        self.assertEqual(record["deterministic"]["score"], metrics.style_similarity(text, [held])["score"])
        self.assertTrue(record["copy_diagnostics"]["copy_flag"])
        self.assertEqual(result["eligible_rate"], 0)
