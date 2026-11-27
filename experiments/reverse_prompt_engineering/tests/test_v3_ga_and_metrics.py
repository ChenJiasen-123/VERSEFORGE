"""Unit tests for v3 metric improvements, anti-checklist prompt rules,
semantic crossover, similarity niching, and in-run elite confirmation.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from experiments.reverse_prompt_engineering.config import load_config
from experiments.reverse_prompt_engineering.corpus import load_selection
from experiments.reverse_prompt_engineering.metrics import (
    corpus_stylometry_summary, diagnose_poem_vs_corpus, prompt_similarity, style_similarity,
)
from experiments.reverse_prompt_engineering.optimizer import Optimizer
from experiments.reverse_prompt_engineering.run import run_experiment
from experiments.reverse_prompt_engineering.validation import validate_prompt


ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


class V3MetricsAndPromptRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(CONFIG)
        cls.selection = load_selection(cls.config, ROOT)
        cls.ref_texts = [p["text"] for p in cls.selection["references"]]
        cls.rules = {
            **cls.config["prompt_rules"],
            "min_prompt_chars": cls.config["population"]["min_prompt_chars"],
            "max_prompt_chars": cls.config["population"]["max_prompt_chars"],
        }

    def test_unpunctuated_poems_are_not_penalized_vs_unpunctuated_references(self):
        unpunct = (
            "今夜雨水落在铁皮屋顶\n"
            "空旷的站台没有灯火\n"
            "只有夜风吹过泥土和青草\n\n"
            "我把旧手套放在长椅\n"
            "水声在黑暗里独自醒着\n"
            "天亮以前\n"
            "远处的山脊露出一线白"
        )
        punct_prose = (
            "今夜雨水落在铁皮屋顶，因为天气变得很冷，\n"
            "所以空旷的站台没有灯火，而且四处都很安静。\n"
            "售货机，你亮在尽头，像一盏孤独的灯；\n\n"
            "然而我把旧手套放在长椅上，接着转身离开，\n"
            "售货机，你亮在尽头，像一盏孤独的灯；\n"
            "于是水声在黑暗里响着，仿佛在诉说什么，\n\n"
            "售货机，你亮在尽头，像一盏孤独的灯。"
        )
        s_clean = style_similarity(unpunct, self.ref_texts)
        s_slop = style_similarity(punct_prose, self.ref_texts)
        self.assertGreater(s_clean["score"], s_slop["score"] + 8.0)
        self.assertGreater(s_slop["anti_slop_penalty"], 0.0)
        self.assertEqual(s_clean["feature_schema"], "rpe-poetry-style-v6")

    def test_corpus_stylometry_summary_and_diagnosis_are_anonymous(self):
        summary = corpus_stylometry_summary(self.ref_texts)
        self.assertIn("unpunctuated_break_rate", summary)
        self.assertIn("line_length_cv", summary)
        diag = diagnose_poem_vs_corpus("每行都有逗号，\n第二行也有逗号，\n第三行还有句号。", self.ref_texts)
        self.assertIsInstance(diag["deviations"], list)

    def test_hardcoded_poem_counts_and_meta_checklists_are_rejected(self):
        base = (
            "现代自由诗风格指令：\n"
            "1. 行尾少用标点，让长短句形成呼吸落差。\n"
            "2. 让现场器物与大地、夜色、雨水发生碰撞。\n"
            "3. 结尾自然承接前文，不用总结格言。\n"
        )
        bad_quota = base + "4. 全诗控制在4—8节，总行数15—40行。\n"
        r1 = validate_prompt(bad_quota, rules=self.rules, references=self.selection["references"], target_name="海子")
        self.assertFalse(r1["ok"])
        self.assertTrue(any("硬编码" in e for e in r1["errors"]), r1["errors"])

        bad_meta = base + "4. 完成后自检明喻数量，任一项不满足则重写。\n"
        r2 = validate_prompt(bad_meta, rules=self.rules, references=self.selection["references"], target_name="海子")
        self.assertFalse(r2["ok"])
        self.assertTrue(any("自检" in e or "元指令" in e for e in r2["errors"]), r2["errors"])

    def test_niching_prefers_diverse_prompts(self):
        cfg = load_config(CONFIG)
        cfg["population"]["size"] = 2
        cfg["population"]["survivor_max_similarity"] = 0.85
        opt = Optimizer(config=cfg, selection=self.selection, topics=cfg["topics"], llm=None, store=None)
        p1 = "现代自由诗：行尾不加标点，用长短句陡峭落差推进呼吸，让器物与大地黑夜碰撞。"
        p1_clone = "现代自由诗：行尾不加标点，用长短句陡峭落差推进呼吸，让器物与大地黑夜并置。"
        p2_distinct = "以直接命名句与赤诚呼告展开抒情，关键词跨节变奏回返，结尾停在余温动作上。"
        self.assertGreater(prompt_similarity(p1, p1_clone), 0.85)
        self.assertLess(prompt_similarity(p1, p2_distinct), 0.85)
        pool = [
            {"id": "c1", "prompt": p1, "fitness": 80.0, "eligible_rate": 1.0, "eligible_style": 80.0},
            {"id": "c2", "prompt": p1_clone, "fitness": 79.0, "eligible_rate": 1.0, "eligible_style": 79.0},
            {"id": "c3", "prompt": p2_distinct, "fitness": 75.0, "eligible_rate": 1.0, "eligible_style": 75.0},
        ]
        survivors = opt._select_survivors(pool)
        self.assertEqual([s["id"] for s in survivors], ["c1", "c3"])

    def test_crossover_and_in_run_confirmation_in_mock_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(CONFIG)
            cfg["experiment"]["output_root"] = str(Path(tmp) / "runs")
            cfg["population"]["size"] = 3
            cfg["population"]["generations"] = 1
            cfg["population"]["crossover_count"] = 1
            cfg["population"]["in_run_confirm_top_k"] = 1
            cfg["evaluation"]["confirmation_top_k"] = 2
            cfg["evaluation"]["confirmation_repetitions"] = 1
            cfg["benchmark"]["repetitions"] = 1
            cfg["budget"]["max_api_calls"] = 500
            cfg["budget"]["max_total_tokens"] = 2000000
            state = run_experiment(cfg, "mock", project_root=ROOT, run_id="v3-check", authorized=False)
            self.assertEqual(state["status"], "completed")
            origins = {c["origin"] for c in state["all_children"]}
            self.assertIn("crossover", origins)
            self.assertIn("mutation", origins)
            self.assertEqual(state["final_prompt"]["evaluation_count"], 2 * len(cfg["topics"]["optimization"]))


if __name__ == "__main__":
    unittest.main()
