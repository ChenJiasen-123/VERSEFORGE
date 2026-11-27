"""Unit tests for RPE-GA v6 Poetic Core (诗核) metrics, Judge rubric, anti-coreless flags,
prose-comma guard, Studio brief leak fix, and v6 seed pool validation.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from poetry_agent.studio import BRIEF_SYSTEM
from poetry_agent.style import stylometry
from experiments.reverse_prompt_engineering.config import load_config
from experiments.reverse_prompt_engineering.corpus import load_selection
from experiments.reverse_prompt_engineering.metrics import prompt_similarity, style_similarity
from experiments.reverse_prompt_engineering.validation import JUDGE_DIMENSIONS, STYLE_DIMENSIONS, validate_prompt


ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"
SEEDS_V6 = Path(__file__).resolve().parents[1] / "seeds_v6.json"


class V6PoeticCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(CONFIG)
        cls.selection = load_selection(cls.config, ROOT)
        cls.ref_texts = [p["text"] for p in cls.selection["references"]]
        cls.held_texts = [p["text"] for p in cls.selection["held_out"]]

    def test_poetic_core_features_distinguish_single_spine_from_scattered_simile_tour(self):
        scattered_v4_like = (
            "水刚从井里上来\n凉意带着地底的灰\n泼在脸上摸到冬天\n\n"
            "镜子挂在墙上 像一小块冻结的河\n下巴滴水 像未被翻过的土\n\n"
            "手指拔下一根白发\n像一根从时间里抽出的线头\n\n"
            "举起来 亮得像雪线以上\n我把它放进抽屉 轻轻合上"
        )
        single_core_poem = (
            "镜子里那根白发是冬天提前钉进头骨的铁钉\n"
            "我拔下它\n"
            "头骨就漏进一线冷风\n\n"
            "这根铁钉曾在我父亲鬓角发亮\n"
            "如今铁钉穿破我的黑夜\n"
            "把三十年的睡眠一寸寸钉紧\n\n"
            "谁也拔不掉体内的冬天\n"
            "白发在掌心绷直成锋利的铁钉\n"
            "今晨我认出自己正站在父亲老去的地方"
        )
        sp_scat = stylometry.profile(scattered_v4_like)
        sp_core = stylometry.profile(single_core_poem)
        self.assertGreater(sp_core["core_motif_span"], sp_scat["core_motif_span"] + 0.35)
        self.assertGreater(sp_core["core_lexical_focus"], sp_scat["core_lexical_focus"])
        self.assertEqual(sp_scat["tame_putdown_flag"], 1)
        self.assertEqual(sp_core["tame_putdown_flag"], 0)

        s_scat = style_similarity(scattered_v4_like, self.ref_texts)
        s_core = style_similarity(single_core_poem, self.ref_texts)
        scat_codes = {f["code"] for f in s_scat["anti_slop_flags"]}
        self.assertIn("scattered_simile_drift", scat_codes)
        self.assertIn("tame_putdown_closure", scat_codes)
        self.assertGreater(s_core["score"], s_scat["score"] + 15.0)

    def test_mid_line_prose_commas_are_caught_to_prevent_v5_regression(self):
        comma_prose = (
            "我接起电话，听见母亲的声音落下来\n"
            "她只问，有没有带伞\n"
            "我说有，其实伞骨已经断了一根\n\n"
            "许多年后，我翻出那晚的旧票根\n"
            "纸面泛潮，字迹快被水吃掉\n"
            "写完以后，我把票根放进夹层"
        )
        res = style_similarity(comma_prose, self.ref_texts)
        codes = {f["code"] for f in res["anti_slop_flags"]}
        self.assertIn("mid_line_prose_commas", codes)

    def test_poetic_core_is_first_judge_dimension_and_highest_weight(self):
        self.assertEqual(JUDGE_DIMENSIONS[0], "poetic_core")
        self.assertEqual(STYLE_DIMENSIONS[0], "poetic_core")
        weights = self.config["evaluation"]["style_dimension_weights"]
        self.assertEqual(weights["poetic_core"], 0.18)
        self.assertLessEqual(weights["addressivity"], 0.03)

    def test_studio_brief_system_has_no_future_self_contamination(self):
        self.assertNotIn("未来自己的一句话", BRIEF_SYSTEM)
        self.assertNotIn("系统回复", BRIEF_SYSTEM)
        self.assertIn("诗核", BRIEF_SYSTEM)

    def test_real_held_out_poems_rarely_trigger_v6_core_penalties(self):
        tame_hits = 0
        prose_comma_hits = 0
        for text in self.held_texts:
            codes = {f["code"] for f in style_similarity(text, self.ref_texts)["anti_slop_flags"]}
            if "tame_putdown_closure" in codes:
                tame_hits += 1
            if "mid_line_prose_commas" in codes:
                prose_comma_hits += 1
        self.assertEqual(tame_hits, 0)
        self.assertLessEqual(prose_comma_hits, 1)

    def test_v6_seeds_pass_validation_and_niching(self):
        seeds = json.loads(SEEDS_V6.read_text(encoding="utf-8"))["candidates"]
        self.assertEqual(len(seeds), 5)
        rules = {
            **self.config["prompt_rules"],
            "min_prompt_chars": self.config["population"]["min_prompt_chars"],
            "max_prompt_chars": self.config["population"]["max_prompt_chars"],
        }
        for s in seeds:
            val = validate_prompt(
                s["prompt"], rules=rules, references=self.selection["references"],
                target_name=self.selection["target_name"],
                min_chars=self.config["population"]["min_prompt_chars"],
                max_chars=self.config["population"]["max_prompt_chars"],
            )
            self.assertTrue(val["ok"], f"{s['id']} invalid: {val['errors']}")
        v6_new = [s for s in seeds if s["id"].startswith("v6-seed-")]
        self.assertEqual(len(v6_new), 3)
        for i in range(len(v6_new)):
            self.assertLess(prompt_similarity(v6_new[i]["prompt"], seeds[0]["prompt"]), 0.88)
            for j in range(i + 1, len(v6_new)):
                self.assertLess(prompt_similarity(v6_new[i]["prompt"], v6_new[j]["prompt"]), 0.88)


if __name__ == "__main__":
    unittest.main()
