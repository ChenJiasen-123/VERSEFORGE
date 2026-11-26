"""Deterministic, offline poetry-style metrics.

These metrics are proxies.  They are reported separately from the LLM judge
and are never treated as a direct measurement of literary style.  Character
ROUGE-1 is retained as a *diagnostic* for textual overlap only.
"""
from __future__ import annotations

import hashlib
import math
import re
import statistics
import unicodedata
from collections import Counter

from poetry_agent.style.features import is_han


FUNCTION_CHARS = frozenset(
    "的了在是我你他她它们和与也就都而却把被让使于从向对为以之其而且但或及有无如不没这那一个着过又还很更最将已"
)
PRONOUNS = ("我们", "你们", "他们", "她们", "它们", "我", "你", "您", "他", "她", "它", "自己")

PUNCT = "，。！？；：、,.!?;:'\"“”‘’（）()《》〈〉—…·-"
TURN_MARKERS = (
    "但", "却", "而", "又", "再", "然后", "接着", "于是", "忽然", "终于",
    "直到", "后来", "等到", "开始", "继续", "停下", "离开", "回来", "转向",
    "变成", "成为", "已经", "将要", "从此",
)


def han_only(text: str) -> str:
    return "".join(ch for ch in text if is_han(ch))


def nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def stanza_count(text: str) -> int:
    count, in_stanza = 0, False
    for line in text.splitlines():
        if line.strip():
            if not in_stanza:
                count += 1
                in_stanza = True
        else:
            in_stanza = False
    return count


def stanza_line_counts(text: str) -> list[int]:
    counts, current = [], 0
    for line in text.splitlines():
        if line.strip():
            current += 1
        elif current:
            counts.append(current)
            current = 0
    if current:
        counts.append(current)
    return counts


def _counter(values):
    return Counter(values)


def _cosine(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    dot = sum(v * right.get(k, 0) for k, v in left.items())
    n1 = math.sqrt(sum(v * v for v in left.values()))
    n2 = math.sqrt(sum(v * v for v in right.values()))
    if n1 == 0 or n2 == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (n1 * n2)))


