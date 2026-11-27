"""Character n-gram TF-IDF similarity and corpus attribution.

Pure standard library: no numpy, no scikit-learn, no word segmenter.  The
weights follow the usual scikit-learn defaults (sublinear tf, smoothed idf,
L2 normalisation) so results can be checked against it; see
``style_similarity.py`` for the parity harness.

What this reports is *surface* overlap: which corpus a text sits nearest to,
and which of its neighbours are closest.  It is not a quality score and not a
verdict about authorship.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from .stylometry import han_only

VERSION = "ngram-similarity-v1"

DEFAULT_NS = (1, 2)


def grams(text: str, ns=DEFAULT_NS, *, han: bool = True) -> Counter:
    """Count character n-grams.  ``han=True`` drops punctuation and line breaks."""
    body = han_only(text) if han else text.replace("\r\n", "\n").replace("\r", "\n")
    counts: Counter = Counter()
    for n in ns:
        if n <= 0:
            raise ValueError("n 必须为正整数")
        for i in range(max(0, len(body) - n + 1)):
            counts[body[i:i + n]] += 1
    return counts


def _weighted(counts: Counter, idf: dict, sublinear: bool) -> dict:
    vector = {}
    for term, count in counts.items():
        weight = 1.0 + math.log(count) if sublinear else float(count)
        vector[term] = weight * idf.get(term, _unseen_idf(idf))
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm:
        for term in vector:
            vector[term] /= norm
    return vector


def _unseen_idf(idf: dict) -> float:
    # Short texts share few surface n-grams; dropping unseen terms entirely makes
    # every similarity 0.  The maximum observed idf is the "never seen" weight.
    return idf.get("__max__", 1.0)


def cosine(left: dict, right: dict) -> float:
    """Cosine similarity of two sparse vectors (already L2 normalised or not)."""
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


class Index:
    """TF-IDF vector index over a fixed set of texts.

    ``labels`` groups texts into corpora (for example one label per poet); it is
    optional, and only used by :meth:`centroid_scores` and :meth:`classify`.
    """

    def __init__(self, texts, labels=None, ns=DEFAULT_NS, *, sublinear: bool = True, han: bool = True):
        self.texts = list(texts)
        self.labels = list(labels) if labels is not None else None
        if self.labels is not None and len(self.labels) != len(self.texts):
            raise ValueError("labels 与 texts 数量不一致")
        if not self.texts:
            raise ValueError("索引至少需要一段文本")
        self.ns = tuple(ns)
        self.sublinear = sublinear
        self.han = han
        self.counts = [grams(text, self.ns, han=han) for text in self.texts]
        document_frequency = Counter()
        for counts in self.counts:
            document_frequency.update(counts.keys())
        total = len(self.counts)
        self.idf = {term: math.log((1 + total) / (1 + frequency)) + 1.0
                    for term, frequency in document_frequency.items()}
        self.idf["__max__"] = max(self.idf.values(), default=1.0)
        self.vectors = [_weighted(counts, self.idf, sublinear) for counts in self.counts]

    # -- single query -----------------------------------------------------
    def vector(self, text: str) -> dict:
        return _weighted(grams(text, self.ns, han=self.han), self.idf, self.sublinear)

    def similarity(self, text: str) -> list[float]:
        query = self.vector(text)
        return [cosine(query, vector) for vector in self.vectors]

    def nearest(self, text: str, k: int = 5) -> list[dict]:
        scores = self.similarity(text)
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:k]
        return [{"index": i, "score": round(scores[i], 6),
                 "label": self.labels[i] if self.labels else None} for i in order]

    # -- corpus-level -----------------------------------------------------
    def centroid_scores(self, text: str) -> dict:
        """Mean similarity to each label's texts, best first."""
        if self.labels is None:
            raise ValueError("需要 labels 才能做语料归属")
        scores = self.similarity(text)
        buckets: dict[str, list[float]] = defaultdict(list)
        for label, score in zip(self.labels, scores):
            buckets[label].append(score)
        ranking = sorted(((label, sum(values) / len(values)) for label, values in buckets.items()),
                         key=lambda row: (-row[1], row[0]))
        return {label: round(score, 6) for label, score in ranking}

    def classify(self, text: str, k: int = 7) -> dict:
        """k-nearest-neighbour vote.  Ties fall back to the centroid ranking."""
        if self.labels is None:
            raise ValueError("需要 labels 才能做归属判断")
        neighbours = self.nearest(text, k=k)
        votes: Counter = Counter()
        for row in neighbours:
            votes[row["label"]] += row["score"]
        total = sum(votes.values())
        if not total:
            return {"label": None, "confidence": 0.0, "neighbours": neighbours,
                    "centroid": self.centroid_scores(text)}
        ranking = sorted(((label, value / total) for label, value in votes.items()),
                         key=lambda row: (-row[1], row[0]))
        return {"label": ranking[0][0], "confidence": round(ranking[0][1], 6),
                "votes": {label: round(value, 6) for label, value in ranking},
                "neighbours": neighbours, "centroid": self.centroid_scores(text)}
