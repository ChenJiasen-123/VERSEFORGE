"""Topic-robust surface stylometry for Chinese modern poetry.

This module deliberately reports *observable distributions*, not a literary
quality score.  A feature being inside a poet's band does not make a poem good;
it only says the text shares a measurable surface habit with that corpus.

Design notes
------------
* Character-level features avoid a Chinese word segmenter dependency.
* Corpus profiles keep the full value distribution so a new text can be placed
  inside a p10--p90 "human band" instead of being compared by raw cosine to a
  handful of reference poems.
* ``anti_slop_flags`` are diagnostics for prose-like or generic-LLM habits.
  They are not aesthetic verdicts.
"""
from __future__ import annotations

import math
import re
import statistics
import unicodedata
from collections import Counter

VERSION = "modern-stylometry-v1"

PUNCT = frozenset("，。！？；：、,.!?;:…—·-（）()《》〈〉“”‘’\"'")
LINE_END_PUNCT = frozenset("，。！？；：、,.!?;:…—")
COMMA = frozenset("，,、；;：:")
DASH_ELLIPSIS = frozenset("—…-·")

FUNCTION_CHARS = frozenset(
    "的了在是我你他她它们和与也就都而却把被让使于从向对为以之其而且但或及有无如不没这那一个着过又还很更最将已"
)

PRONOUNS = (
    "我们", "你们", "他们", "她们", "它们", "咱们", "自己",
    "我", "你", "您", "他", "她", "它",
)

ABSTRACT_WORDS = (
    "灵魂", "时间", "生命", "世界", "孤独", "远方", "岁月", "时光", "温暖", "温柔",
    "希望", "梦想", "永恒", "自由", "命运", "记忆", "死亡", "悲伤", "幸福", "痛苦",
    "空虚", "虚无", "意义", "真理", "精神", "心灵", "思想", "情感", "情绪", "生活",
    "人生", "历史", "未来", "过去", "存在", "本质", "理想", "信仰", "诗意", "忧伤",
    "寂寞", "惆怅", "迷惘", "绝望", "渴望", "思念", "怀念", "眷恋", "乡愁", "青春",
    "爱情", "亲情", "友情", "人性", "神性", "宇宙", "归宿", "美好", "治愈", "流年",
)

GENERIC_WORDS = (
    "时光", "岁月", "远方", "灵魂", "温暖", "温柔", "孤独", "美好", "希望", "梦想",
    "永恒", "自由", "命运", "记忆", "流年", "红尘", "心间", "心底", "眼眸", "微笑",
    "眼泪", "悲伤", "幸福", "寂寞", "迷惘", "惆怅", "忧伤", "眷恋", "思念", "治愈",
    "诗意", "烟火", "人间", "山河", "星辰", "大海",
)

CONNECTIVES = (
    "因为", "所以", "于是", "然而", "但是", "因此", "其实", "虽然", "如果", "由于",
    "并且", "而且", "不过", "可是", "接着", "然后", "最后", "终于",
)

SIMILE_MARKERS = ("像", "仿佛", "好像", "如同", "宛如", "犹如", "似的", "恰似")

IMPERATIVE_START = ("请", "让", "愿", "别", "不要", "来", "去", "看", "听", "记住", "告诉")

SUMMARY_MARKERS = (
    "就是", "终将", "原来", "所以", "因此", "一切", "所有", "我们", "这世界",
    "生活", "人生", "幸福", "孤独", "远方", "爱", "是",
)

# A coarse surface lexicon.  It is intentionally named "concrete_char" rather
# than "concrete noun": matching characters cannot resolve word sense.
CONCRETE_CHARS = frozenset(
    "日月山水风雨雪云天地海河江川湖溪泉林树木花草叶根石土沙泥火灯窗门墙屋房船车马牛羊鸟鱼虫"
    "手眼耳鼻口舌唇齿肩背腰膝足身心衣鞋帽碗杯盘刀剑锤钉绳线布纸张笔书琴鼓钟桥街路巷场院田麦稻谷米豆菜果"
)

