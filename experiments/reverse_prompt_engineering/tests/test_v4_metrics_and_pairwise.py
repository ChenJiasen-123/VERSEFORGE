"""Unit tests for v4 metric dimensions, space-aware breath clauses,
punctuation-agnostic stanza-head anti-cloning, uncertainty shrinkage,
zero-position-bias AB+BA pairwise tie-breaking, and seeded continuation.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from poetry_agent.style import stylometry
from experiments.reverse_prompt_engineering import evaluator
from experiments.reverse_prompt_engineering.config import DEFAULTS, load_config
from experiments.reverse_prompt_engineering.corpus import load_selection
from experiments.reverse_prompt_engineering.metrics import style_similarity
from experiments.reverse_prompt_engineering.run import run_experiment
from experiments.reverse_prompt_engineering.validation import JUDGE_DIMENSIONS


ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


class V4MetricsAndResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(CONFIG)
        cls.selection = load_selection(cls.config, ROOT)
        cls.ref_texts = [p["text"] for p in cls.selection["references"]]

    def test_space_aware_clauses_and_mid_line_space_rate(self):
        spaced = "门开着 风把地板上的灰吹成一道浅水\n四壁之内 黑夜先于我抵达\n木头醒着"
        sp = stylometry.profile(spaced)
        self.assertAlmostEqual(sp["mid_line_space_rate"], 2 / 3, places=5)
        # Splitting on spaces produces 5 clauses instead of 3 whole lines
        self.assertLess(sp["clause_mean_length"], sp["mean_line_length"])
        self.assertGreater(sp["clause_length_cv"], 0.15)

        telegraph = "\n".join(["短词 碎片 停顿"] * 10)
        res = style_similarity(telegraph, self.ref_texts)
        codes = {f["code"] for f in res["anti_slop_flags"]}
        self.assertIn("telegraph_mid_line_spacing", codes)

    def test_punctuation_agnostic_stanza_head_cloning_is_caught(self):
        cloned_heads = (
            "旧衬衣 你被铁丝咬住肩膀\n风穿过袖口\n夜色沉入泥土\n\n"
            "旧衬衣 你在风里站成空壳\n霜雪盖住纽扣\n远山一片漆黑\n\n"
            "旧衬衣 夜色从领口灌进去\n骨头在寒冷里发响\n星光落在草尖\n\n"
            "旧衬衣 等黎明把白霜敲碎\n我伸手取下你\n叠进沉默的木箱"
        )
        varied_heads = (
            "铁丝咬住旧衬衣的肩膀\n风穿过空荡的袖口\n夜色沉入泥土\n\n"
            "你在北风里站成硬壳\n霜雪盖住胸前的旧纽扣\n远山一片漆黑\n\n"
            "当夜色从领口灌进旧衬衣\n我的肋骨也在暗处发响\n星光落在草尖\n\n"
            "黎明把白霜一寸寸敲碎\n我伸手取下冰凉的布\n叠进沉默的木箱"
        )
        s_cloned = style_similarity(cloned_heads, self.ref_texts)
        s_varied = style_similarity(varied_heads, self.ref_texts)
        codes = {f["code"] for f in s_cloned["anti_slop_flags"]}
        self.assertIn("stanza_head_template_cloning", codes)
        self.assertGreater(s_varied["score"], s_cloned["score"] + 4.0)

    def test_order_sensitive_stanza_progression_and_new_bands_exist(self):
        poem = (
            "锈铁锁挂在木门上\n夜风吹过潮湿的石阶\n我摸到冰冷的钥匙\n\n"
            "黑夜漫过大地的肩膀\n远处的河水在深谷奔流\n星火落在荒草根部\n\n"
            "天亮前木门轻轻合拢\n我把钥匙放回掌心"
        )
        res = style_similarity(poem, self.ref_texts)
        for key in ("mid_stanza_novelty", "first_last_return", "mid_line_space_rate", "body_per_100", "primal_per_100"):
            self.assertIn(key, res["band_components"])

    def test_uncertainty_shrinkage_dampens_noisy_dimensions(self):
        judge_low_unc = {
            "dimensions": {
                k: {"score": 4.5 if k == "imagery" else 3.0, "uncertainty": "low"}
                for k in JUDGE_DIMENSIONS
            }
        }
        judge_high_unc = {
            "dimensions": {
                k: {"score": 4.5 if k == "imagery" else 3.0, "uncertainty": "high" if k == "imagery" else "low"}
                for k in JUDGE_DIMENSIONS
            }
        }
        s_confident = evaluator._per_poem_fitness(DEFAULTS, {"score": 65.0}, judge_low_unc, True, {"copy_flag": False})
        s_uncertain = evaluator._per_poem_fitness(DEFAULTS, {"score": 65.0}, judge_high_unc, True, {"copy_flag": False})
        self.assertGreater(s_confident["judge_style_score"], s_uncertain["judge_style_score"])

    def test_symmetric_pairwise_cancels_position_bias_to_exact_zero(self):
        class PositionBiasedFirstWinsJudge:
            mock = True

            def call_json(self, **kwargs):
                # Pathological judge that ALWAYS chooses poem 1 regardless of content
                return {"winner": "1", "confidence": "medium", "rationale": "总是选第一首"}, {}

        class ConsistentQualityJudge:
            mock = True

            def call_json(self, **kwargs):
                payload = json.loads(kwargs["user"])
                p1 = payload["poem_1"]["text"]
                winner = "1" if "大地与骨头" in p1 else "2"
                return {"winner": winner, "confidence": "high", "rationale": "大地与骨头更接近参考诗"}, {}

        cand_a = {
            "id": "cand-A",
            "evaluation": {
                "evaluations": [
                    {"topic_id": "t1", "topic": "题1", "repetition": 0, "ok": True,
                     "components": {"eligible": True}, "generation": {"title": "A1", "text": "大地与骨头在黑夜发光"}},
                    {"topic_id": "t2", "topic": "题2", "repetition": 0, "ok": True,
                     "components": {"eligible": True}, "generation": {"title": "A2", "text": "大地与骨头沉入水底"}},
                ]
            },
        }
        cand_b = {
            "id": "cand-B",
            "evaluation": {
                "evaluations": [
                    {"topic_id": "t1", "topic": "题1", "repetition": 0, "ok": True,
                     "components": {"eligible": True}, "generation": {"title": "B1", "text": "普通散文句子写在这里"}},
                    {"topic_id": "t2", "topic": "题2", "repetition": 0, "ok": True,
                     "components": {"eligible": True}, "generation": {"title": "B2", "text": "另一句平淡的日常说明"}},
                ]
            },
        }
        biased_res = evaluator.pairwise_compare_candidates(
            PositionBiasedFirstWinsJudge(), self.config, cand_a, cand_b, self.selection,
        )
        self.assertEqual(biased_res["order_flips"], 2)
        self.assertEqual(biased_res["consistent_wins_a"], 0)
        self.assertEqual(biased_res["consistent_wins_b"], 0)
        self.assertEqual(biased_res["bonus_a"], 0.0)

        clean_res = evaluator.pairwise_compare_candidates(
            ConsistentQualityJudge(), self.config, cand_a, cand_b, self.selection,
        )
        self.assertEqual(clean_res["order_flips"], 0)
        self.assertEqual(clean_res["consistent_wins_a"], 2)
        self.assertEqual(clean_res["consistent_wins_b"], 0)
        self.assertGreater(clean_res["bonus_a"], 0.0)

    def test_seeded_continuation_pipeline_in_mock_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seed_file = tmp_path / "seeds.json"
            seed_file.write_text(json.dumps({
                "candidates": [
                    {
                        "id": "seed-elite-1",
                        "prompt": (
                            "总纲：从现场最素朴的实物出发，两行内推向大地、黑夜、水火或身体的原初尺度。\n"
                            "1. 词取根本：多用基础实词与身体触感词，抽象词须由具体动作接住。\n"
                            "2. 无标点呼吸：行末少用标点，长短句交替，行内空格停顿克制有度。\n"
                            "3. 呼告错落推进：跨节复沓须改变句法位置与动作方向，禁止多节句首同词克隆。\n"
                            "4. 结尾沉降留白：末行回到安静可触的动作或物象，不作格言总结。\n"
                        ),
                    }
                ]
            }, ensure_ascii=False), encoding="utf-8")
            cfg = load_config(CONFIG)
            cfg["experiment"]["output_root"] = str(tmp_path / "runs")
            cfg["population"]["size"] = 2
            cfg["population"]["generations"] = 1
            cfg["population"]["crossover_count"] = 1
            cfg["population"]["seed_prompts_path"] = str(seed_file)
            cfg["topics"]["optimization"] = cfg["topics"]["optimization"][:2]
            cfg["topics"]["test"] = cfg["topics"]["test"][:2]
            cfg["benchmark"]["repetitions"] = 1
            cfg["budget"]["max_api_calls"] = 500
            cfg["budget"]["max_total_tokens"] = 2000000
            state = run_experiment(cfg, "mock", project_root=ROOT, run_id="v4-seeded-mock", authorized=False)
            self.assertEqual(state["status"], "completed")
            init_origins = [c["origin"] for c in state["initialization"]["candidates"]]
            self.assertEqual(init_origins[0], "seed")
            self.assertEqual(init_origins[1], "initializer")


if __name__ == "__main__":
    unittest.main()
