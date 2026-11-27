"""Deterministic, offline poetry-style metrics (rpe-poetry-style-v3).

Combines three complementary, offline, zero-dependency signals computed strictly
from the active reference set:
1. Empirical corpus-band alignment (robust IQR/SD Gaussian distance on audited
   lineation, breath-contrast, lexical-recurrence, and function-word features);
2. Leave-one-out calibrated character 1-2 gram sublinear TF-IDF similarity;
3. Anti-mechanical / anti-slop diagnostics (penalising prose line-end punctuation,
   verbatim refrain cloning, vocative fill-in-the-blank templates, and explanatory
   connective overuse).

Character ROUGE-1 is retained strictly as a textual-overlap diagnostic.
"""
from __future__ import annotations

import hashlib
import math
import re
import statistics
import unicodedata
from collections import Counter
from functools import lru_cache

from poetry_agent.style import similarity as ngram_sim
from poetry_agent.style import stylometry
from poetry_agent.style.features import is_han


FUNCTION_CHARS = frozenset(
    "的了在是我你他她它们和与也就都而却把被让使于从向对为以之其而且但或及有无如不没这那一个着过又还很更最将已"
)
PRONOUNS = ("我们", "你们", "他们", "她们", "它们", "我", "你", "您", "他", "她", "它", "自己")

PUNCT = "，。！？；：、,.!?;:'\"“”‘’（）()《》〈〉—…·-"
LINE_END_PUNCT = frozenset("，。！？；：、,.!?;:…—")
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


def _cosine(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    dot = sum(v * right.get(k, 0) for k, v in left.items())
    n1 = math.sqrt(sum(v * v for v in left.values()))
    n2 = math.sqrt(sum(v * v for v in right.values()))
    if n1 == 0 or n2 == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (n1 * n2)))


def _optional_distribution_sim(left: Counter, right: Counter, rate_a: float, rate_b: float, scale: float) -> float:
    """Similarity for sparse/optional markers such as punctuation or pronouns.

    Two unpunctuated free-verse poems share an identical habit (similarity 1.0),
    whereas previous raw cosine returned 0.0 whenever either Counter was empty.
    """
    rate_sim = math.exp(-abs(rate_a - rate_b) / max(scale, 1e-6))
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.65 * rate_sim
    return 0.45 * _cosine(left, right) + 0.55 * rate_sim


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
    return max(0.0, min(1.0, 1.0 - math.sqrt(max(0.0, divergence))))


def _ratio_sim(a, b) -> float:
    a, b = float(a), float(b)
    if a <= 0 and b <= 0:
        return 1.0
    if a <= 0 or b <= 0:
        return 0.0
    return min(a, b) / max(a, b)


