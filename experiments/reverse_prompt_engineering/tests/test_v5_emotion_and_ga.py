"""Unit tests for RPE-GA v5 emotional & breath upgrades:
- vital_affect_per_100, abstract_per_100, pronoun_per_100 in BAND_WEIGHTS (rpe-poetry-style-v5)
- cold_anatomical_inventory anti-slop diagnostic (catches organ-stuffing with zero emotion)
- tightened telegraph_mid_line_spacing (>0.45) and uniform_line_lengths (<0.20)
- mixed concrete + high-emotion topic benchmark & seed pool validation
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from poetry_agent.style import stylometry
from experiments.reverse_prompt_engineering.config import load_config
from experiments.reverse_prompt_engineering.corpus import load_selection
from experiments.reverse_prompt_engineering.metrics import prompt_similarity, style_similarity
from experiments.reverse_prompt_engineering.validation import validate_prompt


ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"
SEEDS_V5 = Path(__file__).resolve().parents[1] / "seeds_v5.json"


class V5EmotionAndBreathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(CONFIG)
        cls.selection = load_selection(cls.config, ROOT)
        cls.ref_texts = [p["text"] for p in cls.selection["references"]]
        cls.held_texts = [p["text"] for p in cls.selection["held_out"]]

    def test_v5_band_weights_and_schema_include_emotional_directness(self):
        poem = (
            "今夜大风吹过空旷的站台\n"
            "母亲，我不关心远处的灯火，我只惦记你掌心的旧毛线\n"
            "黑夜从铁轨尽头升起\n"
            "盖住一生的沉默与故乡\n\n"
            "列车擦过漆黑的泥土\n"
            "我喊不出你的名字\n"
            "只有风雪把玻璃敲响"
        )
        res = style_similarity(poem, self.ref_texts)
        self.assertEqual(res["feature_schema"], "rpe-poetry-style-v6")
        for key in ("core_motif_span", "core_lexical_focus", "vital_affect_per_100", "pronoun_per_100", "line_length_cv", "mid_line_space_rate"):
            self.assertIn(key, res["band_components"])

    def test_cold_anatomical_inventory_is_penalized_vs_warm_lyric_voice(self):
        cold_organ_chopped = (
            "走廊白光 咬住铁箱肋骨\n"
            "手指按下 冰冷胃袋的骨头\n"
            "掌心贴紧 铁皮咽喉的霜\n"
            "膝盖顶住 水泥胸腔的灰\n\n"
            "灯管嗡鸣 敲打眉骨与牙齿\n"
            "硬币滚过 脚踝旁边的铁槽\n"
            "耳朵贴住 地板下面的脊骨\n"
            "手指捡起 一粒冰凉的盐"
        )
        warm_surging_poem = (
            "整条医院走廊的夜色压住这盏孤灯\n"
            "母亲 我把发烫的额头抵住孤灯下的铁壁\n"
            "听黑夜在大地深处缓慢呼吸\n\n"
            "这漫长一生的疼痛与沉默压在同一盏孤灯上\n"
            "我握紧病房外的黑夜\n"
            "替熟睡的母亲守住这盏不肯熄灭的孤灯\n\n"
            "天快亮了\n"
            "孤灯仍在黎明的风里发烫"
        )
        s_cold = style_similarity(cold_organ_chopped, self.ref_texts)
        s_warm = style_similarity(warm_surging_poem, self.ref_texts)
        cold_codes = {f["code"] for f in s_cold["anti_slop_flags"]}
        self.assertIn("cold_anatomical_inventory", cold_codes)
        self.assertIn("telegraph_mid_line_spacing", cold_codes)
        self.assertEqual(s_warm["anti_slop_flags"], [])
        self.assertGreater(s_warm["score"], s_cold["score"] + 12.0)

    def test_real_held_out_poems_do_not_trigger_cold_anatomical_flag(self):
        flagged = 0
        for text in self.held_texts:
            res = style_similarity(text, self.ref_texts)
            if any(f["code"] == "cold_anatomical_inventory" for f in res["anti_slop_flags"]):
                flagged += 1
        self.assertEqual(flagged, 0)

    def test_v5_config_weights_and_mixed_topics_are_valid(self):
        ev = self.config["evaluation"]
        self.assertEqual(ev["rubric_version"], "rpe-poetry-zh-v5")
        weights = ev["style_dimension_weights"]
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)
        top_dim = max(weights.items(), key=lambda kv: kv[1])[0]
        self.assertEqual(top_dim, "poetic_core")
        self.assertEqual(len(self.config["topics"]["optimization"]), 8)
        self.assertEqual(len(self.config["topics"]["test"]), 10)

    def test_v5_seed_pool_passes_validation_and_diversity_niching(self):
        payload = json.loads(SEEDS_V5.read_text(encoding="utf-8"))
        seeds = payload["candidates"]
        self.assertEqual(len(seeds), 5)
        rules = {
            **self.config["prompt_rules"],
            "min_prompt_chars": self.config["population"]["min_prompt_chars"],
            "max_prompt_chars": self.config["population"]["max_prompt_chars"],
        }
        for item in seeds:
            val = validate_prompt(
                item["prompt"], rules=rules, references=self.selection["references"],
                target_name=self.selection["target_name"],
                min_chars=self.config["population"]["min_prompt_chars"],
                max_chars=self.config["population"]["max_prompt_chars"],
            )
            self.assertTrue(val["ok"], f"Seed {item['id']} failed validation: {val['errors']}")
        # Ensure the 3 new v5 emotion seeds are mutually distinct (<0.88) from v4/v3 and each other
        v5_new = [s for s in seeds if s["id"].startswith("v5-seed-")]
        self.assertEqual(len(v5_new), 3)
        for i in range(len(v5_new)):
            for j in range(i + 1, len(v5_new)):
                sim = prompt_similarity(v5_new[i]["prompt"], v5_new[j]["prompt"])
                self.assertLess(sim, 0.88, f"{v5_new[i]['id']} vs {v5_new[j]['id']} too similar: {sim}")
            sim_v4 = prompt_similarity(v5_new[i]["prompt"], seeds[0]["prompt"])
            self.assertLess(sim_v4, 0.88, f"{v5_new[i]['id']} vs v4 too similar: {sim_v4}")


if __name__ == "__main__":
    unittest.main()