def _hist(values, upto=40):
    counts = Counter()
    for value in values:
        counts[min(upto, max(1, int(value)))] += 1
    total = sum(counts.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def _js_similarity(left: dict, right: dict) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 1.0
    divergence = 0.0
    for key in keys:
        p = left.get(key, 0.0)
        q = right.get(key, 0.0)
        m = (p + q) / 2
        if p > 0:
            divergence += 0.5 * p * math.log2(p / m)
        if q > 0:
            divergence += 0.5 * q * math.log2(q / m)
    # JS divergence is in [0,1] for base-2; sqrt is a metric.
    return max(0.0, min(1.0, 1.0 - math.sqrt(max(0.0, divergence))))


def _ratio_sim(a, b) -> float:
    a, b = float(a), float(b)
    if a <= 0 and b <= 0:
        return 1.0
    if a <= 0 or b <= 0:
        return 0.0
    return min(a, b) / max(a, b)


def profile(text: str) -> dict:
    """A compact, deterministic feature profile.  Counts are normalized later."""
    lines = nonempty_lines(text)
    han_lines = [han_only(line) for line in lines]
    lengths = [len(line) for line in han_lines]
    han = "".join(han_lines)
    total = len(han)
    unigrams = Counter(han)
    bigrams = Counter(han[i:i + 2] for i in range(max(0, len(han) - 1)))
    function = Counter(ch for ch in han if ch in FUNCTION_CHARS)
    punctuation = Counter(ch for ch in text if ch in PUNCT or unicodedata.category(ch).startswith("P"))
    line_end = Counter(line[-1] for line in han_lines if line)
    line_start = Counter(line[0] for line in han_lines if line)
    pronouns = Counter()
    for word in PRONOUNS:
        pronouns[word] += text.count(word)
    question_lines = sum(1 for line in lines if "？" in line or "?" in line)
    exclaim_lines = sum(1 for line in lines if "！" in line or "!" in line)
    short_lines = sum(1 for n in lengths if n <= 4)
    long_lines = sum(1 for n in lengths if n >= 15)
    terminal = ("。", "！", "？", ".", "!", "?", "；", ";")
    enjambed = sum(1 for line in lines if not line.rstrip().endswith(terminal))
    line_count = len(lines)
    stanza_counts = stanza_line_counts(text)
    turn_lines = sum(1 for line in lines if any(marker in line for marker in TURN_MARKERS))
    turn_rate = turn_lines / line_count if line_count else 0.0
    start_variety = len(line_start) / line_count if line_count else 0.0
    stanza_variation = (
        statistics.pstdev(stanza_counts) / statistics.mean(stanza_counts)
        if len(stanza_counts) > 1 and statistics.mean(stanza_counts) > 0 else 0.0
    )
    progression_proxy = (
        0.5 * min(1.0, turn_rate * 2.0) +
        0.3 * start_variety +
        0.2 * min(1.0, stanza_variation)
    )
    mean_len = statistics.mean(lengths) if lengths else 0.0
    std_len = statistics.pstdev(lengths) if len(lengths) > 1 else 0.0
    return {
        "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "char_count": total,
        "line_count": line_count,
        "stanza_count": stanza_count(text),
        "stanza_line_counts": stanza_line_counts(text),
        "line_lengths": lengths,
        "enjambment_rate": enjambed / line_count if line_count else 0.0,
        "progression_proxy": progression_proxy,
        "mean_line_length": mean_len,
        "std_line_length": std_len,
        "unique_ratio": len(unigrams) / total if total else 0.0,
        "repetition_ratio": 1 - (len(unigrams) / total) if total else 0.0,
        "question_rate": question_lines / line_count if line_count else 0.0,
        "exclaim_rate": exclaim_lines / line_count if line_count else 0.0,
        "short_line_rate": short_lines / line_count if line_count else 0.0,
        "long_line_rate": long_lines / line_count if line_count else 0.0,
        "comma_per_line": (text.count("，") + text.count(",")) / line_count if line_count else 0.0,
        "punct_per_char": sum(punctuation.values()) / total if total else 0.0,
        "unigrams": unigrams,
        "bigrams": bigrams,
        "function_chars": function,
        "punctuation": punctuation,
        "line_end_chars": line_end,
        "line_start_chars": line_start,
        "pronouns": pronouns,
    }


def _structure_similarity(a: dict, b: dict) -> float:
    parts = [
        _ratio_sim(a["line_count"], b["line_count"]),
        _ratio_sim(a["stanza_count"], b["stanza_count"]),
        _ratio_sim(a["mean_line_length"], b["mean_line_length"]),
        1 - min(1.0, abs(a["std_line_length"] - b["std_line_length"]) / max(a["mean_line_length"], b["mean_line_length"], 1.0)),
        1 - abs(a["repetition_ratio"] - b["repetition_ratio"]),
        1 - abs(a["unique_ratio"] - b["unique_ratio"]),
        1 - abs(a["question_rate"] - b["question_rate"]),
        1 - abs(a["exclaim_rate"] - b["exclaim_rate"]),
        1 - abs(a["short_line_rate"] - b["short_line_rate"]),
        1 - abs(a["long_line_rate"] - b["long_line_rate"]),
        1 - abs(a["comma_per_line"] - b["comma_per_line"]) / max(a["comma_per_line"], b["comma_per_line"], 1.0),
        1 - abs(a["punct_per_char"] - b["punct_per_char"]) / max(a["punct_per_char"], b["punct_per_char"], 0.1),
    ]
    return sum(max(0.0, min(1.0, p)) for p in parts) / len(parts)


STYLE_WEIGHTS = {
    "character_bigram": 0.09,
    "character_unigram": 0.054,
    "function_chars": 0.144,
    "line_length": 0.108,
    "punctuation": 0.063,
    "line_endings": 0.072,
    "line_starts": 0.072,
    "stanza_shape": 0.072,
    "enjambment": 0.045,
    "structure": 0.126,
    "progression": 0.10,
    "pronouns": 0.054,
}


def compare_profiles(gen: dict, ref: dict) -> dict:
    components = {
        "character_bigram": _cosine(gen["bigrams"], ref["bigrams"]),
        "character_unigram": _cosine(gen["unigrams"], ref["unigrams"]),
        "function_chars": _cosine(gen["function_chars"], ref["function_chars"]),
        "line_length": _js_similarity(_hist(gen["line_lengths"]), _hist(ref["line_lengths"])),
        "punctuation": _cosine(gen["punctuation"], ref["punctuation"]),
        "line_endings": _cosine(gen["line_end_chars"], ref["line_end_chars"]),
        "line_starts": _cosine(gen["line_start_chars"], ref["line_start_chars"]),
        "stanza_shape": _js_similarity(_hist(gen["stanza_line_counts"], upto=12), _hist(ref["stanza_line_counts"], upto=12)),
        "enjambment": 1 - abs(gen["enjambment_rate"] - ref["enjambment_rate"]),
        "progression": 1 - abs(gen["progression_proxy"] - ref["progression_proxy"]),
        "structure": _structure_similarity(gen, ref),
        "pronouns": _cosine(gen["pronouns"], ref["pronouns"]),
    }
    score = sum(STYLE_WEIGHTS[k] * components[k] for k in STYLE_WEIGHTS)
    return {"score": 100.0 * score, "components": components}


def style_similarity(generated_text: str, reference_texts: list[str]) -> dict:
    if not reference_texts:
        raise ValueError("style_similarity 需要至少一篇参考文本")
    gen = profile(generated_text)
    rows = []
    component_rows = []
    for index, ref_text in enumerate(reference_texts, 1):
        ref = profile(ref_text)
        result = compare_profiles(gen, ref)
        rows.append({"reference": index, "score": round(result["score"], 4),
                     "components": {k: round(v, 6) for k, v in result["components"].items()}})
        component_rows.append(result["components"])
    scores = [row["score"] for row in rows]
    mean_components = {
        key: round(sum(row[key] for row in component_rows) / len(component_rows), 6)
        for key in STYLE_WEIGHTS
    }
    return {
        "score": round(sum(scores) / len(scores), 4),
        "mean": round(sum(scores) / len(scores), 4),
        "max": round(max(scores), 4),
        "min": round(min(scores), 4),
        "std": round(statistics.pstdev(scores), 4) if len(scores) > 1 else 0.0,
        "per_reference": rows,
        "mean_components": mean_components,
        "feature_schema": "rpe-poetry-style-v1",
        "notes": "满分100；逐项为生成诗与每篇参考诗的特征相似度，主分取与各参考诗的均值。",
    }


def rouge1_char(prediction: str, reference: str) -> dict:
    """Character unigram ROUGE-1, an adaptation for Chinese without a segmenter."""
    pred = Counter(han_only(prediction))
    ref = Counter(han_only(reference))
    overlap = sum(min(v, ref.get(k, 0)) for k, v in pred.items())
    pred_total = sum(pred.values())
    ref_total = sum(ref.values())
    precision = overlap / pred_total if pred_total else 0.0
    recall = overlap / ref_total if ref_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def longest_common_substring_length(left: str, right: str) -> int:
    """Longest common contiguous Han substring (O(n*m), inputs are short poems)."""
    a, b = han_only(left), han_only(right)
    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                current[j] = previous[j - 1] + 1
                if current[j] > best:
                    best = current[j]
        previous = current
    return best


def copy_diagnostics(generated_text: str, reference_texts: list[str], *, lcs_chars=12,
                     line_chars=8, rouge1_cap=0.80) -> dict:
    gen_norm = re.sub(r"[\s\W_]+", "", generated_text, flags=re.UNICODE)
    max_lcs = 0
    max_rouge = 0.0
    matched_lines = []
    for index, ref in enumerate(reference_texts, 1):
        max_lcs = max(max_lcs, longest_common_substring_length(generated_text, ref))
        rouge = rouge1_char(generated_text, ref)
        max_rouge = max(max_rouge, rouge["f1"])
        for line in nonempty_lines(ref):
            norm = re.sub(r"[\s\W_]+", "", line, flags=re.UNICODE)
            if len(norm) >= line_chars and norm in gen_norm:
                matched_lines.append({"reference": index, "line": line, "han_length": len(norm)})
    copy_flag = max_lcs >= lcs_chars or bool(matched_lines) or max_rouge >= rouge1_cap
    return {
        "max_lcs_chars": max_lcs,
        "max_rouge1_f1": round(max_rouge, 6),
        "matched_reference_lines": matched_lines,
        "copy_flag": copy_flag,
        "thresholds": {"lcs_chars": lcs_chars, "line_chars": line_chars, "rouge1_f1": rouge1_cap},
        "note": "ROUGE-1 仅作文本重合诊断，不作为风格得分；高重合不等于风格模仿成功。",
    }


def reference_diversity(reference_texts: list[str]) -> dict:
    """Pairwise reference similarity, useful to show that references are not copies."""
    scores = []
    for i in range(len(reference_texts)):
        for j in range(i + 1, len(reference_texts)):
            scores.append(style_similarity(reference_texts[i], [reference_texts[j]])["score"])
    return {
        "pairs": len(scores),
        "mean_style_similarity": round(sum(scores) / len(scores), 4) if scores else None,
        "max_style_similarity": round(max(scores), 4) if scores else None,
        "min_style_similarity": round(min(scores), 4) if scores else None,
    }