def profile(text: str) -> dict:
    """Compact deterministic per-poem feature profile."""
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
        count = text.count(word)
        if count:
            pronouns[word] += count
    question_lines = sum(1 for line in lines if "？" in line or "?" in line)
    exclaim_lines = sum(1 for line in lines if "！" in line or "!" in line)
    short_lines = sum(1 for n in lengths if n <= 4)
    long_lines = sum(1 for n in lengths if n >= 15)
    line_count = len(lines)
    # True unpunctuated break rate (lines not closed by comma/period/etc.)
    if line_count > 1:
        enjambed = sum(1 for line in lines[:-1] if line and line.rstrip()[-1] not in LINE_END_PUNCT)
        enjambment_rate = enjambed / (line_count - 1)
    elif line_count == 1:
        enjambment_rate = 1.0 if lines[0].rstrip()[-1:] not in LINE_END_PUNCT else 0.0
    else:
        enjambment_rate = 0.0
    line_end_punct_rate = (
        sum(1 for line in lines if line and line.rstrip()[-1] in LINE_END_PUNCT) / line_count
        if line_count else 0.0
    )
    mid_space_lines = sum(1 for line in lines if re.search(r"[\u3400-\u9fff]\s+[\u3400-\u9fff]", line))
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
    pronoun_rate = sum(pronouns.values()) / total if total else 0.0
    return {
        "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "char_count": total,
        "line_count": line_count,
        "stanza_count": stanza_count(text),
        "stanza_line_counts": stanza_counts,
        "line_lengths": lengths,
        "enjambment_rate": enjambment_rate,
        "line_end_punct_rate": line_end_punct_rate,
        "mid_line_space_rate": mid_space_lines / line_count if line_count else 0.0,
        "progression_proxy": progression_proxy,
        "mean_line_length": mean_len,
        "std_line_length": std_len,
        "line_length_cv": std_len / mean_len if mean_len > 0 else 0.0,
        "unique_ratio": len(unigrams) / total if total else 0.0,
        "repetition_ratio": 1 - (len(unigrams) / total) if total else 0.0,
        "question_rate": question_lines / line_count if line_count else 0.0,
        "exclaim_rate": exclaim_lines / line_count if line_count else 0.0,
        "short_line_rate": short_lines / line_count if line_count else 0.0,
        "long_line_rate": long_lines / line_count if line_count else 0.0,
        "comma_per_line": (text.count("，") + text.count(",")) / line_count if line_count else 0.0,
        "punct_per_char": sum(punctuation.values()) / total if total else 0.0,
        "pronoun_per_char": pronoun_rate,
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
        _ratio_sim(a["mean_line_length"], b["mean_line_length"]),
        1 - min(1.0, abs(a.get("line_length_cv", 0.0) - b.get("line_length_cv", 0.0)) / 0.35),
        1 - min(1.0, abs(a["repetition_ratio"] - b["repetition_ratio"]) / 0.35),
        1 - min(1.0, abs(a["unique_ratio"] - b["unique_ratio"]) / 0.35),
        1 - abs(a["question_rate"] - b["question_rate"]),
        1 - abs(a["exclaim_rate"] - b["exclaim_rate"]),
        1 - abs(a["short_line_rate"] - b["short_line_rate"]),
        1 - abs(a["long_line_rate"] - b["long_line_rate"]),
        1 - min(1.0, abs(a.get("line_end_punct_rate", 0.0) - b.get("line_end_punct_rate", 0.0))),
        1 - min(1.0, abs(a["punct_per_char"] - b["punct_per_char"]) / 0.15),
    ]
    return sum(max(0.0, min(1.0, p)) for p in parts) / len(parts)


STYLE_WEIGHTS = {
    "character_bigram": 0.05,
    "character_unigram": 0.06,
    "function_chars": 0.16,
    "line_length": 0.14,
    "punctuation": 0.13,
    "line_endings": 0.03,
    "line_starts": 0.04,
    "stanza_shape": 0.08,
    "enjambment": 0.11,
    "structure": 0.14,
    "progression": 0.0,  # Surface diagnostic; insensitive to line order.
    "pronouns": 0.06,
}

# Audited corpus-band features (rpe-poetry-style-v6: centers Poetic Core persistence
# via core_motif_span & core_lexical_focus, guards sculptural sharpness via comma_per_line
# & line_length_cv, and suppresses scattered simile drift & inverted novelty noise).
FEATURE_SCHEMA = "rpe-poetry-style-v6"
BAND_WEIGHTS = {
    "core_motif_span": 0.11,
    "line_length_cv": 0.11,
    "unpunctuated_break_rate": 0.09,
    "core_lexical_focus": 0.08,
    "clause_length_cv": 0.07,
    "comma_per_line": 0.07,
    "line_end_punct_rate": 0.06,
    "simile_stanza_rate": 0.06,
    "repetition_ratio": 0.06,
    "first_last_return": 0.05,
    "primal_per_100": 0.05,
    "mid_line_space_rate": 0.04,
    "body_per_100": 0.04,
    "copula_per_100": 0.03,
    "vital_affect_per_100": 0.03,
    "pronoun_per_100": 0.03,
    "mid_stanza_novelty": 0.01,
    "short_line_rate": 0.01,
}