NUMERIC_FEATURES = (
    "line_count", "stanza_count", "mean_line_length", "median_line_length",
    "line_length_cv", "short_line_rate", "long_line_rate",
    "line_end_punct_rate", "line_end_comma_rate", "unpunctuated_break_rate",
    "line_start_function_rate", "line_end_function_rate",
    "char_ttr", "hapax_ratio", "repetition_ratio",
    "function_char_ratio", "pronoun_per_100", "abstract_per_100",
    "generic_per_100", "connective_per_100", "question_rate", "exclaim_rate",
    "imperative_rate", "copula_per_100", "simile_per_100",
    "punct_per_100", "comma_per_line", "dash_ellipsis_per_100",
    "clause_mean_length", "clause_length_cv",
    "stanza_length_cv", "repeated_line_rate", "anaphora_rate",
    "stanza_return_rate", "first_last_return",
    "modifier_de_per_100", "concrete_char_per_100",
    "last_line_length", "last_line_end_punct", "summary_ending_flag",
    "simile_ending_flag",
)

FEATURE_LABELS = {
    "line_count": "行数",
    "stanza_count": "节数",
    "mean_line_length": "平均行长（汉字）",
    "median_line_length": "行长中位数",
    "line_length_cv": "行长变异系数",
    "short_line_rate": "短行率（≤4字）",
    "long_line_rate": "长行率（≥15字）",
    "line_end_punct_rate": "行末标点率",
    "line_end_comma_rate": "行末逗号/顿号率",
    "unpunctuated_break_rate": "无标点断行率",
    "line_start_function_rate": "行首虚词率",
    "line_end_function_rate": "行末虚词率",
    "char_ttr": "字种比（TTR）",
    "hapax_ratio": "仅出现一次的字占比",
    "repetition_ratio": "字重复率",
    "function_char_ratio": "虚词字占比",
    "pronoun_per_100": "代词/百字",
    "abstract_per_100": "抽象/情绪词/百字",
    "generic_per_100": "通用抒情词/百字",
    "connective_per_100": "解释性连词/百字",
    "question_rate": "问句行率",
    "exclaim_rate": "感叹句行率",
    "imperative_rate": "祈使/呼告标记行率",
    "copula_per_100": "判断词“是”/百字",
    "simile_per_100": "明喻标记/百字",
    "punct_per_100": "标点/百字",
    "comma_per_line": "每行逗号数",
    "dash_ellipsis_per_100": "破折号/省略号/百字",
    "clause_mean_length": "分句平均长度",
    "clause_length_cv": "分句长度变异系数",
    "stanza_length_cv": "节长变异系数",
    "repeated_line_rate": "重复行率",
    "anaphora_rate": "相邻行同头率",
    "stanza_return_rate": "相邻节字面回返率",
    "first_last_return": "首尾节字面回返率",
    "modifier_de_per_100": "的/地/得/百字",
    "concrete_char_per_100": "具体字面词/百字",
    "last_line_length": "末行长度",
    "last_line_end_punct": "末行有标点",
    "summary_ending_flag": "末行总结/判断标记",
    "simile_ending_flag": "末行明喻标记",
}


def is_han(char: str) -> bool:
    return char == "〇" or unicodedata.name(char, "").startswith(
        ("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-")
    )


def han_only(text: str) -> str:
    return "".join(ch for ch in text if is_han(ch))


def nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]


