"""Per-poem observations. Line and column numbers refer to the submitted text."""
from collections import Counter
from itertools import groupby
import math
import re
import statistics
import unicodedata

from .corpus import VERSION, digest


def is_han(char):
    return char == "〇" or unicodedata.name(char, "").startswith(("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-"))


def literal_hits(lines, terms):
    """Report overlapping occurrences and keep the entire source line for close reading."""
    result = {term: [] for term in terms}
    for term, hits in result.items():
        if not isinstance(term, str) or not term.strip() or len(term.splitlines()) != 1:
            raise ValueError("检索词须为非空单行文字")
        for row in lines:
            start = 0
            while (pos := row["text"].find(term, start)) != -1:
                hits.append({"line": row["line"], "stanza": row["stanza"], "column": pos + 1, "evidence": row["text"]})
                start = pos + 1
    return result


def extract(poem, terms=()):
    chars, punctuation, bigrams, trigrams, pronouns = (Counter() for _ in range(5))
    lines, lengths = [], []
    stanza, at_boundary = 0, True
    # No Unicode normalization here: evidence offsets must index the original.
    for index, line in enumerate(poem["text"].splitlines(), 1):
        if not line.strip():
            at_boundary = True
            continue
        if at_boundary:
            stanza += 1
            at_boundary = False
        runs = ["".join(group) for han, group in groupby(line, is_han) if han]
        length = sum(map(len, runs))
        lengths.append(length)
        lines.append({"line": index, "stanza": stanza, "text": line, "han_count": length})
        for run in runs:
            chars.update(run)
            bigrams.update(run[i:i+2] for i in range(len(run)-1))
            trigrams.update(run[i:i+3] for i in range(len(run)-2))
        punctuation.update(c for c in line if unicodedata.category(c).startswith("P"))
        pronouns.update(re.findall(r"[我你您他她它牠祂咱][们們]?|吾|余|汝|爾|尔", line))
    n = chars.total()
    return {
        "poem_id": poem["poem_id"], "feature_schema_version": VERSION, "text_hash": digest(poem["text"]),
        "lines": lines,
        "character": {"total": n, "unique": len(chars), "counts": dict(chars),
                      "entropy_bits": -sum((k/n)*math.log2(k/n) for k in chars.values()) if n else None,
                      "repetition_ratio": (n-len(chars))/n if n else None,
                      "bigrams": dict(bigrams), "trigrams": dict(trigrams)},
        "lexical": {"literal_pronouns": dict(pronouns)},
        "syntactic": {"question_mark_lines": [r["line"] for r in lines if re.search("[？?]", r["text"])]},
        "rhythmic": {"line_count": len(lines), "stanza_count": stanza, "line_lengths": lengths,
                     "mean_line_length": statistics.mean(lengths), "line_length_std": statistics.pstdev(lengths),
                     "punctuation_counts": dict(punctuation)},
        "literal_matches": literal_hits(lines, terms),
    }