MIN_FEATURE_SCALES = {
    "core_motif_span": 0.10,
    "core_lexical_focus": 0.02,
    "line_length_cv": 0.06,
    "clause_length_cv": 0.06,
    "comma_per_line": 0.12,
    "simile_stanza_rate": 0.12,
    "unpunctuated_break_rate": 0.08,
    "line_end_punct_rate": 0.08,
    "mid_line_space_rate": 0.08,
    "repetition_ratio": 0.05,
    "hapax_ratio": 0.05,
    "stanza_return_rate": 0.04,
    "first_last_return": 0.04,
    "mid_stanza_novelty": 0.08,
    "anaphora_rate": 0.04,
    "function_char_ratio": 0.04,
    "modifier_de_per_100": 1.5,
    "copula_per_100": 0.6,
    "short_line_rate": 0.06,
    "concrete_char_per_100": 2.0,
    "body_per_100": 1.0,
    "primal_per_100": 1.5,
    "vital_affect_per_100": 1.0,
    "abstract_per_100": 0.9,
    "pronoun_per_100": 1.2,
    "stanza_length_cv": 0.08,
}


def compare_profiles(gen: dict, ref: dict) -> dict:
    components = {
        "character_bigram": _cosine(gen["bigrams"], ref["bigrams"]),
        "character_unigram": _cosine(gen["unigrams"], ref["unigrams"]),
        "function_chars": _cosine(gen["function_chars"], ref["function_chars"]),
        "line_length": _js_similarity(_hist(gen["line_lengths"]), _hist(ref["line_lengths"])),
        "punctuation": _optional_distribution_sim(
            gen["punctuation"], ref["punctuation"],
            gen.get("punct_per_char", 0.0), ref.get("punct_per_char", 0.0), 0.08,
        ),
        "line_endings": _cosine(gen["line_end_chars"], ref["line_end_chars"]),
        "line_starts": _cosine(gen["line_start_chars"], ref["line_start_chars"]),
        "stanza_shape": _js_similarity(
            _hist(gen["stanza_line_counts"], upto=12),
            _hist(ref["stanza_line_counts"], upto=12),
        ),
        "enjambment": 1 - abs(gen["enjambment_rate"] - ref["enjambment_rate"]),
        "progression": 1 - abs(gen["progression_proxy"] - ref["progression_proxy"]),
        "structure": _structure_similarity(gen, ref),
        "pronouns": _optional_distribution_sim(
            gen["pronouns"], ref["pronouns"],
            gen.get("pronoun_per_char", 0.0), ref.get("pronoun_per_char", 0.0), 0.04,
        ),
    }
    score = sum(STYLE_WEIGHTS[k] * components[k] for k in STYLE_WEIGHTS)
    return {"score": 100.0 * score, "components": components}


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_vals[lo])
    w = pos - lo
    return float(sorted_vals[lo] * (1.0 - w) + sorted_vals[hi] * w)


