import json
import tempfile
import unittest
from pathlib import Path

from experiments.reverse_prompt_engineering.config import load_config
from experiments.reverse_prompt_engineering.corpus import (
    anonymous_references, load_selection, reference_lines,
)
from experiments.reverse_prompt_engineering.metrics import (
    copy_diagnostics, longest_common_substring_length, profile,
    rouge1_char, style_similarity,
)
from experiments.reverse_prompt_engineering.validation import validate_prompt


ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


class CorpusAndMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(CONFIG)
        cls.selection = load_selection(cls.config, ROOT)

    def test_reference_and_held_out_are_disjoint_and_controlled(self):
        refs = self.selection["references"]
        held = self.selection["held_out"]
        self.assertEqual(len(refs), self.config["corpus"]["reference_count"])
        self.assertEqual(len(held), self.config["corpus"]["held_out_count"])
        self.assertFalse({p["poem_id"] for p in refs} & {p["poem_id"] for p in held})
        self.assertFalse({p["text_sha256"] for p in refs} & {p["text_sha256"] for p in held})
        self.assertTrue(all(p["split"] == "train" for p in refs))
        self.assertTrue(all(p["split"] == "held_out" for p in held))
        self.assertTrue(all(p["text"] for p in refs + held))

    def test_anonymous_block_does_not_include_poet_name_or_source(self):
        rows = anonymous_references(self.selection["references"])
        self.assertEqual(len(rows), len(self.selection["references"]))
        for row in rows:
            serialized = json.dumps(row, ensure_ascii=False)
            self.assertNotIn(self.selection["target_name"], serialized)
            self.assertNotIn("source_url", row)
            self.assertNotIn("poem_id", row)
            self.assertEqual(set(row), {"label", "text"})

    def test_identical_text_has_full_style_score_and_copy_flag(self):
        text = self.selection["references"][0]["text"]
        result = style_similarity(text, [text])
        self.assertAlmostEqual(result["score"], 100.0, places=6)
        self.assertAlmostEqual(rouge1_char(text, text)["f1"], 1.0, places=6)
        diag = copy_diagnostics(text, [text])
        self.assertTrue(diag["copy_flag"])
        self.assertGreaterEqual(diag["max_lcs_chars"], 12)

    def test_style_similarity_is_bounded_and_has_components(self):
        gen = "夜里的灯还亮着\n我把手伸进风里\n一只空瓶滚到墙角"
        result = style_similarity(gen, [p["text"] for p in self.selection["references"]])
        self.assertGreaterEqual(result["score"], 0.0)
        self.assertLessEqual(result["score"], 100.0)
        self.assertEqual(set(result["mean_components"]), {
            "character_bigram", "character_unigram", "function_chars", "line_length",
            "punctuation", "line_endings", "line_starts", "stanza_shape",
            "enjambment", "structure", "progression", "pronouns",
        })
        self.assertEqual(len(result["per_reference"]), len(self.selection["references"]))

    def test_copy_diagnostics_detects_verbatim_reference_line(self):
        ref = "第一行是完全普通的诗句啊\n第二行也是普通的句子"
        gen = "我写下了第一行是完全普通的诗句啊\n然后停下"
        diag = copy_diagnostics(gen, [ref], line_chars=8, lcs_chars=12)
        self.assertTrue(diag["copy_flag"])
        self.assertTrue(diag["matched_reference_lines"])
        self.assertGreaterEqual(longest_common_substring_length(gen, ref), 12)

    def test_profile_is_deterministic(self):
        text = "雨落在窗上\n我听见远处的车"
        self.assertEqual(profile(text)["char_count"], 12)
        self.assertEqual(profile(text)["line_count"], 2)
        self.assertEqual(profile(text)["stanza_count"], 1)


class PromptRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(CONFIG)
        cls.selection = load_selection(cls.config, ROOT)
        cls.rules = {
            **cls.config["prompt_rules"],
            "min_prompt_chars": cls.config["population"]["min_prompt_chars"],
            "max_prompt_chars": cls.config["population"]["max_prompt_chars"],
        }

    def _validate(self, prompt):
        return validate_prompt(
            prompt, rules=self.rules, references=self.selection["references"],
            target_name=self.selection["target_name"], target_aliases=self.selection["target_aliases"],
        )

    def _valid_prompt(self):
        return (
            "写现代汉语自由诗。\n"
            "1. 每节控制在2到5行，行尾优先落在具体名词或动作上。\n"
            "2. 先写动作、空间和声音，再让情感从场景中出现，每节最多一次直接抒情。\n"
            "3. 全诗至少一次重复呼告，但同一意象不要反复超过三次。\n"
            "4. 结尾用仍在运动中的具体物象收束，不用总结性格言。\n"
        )

    def test_valid_prompt_passes(self):
        result = self._validate(self._valid_prompt())
        self.assertTrue(result["ok"], result["errors"])
        self.assertGreaterEqual(result["metrics"]["instruction_units"], 3)

    def test_target_name_is_rejected(self):
        prompt = self._valid_prompt() + "5. 模仿海子的语言。\n"
        result = self._validate(prompt)
        self.assertFalse(result["ok"])
        self.assertTrue(any("姓名" in error for error in result["errors"]))

    def test_vague_phrases_are_rejected_when_excessive(self):
        prompt = self._valid_prompt() + "5. 语言优美，意境深远，情感真挚。\n"
        result = self._validate(prompt)
        self.assertFalse(result["ok"])
        self.assertTrue(any("含糊" in error or "套话" in error for error in result["errors"]))

    def test_reference_line_copy_is_rejected(self):
        ref_line = reference_lines(self.selection["references"], min_chars=12)[0]
        prompt = self._valid_prompt() + "5. " + ref_line + "。\n"
        result = self._validate(prompt)
        self.assertFalse(result["ok"])
        self.assertTrue(any("完整诗句" in error or "连续重合" in error for error in result["errors"]))

    def test_dependency_phrase_is_rejected(self):
        prompt = self._valid_prompt() + "5. 参考上面这些作品的语言。\n"
        result = self._validate(prompt)
        self.assertFalse(result["ok"])
        self.assertTrue(any("依赖参考" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()


class StanzaBreakTests(unittest.TestCase):
    def test_generation_accepts_blank_lines_as_stanza_breaks(self):
        import json as _json
        import tempfile
        from pathlib import Path as _Path
        from experiments.reverse_prompt_engineering.config import load_config
        from experiments.reverse_prompt_engineering.generator import generate_poem
        from experiments.reverse_prompt_engineering.llm import Budget, JsonlLedger, LLM, LLMCache
        from experiments.reverse_prompt_engineering.validation import validate_generation

        class BlankLineClient:
            model = "blank-line-test"
            mock = True

            def complete(self, system, user, timeout=90, max_tokens=1200, thinking=None, temperature=None):
                content = _json.dumps({
                    "title": "测试",
                    "lines": [
                        "第一行", "第二行", "第三行", "第四行", "",
                        "第五行", "第六行", "第七行", "第八行", "",
                        "第九行", "第十行", "第十一行", "第十二行",
                    ],
                }, ensure_ascii=False)
                return {"content": content, "usage": {}, "request_settings": {"mock": True}}

        lines = [
            "第一行", "第二行", "第三行", "第四行", "",
            "第五行", "第六行", "第七行", "第八行", "",
            "第九行", "第十行", "第十一行", "第十二行",
        ]
        data = {"title": "测试", "lines": lines}
        self.assertEqual(validate_generation(data), [])
        cfg = load_config(CONFIG)
        topic = cfg["topics"]["optimization"][0]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = _Path(tmp)
            llm = LLM(BlankLineClient(), Budget(10, 100000), LLMCache(tmp / "c.jsonl"), JsonlLedger(tmp / "l.jsonl"))
            gen = generate_poem(llm, cfg, "写现代诗。", topic, cache_variant="stanza-test")
        self.assertTrue(gen["ok"], gen.get("form_issues"))
        self.assertEqual(gen["lines"], [line for line in lines if line])
        self.assertEqual(gen["raw_lines"], lines)
        self.assertIn("\n\n", gen["text"])
        self.assertTrue(gen["form_ok"], gen["form_issues"])


if __name__ == "__main__":
    unittest.main()


class JudgeNormalizationTests(unittest.TestCase):
    def test_uncertainty_variants_are_normalized(self):
        from experiments.reverse_prompt_engineering.evaluator import _normalize_uncertainty
        self.assertEqual(_normalize_uncertainty("medium-high"), "high")
        self.assertEqual(_normalize_uncertainty("中"), "medium")
        self.assertEqual(_normalize_uncertainty("低"), "low")
        self.assertEqual(_normalize_uncertainty("HIGH"), "high")
        self.assertEqual(_normalize_uncertainty(None), "high")


if __name__ == "__main__":
    unittest.main()
