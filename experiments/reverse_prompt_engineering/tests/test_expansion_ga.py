"""Unit tests for the full 7-phase Step-2 Expansion RPE-GA and Orthogonal Contract."""
from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.reverse_prompt_engineering.config import load_config
from experiments.reverse_prompt_engineering.corpus import load_selection
from experiments.reverse_prompt_engineering import expansion_ga


ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


class ExpansionGATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(CONFIG)
        cls.selection = load_selection(cls.config, ROOT)

    def test_orthogonal_contract_rejects_step3_syntax_and_lineation_terms(self):
        clean_prompt = (
            "现代诗前置构思扩写原则：\n"
            "1. 从题目核心经验里选取一件最质朴的基础实物或身体动作作为起跳切口。\n"
            "2. 立即建立该具身切口与大地、黑夜、季节或生命时间纵深的对峙关系。\n"
            "3. 确立第一人称赤诚发话位置与呼告朝向，拒绝编排买卖通勤等日常琐事因果链。\n"
            "4. 给出中后段关系推进与沉降的方向势能，留足想象余地。\n"
        )
        ok_res = expansion_ga.validate_expansion_prompt(clean_prompt, self.config, self.selection)
        self.assertTrue(ok_res["ok"], ok_res["errors"])

        intruding_prompt = clean_prompt + "5. 行末不加标点，禁用明喻，每节控制在四行以内。\n"
        bad_res = expansion_ga.validate_expansion_prompt(intruding_prompt, self.config, self.selection)
        self.assertFalse(bad_res["ok"])
        self.assertTrue(any("正交职责契约" in e for e in bad_res["errors"]), bad_res["errors"])

    def test_anchor_validator_rejects_overlong_or_form_intruding_output(self):
        good_anchor = {
            "entry_anchor": "深夜桌上一只空水杯与发凉的掌心",
            "world_scale": "掌心余温与窗外整片黑夜及消逝岁月的正面对峙",
            "stance_and_relation": "第一人称对黑夜与旧年的自己直接说话",
            "arc_turn": "从察觉衰老的惊悸转向平静饮尽杯中冷水",
            "avoid": "避开加班熬夜流水账与感伤套话",
        }
        self.assertEqual(expansion_ga.validate_expansion_anchor(good_anchor), [])

        bad_anchor = {**good_anchor, "avoid": "行末不要打逗号和句号，分三节每节四行"}
        issues = expansion_ga.validate_expansion_anchor(bad_anchor)
        self.assertTrue(any("越界" in x for x in issues), issues)

    def test_full_7phase_mock_expansion_pipeline_and_abc_benchmark(self):
        run_id = "mock-expand-v1-test"
        run_dir = ROOT / "experiments/reverse_prompt_engineering/runs" / run_id
        shutil.rmtree(run_dir, ignore_errors=True)
        try:
            report = expansion_ga.run_expansion_experiment(
                run_id=run_id,
                mode="mock",
                pop_size=2,
                generations=1,
                crossover_count=1,
                opt_topics=expansion_ga.EXPANSION_OPT_TOPICS[:2],
                test_topics=expansion_ga.EXPANSION_TEST_TOPICS[:2],
                bench_reps=1,
            )
            self.assertEqual(report["schema_version"], "rpe-expand-v1")
            self.assertTrue(report["orthogonal_contract_enforced"])
            self.assertTrue(report["champion"]["validation"]["ok"])
            self.assertIn("A_native_studio_brief", report["benchmark"])
            self.assertIn("B_oneshot_reverse_expansion", report["benchmark"])
            self.assertIn("C_rpe_ga_expand_v1", report["benchmark"])

            # A matching completed run returns its saved report before creating clients.
            with patch.object(expansion_ga, "make_mock_llm", side_effect=AssertionError("completed run was replayed")):
                resumed = expansion_ga.run_expansion_experiment(
                    run_id=run_id,
                    mode="mock",
                    pop_size=2,
                    generations=1,
                    crossover_count=1,
                    opt_topics=expansion_ga.EXPANSION_OPT_TOPICS[:2],
                    test_topics=expansion_ga.EXPANSION_TEST_TOPICS[:2],
                    bench_reps=1,
                    resume=True,
                )
            self.assertEqual(resumed, report)

            # The same run directory cannot be resumed under a changed manifest.
            manifest_path = run_dir / "run.json"
            manifest = expansion_ga.json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["bench_reps"] = 2
            manifest_path.write_text(expansion_ga.json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "相同配置续跑"):
                expansion_ga.run_expansion_experiment(
                    run_id=run_id,
                    mode="mock",
                    pop_size=2,
                    generations=1,
                    crossover_count=1,
                    opt_topics=expansion_ga.EXPANSION_OPT_TOPICS[:2],
                    test_topics=expansion_ga.EXPANSION_TEST_TOPICS[:2],
                    bench_reps=1,
                    resume=True,
                )
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