@lru_cache(maxsize=32)
def _build_reference_model(ref_tuple: tuple[str, ...]) -> dict:
    ref_profiles = [profile(text) for text in ref_tuple]
    stylo_profiles = [stylometry.profile(text) for text in ref_tuple]
    bands = {}
    all_keys = set(BAND_WEIGHTS) | {
        "repeated_line_rate", "connective_per_100", "simile_per_100", "simile_stanza_rate",
        "abstract_per_100", "vital_affect_per_100", "median_line_length", "pronoun_per_100",
        "concrete_char_per_100", "stanza_head_clone_rate", "net_cliche_per_100",
        "simile_ending_flag", "tame_putdown_flag", "anaphora_rate", "modifier_de_per_100",
        "stanza_length_cv", "hapax_ratio", "function_char_ratio", "stanza_return_rate",
    }
    for feat in all_keys:
        vals = sorted(float(sp[feat]) for sp in stylo_profiles)
        p10 = _quantile(vals, 0.10)
        p25 = _quantile(vals, 0.25)
        med = _quantile(vals, 0.50)
        p75 = _quantile(vals, 0.75)
        p90 = _quantile(vals, 0.90)
        iqr = p75 - p25
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        scale = max(iqr / 1.349, sd, MIN_FEATURE_SCALES.get(feat, 0.05))
        bands[feat] = {
            "p10": p10, "p25": p25, "median": med, "p75": p75, "p90": p90,
            "iqr": iqr, "sd": sd, "scale": scale,
        }
    tfidf_index = ngram_sim.Index(list(ref_tuple), ns=(1, 2), sublinear=True, han=True)
    if len(ref_tuple) > 1:
        loo_scores = []
        for i in range(len(ref_tuple)):
            others = [
                ngram_sim.cosine(tfidf_index.vectors[i], tfidf_index.vectors[j])
                for j in range(len(ref_tuple)) if j != i
            ]
            loo_scores.append(0.5 * (sum(others) / len(others) + max(others)))
        loo_sorted = sorted(loo_scores)
        tfidf_anchor = max(0.03, _quantile(loo_sorted, 0.85) * 1.12)
    else:
        tfidf_anchor = 1.0
    return {
        "ref_profiles": ref_profiles,
        "stylo_profiles": stylo_profiles,
        "bands": bands,
        "tfidf_index": tfidf_index,
        "tfidf_anchor": tfidf_anchor,
    }