def stanzas(text: str) -> list[list[str]]:
    result, current = [], []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            current.append(line.strip())
        elif current:
            result.append(current)
            current = []
    if current:
        result.append(current)
    return result


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def _cv(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = statistics.mean(values)
    return _safe_div(statistics.pstdev(values), mean)


def _count_terms(text: str, terms) -> int:
    return sum(text.count(term) for term in terms)


def _char_set(text: str) -> set[str]:
    return set(han_only(text))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _clauses(text: str) -> list[str]:
    chunks = re.split(r"[\n，。！？；：、,.!?;:…—·\-]+", text)
    return [han_only(chunk) for chunk in chunks if han_only(chunk)]


def profile(text: str) -> dict:
    """Per-poem surface profile.  All rates have deterministic denominators."""
    lines = nonempty_lines(text)
    han_lines = [han_only(line) for line in lines]
    lengths = [len(line) for line in han_lines]
    han = "".join(han_lines)
    total = len(han)
    line_count = len(lines)
    stanza_rows = stanzas(text)
    stanza_lengths = [len(row) for row in stanza_rows]
    unigrams = Counter(han)
    clauses = _clauses(text)
    clause_lengths = [len(clause) for clause in clauses]

    line_end_punct = sum(1 for line in lines if line and line[-1] in LINE_END_PUNCT)
    line_end_comma = sum(1 for line in lines if line and line[-1] in COMMA)
    unpunctuated_breaks = sum(
        1 for line in lines[:-1] if line and line[-1] not in LINE_END_PUNCT
    )
    line_starts = [han_only(line)[:1] for line in han_lines if han_only(line)]
    line_ends = [han_only(line)[-1:] for line in han_lines if han_only(line)]
    question_lines = sum(1 for line in lines if "？" in line or "?" in line)
    exclaim_lines = sum(1 for line in lines if "！" in line or "!" in line)
    imperative_lines = sum(
        1 for line in lines
        if han_only(line).startswith(IMPERATIVE_START) or han_only(line).endswith(("吧", "啊", "呀", "吗", "呢"))
    )

    normalized_lines = [han_only(line) for line in lines if han_only(line)]
    repeated_lines = sum(
        1 for value, count in Counter(normalized_lines).items() if value and count > 1 for _ in range(count - 1)
    )
    anaphora = sum(
        1 for left, right in zip(normalized_lines, normalized_lines[1:])
        if len(left) >= 2 and len(right) >= 2 and left[:2] == right[:2]
    )
    stanza_returns = [
        _jaccard(_char_set("\n".join(left)), _char_set("\n".join(right)))
        for left, right in zip(stanza_rows, stanza_rows[1:])
    ]
    first_last = _jaccard(_char_set("\n".join(stanza_rows[0])), _char_set("\n".join(stanza_rows[-1]))) if len(stanza_rows) > 1 else 0.0

    last_line = lines[-1] if lines else ""
    last_han = han_only(last_line)
    summary_ending = int(
        len(last_han) >= 4
        and any(marker in last_line for marker in SUMMARY_MARKERS)
        and not last_line[-1:] in {"？", "?"}
    )
    simile_ending = int(any(marker in last_line for marker in SIMILE_MARKERS))

    return {
        "line_count": line_count,
        "stanza_count": len(stanza_rows),
        "mean_line_length": round(statistics.mean(lengths), 6) if lengths else 0.0,
        "median_line_length": round(statistics.median(lengths), 6) if lengths else 0.0,
        "line_length_cv": round(_cv(lengths), 6),
        "short_line_rate": round(_safe_div(sum(1 for n in lengths if n <= 4), line_count), 6),
        "long_line_rate": round(_safe_div(sum(1 for n in lengths if n >= 15), line_count), 6),
        "line_end_punct_rate": round(_safe_div(line_end_punct, line_count), 6),
        "line_end_comma_rate": round(_safe_div(line_end_comma, line_count), 6),
        "unpunctuated_break_rate": round(_safe_div(unpunctuated_breaks, max(1, line_count - 1)), 6),
        "line_start_function_rate": round(_safe_div(sum(1 for c in line_starts if c in FUNCTION_CHARS), line_count), 6),
        "line_end_function_rate": round(_safe_div(sum(1 for c in line_ends if c in FUNCTION_CHARS), line_count), 6),
        "char_ttr": round(_safe_div(len(unigrams), total), 6),
        "hapax_ratio": round(_safe_div(sum(1 for v in unigrams.values() if v == 1), len(unigrams)), 6),
        "repetition_ratio": round(1 - _safe_div(len(unigrams), total), 6) if total else 0.0,
        "function_char_ratio": round(_safe_div(sum(1 for c in han if c in FUNCTION_CHARS), total), 6),
        "pronoun_per_100": round(_safe_div(_count_terms(han, PRONOUNS), total) * 100, 6),
        "abstract_per_100": round(_safe_div(_count_terms(han, ABSTRACT_WORDS), total) * 100, 6),
        "generic_per_100": round(_safe_div(_count_terms(han, GENERIC_WORDS), total) * 100, 6),
        "connective_per_100": round(_safe_div(_count_terms(han, CONNECTIVES), total) * 100, 6),
        "question_rate": round(_safe_div(question_lines, line_count), 6),
        "exclaim_rate": round(_safe_div(exclaim_lines, line_count), 6),
        "imperative_rate": round(_safe_div(imperative_lines, line_count), 6),
        "copula_per_100": round(_safe_div(han.count("是"), total) * 100, 6),
        "simile_per_100": round(_safe_div(_count_terms(han, SIMILE_MARKERS), total) * 100, 6),
        "punct_per_100": round(_safe_div(sum(1 for c in text if c in PUNCT or unicodedata.category(c).startswith("P")), total) * 100, 6),
        "comma_per_line": round(_safe_div(sum(1 for c in text if c in COMMA), line_count), 6),
        "dash_ellipsis_per_100": round(_safe_div(sum(1 for c in text if c in DASH_ELLIPSIS), total) * 100, 6),
        "clause_mean_length": round(statistics.mean(clause_lengths), 6) if clause_lengths else 0.0,
        "clause_length_cv": round(_cv(clause_lengths), 6),
        "stanza_length_cv": round(_cv(stanza_lengths), 6),
        "repeated_line_rate": round(_safe_div(repeated_lines, line_count), 6),
        "anaphora_rate": round(_safe_div(anaphora, max(1, line_count - 1)), 6),
        "stanza_return_rate": round(statistics.mean(stanza_returns), 6) if stanza_returns else 0.0,
        "first_last_return": round(first_last, 6),
        "modifier_de_per_100": round(_safe_div(han.count("的") + han.count("地") + han.count("得"), total) * 100, 6),
        "concrete_char_per_100": round(_safe_div(sum(1 for c in han if c in CONCRETE_CHARS), total) * 100, 6),
        "last_line_length": len(last_han),
        "last_line_end_punct": int(bool(last_line) and last_line[-1] in LINE_END_PUNCT),
        "summary_ending_flag": summary_ending,
        "simile_ending_flag": simile_ending,
    }


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 6) if values else 0.0,
        "median": round(statistics.median(values), 6) if values else 0.0,
        "p10": round(_percentile(values, 0.10), 6),
        "p25": round(_percentile(values, 0.25), 6),
        "p75": round(_percentile(values, 0.75), 6),
        "p90": round(_percentile(values, 0.90), 6),
        "min": round(min(values), 6) if values else 0.0,
        "max": round(max(values), 6) if values else 0.0,
        "sd": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
    }


