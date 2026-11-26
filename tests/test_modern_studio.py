import json
import tempfile
import unittest
from pathlib import Path

from poetry_agent.style.stylometry import corpus_profile
from experiments.modern_poetry_studio.blind import _review_markdown, build_packet
from experiments.modern_poetry_studio.evaluate import evaluate_run
from experiments.modern_poetry_studio.generate import parse_poem, run_generation
from experiments.modern_poetry_studio.prompt import compile_style_prompt

TEXTS = [
    "短句\n短句\n\n长一点的一行在纸上\n短",
    "另一首\n没有标点\n\n很短的收尾",
]


class ModernStudioTests(unittest.TestCase):
    def setUp(self):
        self.profile = corpus_profile(TEXTS)

    def test_prompt_has_no_poet_name_or_original_line(self):
        record = compile_style_prompt(self.profile, variant="style_card_anti_slop", max_lines=12)
        self.assertNotIn("海子", record["prompt"])
        self.assertNotIn("北岛", record["prompt"])
        self.assertNotIn("舒婷", record["prompt"])
        self.assertNotIn("长一点的一行在纸上", record["prompt"])
        self.assertGreater(record["char_count"], 100)

    def test_parse_poem_accepts_stanzas_and_lines(self):
        stanzas = parse_poem(json.dumps({"title": "题", "stanzas": [["一", "二"], ["三"]]}, ensure_ascii=False))
        self.assertEqual(stanzas["lines"], ["一", "二", "三"])
        lines = parse_poem(json.dumps({"title": "题", "lines": ["一", "二"]}, ensure_ascii=False))
        self.assertEqual(lines["lines"], ["一", "二"])
        embedded = parse_poem(json.dumps({"title": "题", "stanzas": ["一\n二", "三"]}, ensure_ascii=False))
        self.assertEqual(embedded["lines"], ["一", "二", "三"])

    def test_parse_poem_rejects_missing_title(self):
        with self.assertRaises(ValueError):
            parse_poem(json.dumps({"lines": ["一"]}, ensure_ascii=False))

    def test_blind_packet_hides_method_and_title(self):
        with tempfile.TemporaryDirectory() as temp:
            bodies = {"base": "正文甲" + chr(10) + "第二行", "style": "正文乙" + chr(10) + "第二行"}
            titles = {"base": "标题甲", "style": "标题乙"}
            for name, text in bodies.items():
                run = Path(temp) / name
                run.mkdir()
                (run / "generations.json").write_text(json.dumps({
                    "records": [{"ok": True, "topic_id": "t1", "topic": "题目", "title": titles[name], "text": text, "stanzas": None}]
                }, ensure_ascii=False), encoding="utf-8")
            packet = build_packet([Path(temp) / "base"], [Path(temp) / "style"])
            review = _review_markdown(packet)
            self.assertIn("作品 A", review)
            self.assertIn("作品 B", review)
            self.assertIn("正文甲", review)
            self.assertIn("正文乙", review)
            self.assertNotIn("标题甲", review)
            self.assertNotIn("标题乙", review)
            self.assertNotIn("baseline", review)
            self.assertNotIn("style_card", review)

    def test_mock_generation_and_evaluation(self):
        prompt = compile_style_prompt(self.profile, variant="style_card", max_lines=12)
        with tempfile.TemporaryDirectory() as temp:
            result = run_generation(
                mode="mock",
                prompt_record=prompt,
                topics=[{"id": "t1", "topic": "测试题", "max_lines": 12, "requirements": ""}],
                repetitions=1,
                output_dir=Path(temp),
            )
            self.assertEqual(result["call_count"], 0)
            run_dir = Path(temp) / result["run_id"]
            self.assertTrue((run_dir / "generations.json").exists())
            evaluation = evaluate_run(run_dir)
            self.assertEqual(evaluation["aggregate"]["n"], 1)
            self.assertIn("rows", evaluation)


if __name__ == "__main__":
    unittest.main()