def _anti_slop_diagnostics(gen_text: str, gen_stylo: dict, bands: dict) -> dict:
    flags = []
    penalty = 0.0

    ref_end_med = bands["line_end_punct_rate"]["median"]
    if ref_end_med < 0.25 and gen_stylo["line_end_punct_rate"] > 0.45:
        excess = gen_stylo["line_end_punct_rate"] - 0.45
        p = min(0.18, excess * 0.34)
        penalty += p
        flags.append({
            "code": "prose_line_end_punctuation",
            "detail": f"行末标点率 {gen_stylo['line_end_punct_rate']:.2f} 远高于参考中位数 {ref_end_med:.2f}",
            "penalty": round(p * 100.0, 3),
        })

    rep_cap = max(0.22, bands["repeated_line_rate"]["p90"] + 0.06)
    if gen_stylo["repeated_line_rate"] > rep_cap:
        excess = gen_stylo["repeated_line_rate"] - rep_cap
        p = min(0.15, excess * 0.55)
        penalty += p
        flags.append({
            "code": "mechanical_line_repetition",
            "detail": f"整行原样重复率 {gen_stylo['repeated_line_rate']:.2f} 超过参考上界 {rep_cap:.2f}",
            "penalty": round(p * 100.0, 3),
        })

    stz = stylometry.stanzas(gen_text)
    if len(stz) >= 3:
        vocative_heads = sum(
            1 for s in stz if s and re.match(r"^[^，,。！？]{1,6}[，,]\s*(?:[^，,。！？]{1,6}[，,]\s*)?你", s[0])
        )
        numbered_heads = sum(
            1 for s in stz if s and re.match(r"^第[一二三四五六七八九十\d]+", s[0])
        )
        head_clone_rate = float(gen_stylo.get("stanza_head_clone_rate", 0.0))
        if vocative_heads >= 3 or numbered_heads >= 3:
            penalty += 0.10
            flags.append({
                "code": "stanza_head_template_cloning",
                "detail": "至少三节首行机械套用同一呼告或编号填空模板",
                "penalty": 10.0,
            })
        elif head_clone_rate >= 0.50:
            p = min(0.10, 0.05 + (head_clone_rate - 0.50) * 0.10)
            penalty += p
            flags.append({
                "code": "stanza_head_template_cloning",
                "detail": f"至少三节首行使用同一前导词顶格领起（同头克隆率 {head_clone_rate:.2f}），位置缺乏错落变奏",
                "penalty": round(p * 100.0, 3),
            })

    space_cap = max(0.50, bands["mid_line_space_rate"]["p90"] + 0.06)
    if gen_stylo.get("mid_line_space_rate", 0.0) > space_cap:
        p = min(0.10, (gen_stylo["mid_line_space_rate"] - space_cap) * 0.28)
        penalty += p
        flags.append({
            "code": "telegraph_mid_line_spacing",
            "detail": f"行内空格断句率 {gen_stylo['mid_line_space_rate']:.2f} 过高（参考上界 {space_cap:.2f}），流于逐行劈半的碎电报体",
            "penalty": round(p * 100.0, 3),
        })

    comma_cap = max(0.42, bands["comma_per_line"]["p90"] + 0.08)
    if gen_stylo.get("comma_per_line", 0.0) > comma_cap:
        p = min(0.11, (gen_stylo["comma_per_line"] - comma_cap) * 0.22)
        penalty += p
        flags.append({
            "code": "mid_line_prose_commas",
            "detail": f"每行逗号数 {gen_stylo['comma_per_line']:.2f} 过高（参考上界 {comma_cap:.2f}），退化为行内带逗的日常散文分句",
            "penalty": round(p * 100.0, 3),
        })

    if (
        gen_stylo.get("stanza_count", 1) >= 3
        and gen_stylo.get("core_motif_span", 1.0) < 0.42
        and gen_stylo.get("core_lexical_focus", 1.0) < 0.10
    ):
        p = min(0.09, 0.04 + (0.42 - gen_stylo["core_motif_span"]) * 0.25)
        penalty += p
        flags.append({
            "code": "core_motif_dispersion",
            "detail": (
                f"主核意象跨节贯通率仅 {gen_stylo['core_motif_span']:.2f} 且核心实字凝聚度 {gen_stylo['core_lexical_focus']:.2f} 偏散，"
                "各节更换外围道具而缺乏贯穿全篇的唯一诗核"
            ),
            "penalty": round(p * 100.0, 3),
        })

    sim_stz_rate = float(gen_stylo.get("simile_stanza_rate", 0.0))
    sim_cap = max(0.85, bands["simile_per_100"]["p90"] + 0.35)
    if (gen_stylo.get("stanza_count", 1) >= 2 and sim_stz_rate >= 0.50) or gen_stylo["simile_per_100"] > sim_cap:
        p = min(0.10, max(0.04, (sim_stz_rate - 0.30) * 0.16, (gen_stylo["simile_per_100"] - sim_cap) * 0.06))
        penalty += p
        flags.append({
            "code": "scattered_simile_drift",
            "detail": (
                f"贴喻节率 {sim_stz_rate:.2f}（明喻 {gen_stylo['simile_per_100']:.2f}/百字）偏高，"
                "靠多节‘像……’更换散珠比喻代替唯一本体诗核"
            ),
            "penalty": round(p * 100.0, 3),
        })

    if gen_stylo.get("tame_putdown_flag", 0):
        penalty += 0.05
        flags.append({
            "code": "tame_putdown_closure",
            "detail": "结尾套用‘轻轻合上/放进抽屉/弯腰捡起/捏着’等万能轻放动作安全退场，回避诗核刺破与决断",
            "penalty": 5.0,
        })

    body_cap = max(5.2, bands["body_per_100"]["p90"] + 1.4)
    if (
        gen_stylo.get("body_per_100", 0.0) > body_cap
        and gen_stylo.get("vital_affect_per_100", 0.0) < 0.8
        and gen_stylo.get("abstract_per_100", 0.0) < 0.5
    ):
        p = min(0.08, 0.03 + (gen_stylo["body_per_100"] - body_cap) * 0.025)
        penalty += p
        flags.append({
            "code": "cold_anatomical_inventory",
            "detail": (
                f"身体器官词密度 {gen_stylo['body_per_100']:.2f}/百字 超过参考上界 {body_cap:.2f} "
                f"且赤诚情感/生命直陈词近乎清零（{gen_stylo.get('vital_affect_per_100', 0.0):.2f}/百字），流于有物无情的冷硬词壳清点"
            ),
            "penalty": round(p * 100.0, 3),
        })

    if gen_stylo.get("net_cliche_per_100", 0.0) > 0:
        p = min(0.08, gen_stylo["net_cliche_per_100"] * 0.04)
        penalty += p
        flags.append({
            "code": "net_lyric_cliche",
            "detail": f"出现当代网文抒情套话词（{gen_stylo['net_cliche_per_100']:.2f}/百字）",
            "penalty": round(p * 100.0, 3),
        })

    if gen_stylo.get("simile_ending_flag", 0) and bands["simile_ending_flag"]["p90"] == 0:
        penalty += 0.04
        flags.append({
            "code": "simile_ending",
            "detail": "末行以明喻收尾封死余响（参考诗末行零明喻）",
            "penalty": 4.0,
        })

    conn_cap = max(1.4, bands["connective_per_100"]["p90"] * 1.35)
    if gen_stylo["connective_per_100"] > conn_cap:
        p = min(0.10, (gen_stylo["connective_per_100"] - conn_cap) * 0.06)
        penalty += p
        flags.append({
            "code": "explanatory_connectives",
            "detail": f"解释性连词 {gen_stylo['connective_per_100']:.2f}/百字 偏多",
            "penalty": round(p * 100.0, 3),
        })

    if gen_stylo["line_count"] >= 8 and gen_stylo["line_length_cv"] < 0.20 and bands["line_length_cv"]["median"] > 0.25:
        p = min(0.09, (0.20 - gen_stylo["line_length_cv"]) * 0.65)
        penalty += p
        flags.append({
            "code": "uniform_line_lengths",
            "detail": f"行长变异系数 {gen_stylo['line_length_cv']:.2f} 过平，缺少奔涌长句与陡峭短行的呼吸对比",
            "penalty": round(p * 100.0, 3),
        })

    return {"penalty": round(min(0.35, penalty), 6), "flags": flags}


