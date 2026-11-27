import math
import unittest

from poetry_agent.style.similarity import VERSION, Index, cosine, grams


class GramTests(unittest.TestCase):
    def test_unigram_and_bigram_counts(self):
        counts = grams("月光光", ns=(1, 2))
        self.assertEqual(counts["光"], 2)
        self.assertEqual(counts["月"], 1)
        self.assertEqual(counts["月光"], 1)
        self.assertEqual(counts["光光"], 1)
        self.assertEqual(sum(counts.values()), 5)

    def test_punctuation_and_breaks_dropped_by_default(self):
        self.assertEqual(grams("月，光\n光"), grams("月光光"))

    def test_han_false_keeps_punctuation(self):
        counts = grams("月，光", ns=(1,), han=False)
        self.assertIn("，", counts)

    def test_invalid_n(self):
        with self.assertRaises(ValueError):
            grams("月光", ns=(0,))


class CosineTests(unittest.TestCase):
    def test_symmetric(self):
        left, right = {"月": 0.5, "光": 0.5}, {"月": 0.5, "霜": 0.5}
        self.assertAlmostEqual(cosine(left, right), cosine(right, left), places=12)
        self.assertAlmostEqual(cosine(left, right), 0.25, places=12)

    def test_empty_vector_scores_zero(self):
        self.assertEqual(cosine({}, {"月": 1.0}), 0.0)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.texts = [
            "月亮升起来了\n海面很安静",
            "月光落在海上\n我一个人坐着",
            "地铁在隧道里轰鸣\n人群挤成一片",
            "红绿灯坏了\n路口堵成一锅粥",
        ]
        self.labels = ["诗", "诗", "新闻", "新闻"]
        self.index = Index(self.texts, self.labels)

    def test_self_similarity_is_one(self):
        for text in self.texts:
            nearest = self.index.nearest(text, k=1)
            self.assertAlmostEqual(nearest[0]["score"], 1.0, places=9)
            self.assertEqual(nearest[0]["score"], 1.0)

    def test_nearest_is_sorted_and_limited(self):
        rows = self.index.nearest("海上月亮很安静", k=2)
        self.assertEqual(len(rows), 2)
        self.assertGreaterEqual(rows[0]["score"], rows[1]["score"])

    def test_shared_nouns_beat_topic_distance(self):
        self.assertEqual(self.index.classify("月亮底下看海的人")["label"], "诗")
        self.assertEqual(self.index.classify("地铁站里排队的人群")["label"], "新闻")

    def test_centroid_ranking_covers_every_label(self):
        scores = self.index.centroid_scores("月光落在海面上")
        self.assertEqual(list(scores), ["诗", "新闻"])
        self.assertGreater(scores["诗"], scores["新闻"])

    def test_classify_reports_confidence_between_zero_and_one(self):
        result = self.index.classify("月亮", k=3)
        self.assertIn(result["label"], self.labels)
        self.assertTrue(0.0 < result["confidence"] <= 1.0)
        self.assertAlmostEqual(sum(result["votes"].values()), 1.0, places=5)

    def test_out_of_vocabulary_query_does_not_crash(self):
        result = self.index.classify("ΩΩ", k=2)
        self.assertIsNone(result["label"])
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(self.index.similarity("ΩΩ"), [0.0, 0.0, 0.0, 0.0])

    def test_labels_asymmetric_rejected(self):
        with self.assertRaises(ValueError):
            Index(self.texts, ["诗"])

    def test_empty_corpus_rejected(self):
        with self.assertRaises(ValueError):
            Index([])

    def test_label_free_index_rejects_attribution(self):
        index = Index(self.texts)
        with self.assertRaises(ValueError):
            index.centroid_scores("月亮")
        with self.assertRaises(ValueError):
            index.classify("月亮")
        self.assertEqual(len(index.similarity("月亮")), len(self.texts))

    def test_weights_are_normalised(self):
        for vector in self.index.vectors:
            self.assertAlmostEqual(math.sqrt(sum(v * v for v in vector.values())), 1.0, places=9)

    def test_version_is_recorded(self):
        self.assertEqual(VERSION, "ngram-similarity-v1")


if __name__ == "__main__":
    unittest.main()