def corpus_profile(texts: list[str], *, ids: list[str] | None = None) -> dict:
    """Aggregate a corpus while keeping the full per-feature value lists."""
    if not texts:
        raise ValueError("corpus_profile 需要至少一篇文本")
    rows = [profile(text) for text in texts]
    values = {feature: [row[feature] for row in rows] for feature in NUMERIC_FEATURES}
    return {
        "feature_schema": VERSION,
        "n": len(rows),
        "ids": ids,
        "summary": {feature: _summary(values[feature]) for feature in NUMERIC_FEATURES},
        "values": values,
    }


def _empirical_percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.5
    below = sum(1 for x in values if x < value)
    equal = sum(1 for x in values if x == value)
    return (below + 0.5 * equal) / len(values)


def _robust_z(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    median = statistics.median(values)
    iqr = _percentile(values, 0.75) - _percentile(values, 0.25)
    scale = iqr / 1.349 if iqr > 1e-9 else (statistics.pstdev(values) or 1.0)
    return (value - median) / scale


def anti_slop_flags(text: str, p: dict | None = None, reference: dict | None = None) -> list[dict]:
    """Observable prose/generic-LLM diagnostics.  Not a literary verdict."""
    p = p or profile(text)
    summary = (reference or {}).get("summary", {})

    def above(feature: str, factor: float = 1.5, absolute: float | None = None) -> bool:
        value = p[feature]
        if absolute is not None and value >= absolute:
            return True
        if feature in summary:
            p90 = summary[feature]["p90"]
            if p90 > 0:
                return value > p90 * factor
        return False

    flags = []

    def add(code, label, severity, detail):
        flags.append({"code": code, "label": label, "severity": severity, "detail": detail})

    if p["line_count"] >= 6 and p["line_end_punct_rate"] >= 0.8:
        add("all_lines_punctuated", "每行几乎都以标点收尾，分行接近排版而非节奏",
            "warn", f"行末标点率 {p['line_end_punct_rate']:.0%}")
    if p["line_count"] >= 6 and p["line_length_cv"] <= 0.18 and p["mean_line_length"] >= 8:
        add("uniform_line_length", "行长过于均匀，缺少长短呼吸", "warn",
            f"行长中位数 {p['median_line_length']:.1f}，变异系数 {p['line_length_cv']:.2f}")
    if p["mean_line_length"] >= 14 and p["line_end_punct_rate"] >= 0.7:
        add("prose_like", "长行多且句末闭合，接近分行散文", "warn",
            f"平均行长 {p['mean_line_length']:.1f}，行末标点率 {p['line_end_punct_rate']:.0%}")
    if above("connective_per_100", factor=1.5, absolute=1.0):
        add("connective_overuse", "解释性连词偏多，诗在替读者说明关系", "warn",
            f"{p['connective_per_100']:.2f}/百字")
    if above("abstract_per_100", factor=1.5, absolute=2.0):
        add("abstract_overuse", "抽象/情绪词密度偏高，缺少具体物象支撑", "warn",
            f"{p['abstract_per_100']:.2f}/百字")
    if above("generic_per_100", factor=1.5, absolute=1.0):
        add("generic_lyricism", "通用抒情词偏多，容易像可替换任何题目的句子", "info",
            f"{p['generic_per_100']:.2f}/百字")
    if p["simile_per_100"] >= 2.0:
        add("simile_overuse", "明喻标记偏多，比喻可能在替关系下结论", "info",
            f"{p['simile_per_100']:.2f}/百字")
    if p["summary_ending_flag"]:
        add("sententious_ending", "末行像总结/格言，而不是停在一个动作或物象上", "warn",
            "末行含判断或抽象收束词")
    if p["simile_ending_flag"]:
        add("simile_ending", "末行以明喻补足意义，可能是漂亮但封闭的收尾", "info",
            "末行含明喻标记")
    if p["dash_ellipsis_per_100"] >= 1.0:
        add("dash_overuse", "破折号/省略号偏多，停顿可能由符号代替", "info",
            f"{p['dash_ellipsis_per_100']:.2f}/百字")
    if p["repeated_line_rate"] >= 0.3:
        add("repetition_overuse", "重复行比例偏高，回环可能变成机械重复", "info",
            f"重复行率 {p['repeated_line_rate']:.0%}")
    if p["question_rate"] >= 0.35:
        add("question_overuse", "问句行比例偏高，追问可能代替陈述", "info",
            f"问句行率 {p['question_rate']:.0%}")
    return flags


def compare(text: str, reference: dict) -> dict:
    """Place one text inside a corpus profile.  No composite quality score."""
    p = profile(text)
    features = {}
    for feature in NUMERIC_FEATURES:
        values = reference.get("values", {}).get(feature, [])
        value = p[feature]
        features[feature] = {
            "value": value,
            "percentile": round(_empirical_percentile(values, value), 6),
            "robust_z": round(_robust_z(values, value), 6),
            "band": [reference["summary"][feature]["p10"], reference["summary"][feature]["p90"]]
            if feature in reference.get("summary", {}) else [0.0, 0.0],
            "in_band": bool(
                feature in reference.get("summary", {})
                and reference["summary"][feature]["p10"] <= value <= reference["summary"][feature]["p90"]
            ),
        }
    in_band_rate = sum(1 for row in features.values() if row["in_band"]) / len(features) if features else 0.0
    delta = statistics.mean(abs(row["robust_z"]) for row in features.values()) if features else 0.0
    return {
        "feature_schema": VERSION,
        "profile": p,
        "features": features,
        "in_band_rate": round(in_band_rate, 6),
        "mean_abs_robust_z": round(delta, 6),
        "flags": anti_slop_flags(text, p, reference),
        "note": "in_band_rate 与 mean_abs_robust_z 只表示与该语料表面分布的接近程度，不是文学质量分。",
    }


def _ngram_counts(texts: list[str], n: int) -> Counter:
    counts = Counter()
    for text in texts:
        body = han_only(text)
        for i in range(max(0, len(body) - n + 1)):
            counts[body[i:i + n]] += 1
    return counts


def distinctive_terms(
    target_texts: list[str],
    baseline_texts: list[str],
    *,
    n: int = 2,
    top: int = 30,
    alpha: float = 0.5,
    min_count: int = 3,
) -> dict:
    """Log-odds with an informative Dirichlet prior (Monroe et al. style).

    Intended for descriptive lexical fields, not as a style score.  Character
    bigrams are used because the project does not ship a segmenter.
    """
    target = _ngram_counts(target_texts, n)
    baseline = _ngram_counts(baseline_texts, n)
    vocab = set(target) | set(baseline)
    target_total = sum(target.values())
    baseline_total = sum(baseline.values())
    if not vocab or not target_total or not baseline_total:
        return {"n": n, "positive": [], "negative": []}
    size = len(vocab)
    rows = []
    for term in vocab:
        a, b = target[term], baseline[term]
        if a < min_count:
            continue
        p_t = (a + alpha) / (target_total + alpha * size)
        p_b = (b + alpha) / (baseline_total + alpha * size)
        diff = math.log(p_t) - math.log(p_b)
        variance = 1 / (a + alpha) + 1 / (b + alpha)
        z = diff / math.sqrt(variance)
        rows.append({"term": term, "target_count": a, "baseline_count": b, "log_odds_z": round(z, 4)})
    rows.sort(key=lambda row: row["log_odds_z"], reverse=True)
    positive = rows[:top]
    negative = sorted(rows, key=lambda row: row["log_odds_z"])[:top]
    return {"n": n, "positive": positive, "negative": negative}