def style_similarity(generated_text: str, reference_texts: list[str]) -> dict:
    if not reference_texts:
        raise ValueError("style_similarity 需要至少一篇参考文本")
    ref_tuple = tuple(reference_texts)
    model = _build_reference_model(ref_tuple)
    gen = profile(generated_text)
    gen_stylo = stylometry.profile(generated_text)

    rows = []
    component_rows = []
    for index, ref_prof in enumerate(model["ref_profiles"], 1):
        result = compare_profiles(gen, ref_prof)
        rows.append({
            "reference": index,
            "score": round(result["score"], 4),
            "components": {k: round(v, 6) for k, v in result["components"].items()},
        })
        component_rows.append(result["components"])
    pairwise_scores = [row["score"] for row in rows]
    mean_components = {
        key: round(sum(row[key] for row in component_rows) / len(component_rows), 6)
        for key in STYLE_WEIGHTS
    }
    pairwise_mean = (sum(pairwise_scores) / len(pairwise_scores)) / 100.0

    # Corpus-band score across empirically validated stylometric features
    bands = model["bands"]
    band_components = {}
    for feat, weight in BAND_WEIGHTS.items():
        b = bands[feat]
        val = float(gen_stylo[feat])
        if b["p25"] <= val <= b["p75"]:
            z = 0.20 * abs(val - b["median"]) / b["scale"]
        else:
            edge = b["p25"] if val < b["p25"] else b["p75"]
            z = 0.20 * abs(edge - b["median"]) / b["scale"] + abs(val - edge) / b["scale"]
        band_components[feat] = round(math.exp(-0.5 * z * z), 6)
    band_sim = sum(BAND_WEIGHTS[k] * band_components[k] for k in BAND_WEIGHTS) / sum(BAND_WEIGHTS.values())

    # Sublinear char 1-2 gram TF-IDF lexical resonance
    tfidf_sims = model["tfidf_index"].similarity(generated_text)
    raw_tfidf = 0.5 * (sum(tfidf_sims) / len(tfidf_sims) + max(tfidf_sims))
    tfidf_sim = min(1.0, raw_tfidf / model["tfidf_anchor"])

    slop = _anti_slop_diagnostics(generated_text, gen_stylo, bands)
    composite = max(0.0, min(1.0, 0.52 * band_sim + 0.26 * tfidf_sim + 0.22 * pairwise_mean - slop["penalty"]))
    score = 100.0 * composite
    if any(generated_text == ref for ref in ref_tuple):
        score = 100.0

    return {
        "score": round(score, 4),
        "mean": round(sum(pairwise_scores) / len(pairwise_scores), 4),
        "max": round(max(pairwise_scores), 4),
        "min": round(min(pairwise_scores), 4),
        "std": round(statistics.pstdev(pairwise_scores), 4) if len(pairwise_scores) > 1 else 0.0,
        "corpus_band_score": round(100.0 * band_sim, 4),
        "tfidf_lexical_score": round(100.0 * tfidf_sim, 4),
        "pairwise_profile_score": round(100.0 * pairwise_mean, 4),
        "anti_slop_penalty": round(100.0 * slop["penalty"], 4),
        "anti_slop_flags": slop["flags"],
        "band_components": band_components,
        "per_reference": rows,
        "mean_components": mean_components,
        "feature_schema": FEATURE_SCHEMA,
        "notes": "满分100；v6聚焦诗核贯通与刀锋骨力：语料分位带对齐(0.52：含主核意象跨节贯通率core_motif_span、核心实字凝聚度core_lexical_focus、长短句落差、零行内散文逗号与零贴喻漂移)、字符1-2gram TF-IDF共鸣(0.26)、逐篇结构特征(0.22)，并严惩散珠贴喻、无核漂移、行内逗号散文化及套路轻放收尾。",
    }


