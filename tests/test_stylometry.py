import unittest

from poetry_agent.style.stylometry import (
    anti_slop_flags,
    compare,
    corpus_profile,
    distinctive_terms,
    profile,
)


class StylometryTests(unittest.TestCase):
    def test_lineation_rates(self):
        text = "第一行没有标点\n第二行，也没有句号\n\n第三行结束了。"
        p = profile(text)
        self.assertEqual(p["line_count"], 3)
        self.assertEqual(p["stanza_count"], 2)
        self.assertAlmostEqual(p["line_end_punct_rate"], 1 / 3, places=5)
        self.assertGreater(p["unpunctuated_break_rate"], 0.5)

    def test_uniform_prose_flags(self):
        text = "\n".join(["这是一行长度差不多的完整句子。" for _ in range(6)])
        p = profile(text)
        flags = {row["code"] for row in anti_slop_flags(text, p)}
        self.assertIn("all_lines_punctuated", flags)
        self.assertIn("uniform_line_length", flags)

    def test_compare_places_text_inside_band(self):
        texts = ["短句\n短句\n\n长一点的一行在这里\n短", "另一首\n没有标点\n\n很短的收尾"]
        reference = corpus_profile(texts)
        result = compare(texts[0], reference)
        self.assertIn("in_band_rate", result)
        self.assertGreater(result["in_band_rate"], 0.0)
        self.assertLessEqual(result["in_band_rate"], 1.0)

    def test_distinctive_terms_positive_and_negative(self):
        target = ["麦地麦地麦地\n太阳太阳", "麦地太阳"]
        baseline = ["城市城市城市\n街道街道", "城市街道"]
        result = distinctive_terms(target, baseline, n=2, top=5)
        self.assertTrue(result["positive"])
        self.assertTrue(all(row["target_count"] >= 3 for row in result["positive"]))
        self.assertTrue(result["negative"])

    def test_missing_reference_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            corpus_profile([])


if __name__ == "__main__":
    unittest.main()