def corpus_stylometry_summary(reference_texts: list[str]) -> dict:
    """Anonymous quantitative distribution summary of the reference set for prompting/analysis."""
    if not reference_texts:
        return {}
    model = _build_reference_model(tuple(reference_texts))
    bands = model["bands"]
    selected = (
        "core_motif_span", "core_lexical_focus",
        "median_line_length", "line_length_cv", "clause_length_cv", "short_line_rate",
        "unpunctuated_break_rate", "line_end_punct_rate", "comma_per_line", "mid_line_space_rate",
        "repetition_ratio", "stanza_return_rate", "first_last_return",
        "anaphora_rate", "function_char_ratio", "copula_per_100",
        "body_per_100", "primal_per_100", "pronoun_per_100",
        "vital_affect_per_100", "abstract_per_100", "connective_per_100",
        "simile_per_100", "simile_stanza_rate",
    )
    return {
        key: {
            "p10": round(bands[key]["p10"], 3),
            "median": round(bands[key]["median"], 3),
            "p90": round(bands[key]["p90"], 3),
        }
        for key in selected if key in bands
    }


def diagnose_poem_vs_corpus(generated_text: str, reference_texts: list[str]) -> dict:
    """Return concrete surface deviations between one generated poem and reference bands."""
    if not reference_texts:
        return {"deviations": [], "anti_slop_flags": []}
    model = _build_reference_model(tuple(reference_texts))
    bands = model["bands"]
    gp = stylometry.profile(generated_text)
    labels = stylometry.FEATURE_LABELS
    deviations = []
    for feat in BAND_WEIGHTS:
        b = bands[feat]
        val = float(gp[feat])
        if val < b["p10"]:
            deviations.append(f"{labels.get(feat, feat)}偏低（生成 {val:.2f} < 参考p10 {b['p10']:.2f}，中位数 {b['median']:.2f}）")
        elif val > b["p90"]:
            deviations.append(f"{labels.get(feat, feat)}偏高（生成 {val:.2f} > 参考p90 {b['p90']:.2f}，中位数 {b['median']:.2f}）")
    slop = _anti_slop_diagnostics(generated_text, gp, bands)
    return {"deviations": deviations[:6], "anti_slop_flags": slop["flags"]}


def prompt_similarity(left_prompt: str, right_prompt: str) -> float:
    """Character 1-2 gram cosine between two prompts for population niching."""
    a = ngram_sim.grams(left_prompt, ns=(1, 2), han=True)
    b = ngram_sim.grams(right_prompt, ns=(1, 2), han=True)
    return _cosine(a, b)


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
