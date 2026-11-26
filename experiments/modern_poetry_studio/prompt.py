"""Compile an inspectable style prompt from a corpus profile.

Only theory-supported, actionable features are written into the prompt.  The
compiler does not use character-bigram overlap as a target, and it does not
force the model to reproduce a poet's signature nouns.  The output records every
number it used so a later report can say which distribution produced the prompt.
"""
from __future__ import annotations

import json
from pathlib import Path

from poetry_agent.style.stylometry import FEATURE_LABELS, corpus_profile

VERSION = "modern-prompt-v1"


def _pct(value: float, digits: int = 0) -> str:
    return f"{value * 100:.{digits}f}%"


def _num(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def _range(summary: dict, feature: str, *, percent: bool = False, digits: int = 1) -> str:
    item = summary[feature]
    if percent:
        return f"{_pct(item['p10'], digits)}—{_pct(item['p90'], digits)}"
    return f"{_num(item['p10'], digits)}—{_num(item['p90'], digits)}"


def _lineation_block(summary: dict, max_lines: int | None) -> str:
    line_low, line_high = summary["line_count"]["p10"], summary["line_count"]["p90"]
    if max_lines:
        line_low = min(line_low, max_lines)
        line_high = min(line_high, max_lines)
        line_text = f"硬性上限：正文不得超过 {max_lines} 行；分行节奏参考：约 {int(line_low)}—{int(line_high)} 行，"
    else:
        line_text = f"分行节奏参考：约 {int(line_low)}—{int(line_high)} 行，"
    return (
        line_text
        + f"行长中位数约 {_num(summary['median_line_length']['p10'])}—{_num(summary['median_line_length']['p90'])} 字，"
        + f"短行（≤4字）约 {_pct(summary['short_line_rate']['p10'])}—{_pct(summary['short_line_rate']['p90'])}。"
        + f"行末标点应少：大多数行在无标点处断开（参考 {_pct(summary['unpunctuated_break_rate']['p10'])}—{_pct(summary['unpunctuated_break_rate']['p90'])}），"
        + "不要每行都写成闭合的完整句。行长要有明显长短差，不要每行差不多长。"
    )


def _language_block(summary: dict) -> str:
    return (
        "每行先有一个可感知的动作、物件、位置或声音，再让意义从它们的关系里出现。"
        "具体物象不要堆成清单：物象要在动作或位置中发生变化。"
        "抽象词、情绪词和直接判断不是禁品，但必须有前文的动作或物件支撑，不能用来填空。"
        f"少用解释性连词（因为、所以、于是、然而、但是、因此）；参考上限约 {_num(summary['connective_per_100']['p90'])}/百字。"
        "明喻不要密集，不要用“像……”给每一节补一个漂亮结论。"
    )


def _repetition_block(summary: dict) -> str:
    return (
        "可以重复一个短语、句式或动作，但每次回返要改变位置、对象、语气或句法功能；"
        "不要原样机械重复，也不要把重复当作唯一的结构。"
    )


def _ending_block(summary: dict) -> str:
    return (
        "结尾可以直说、可以停在动作或物件上，也可以保留未解决的问题；"
        "但末行必须承接前文已经建立的关系，不要为了收束补一句可替换的格言，"
        "也不要用一个明喻把全诗封闭起来。"
    )


def _anti_slop_block() -> str:
    return (
        "避免以下明显的“分行散文/通用 AI 诗”习惯："
        "每行都以逗号或句号收尾；行长过于均匀；用“因为/所以/然而”解释关系；"
        "堆叠抽象大词；连续使用破折号或省略号制造停顿；"
        "每节末尾都用“像……”作漂亮比喻；末行突然升华或总结。"
    )


def _baseline_prompt(max_lines: int | None) -> str:
    limit = f"，不超过 {max_lines} 行" if max_lines else ""
    return (
        f"写一首现代诗{limit}。题目由用户给出。"
        "要求语言自然、意象具体、分行有节奏；不要出现任何诗人姓名，不要复刻参考作品原句。"
    )


def compile_style_prompt(
    profile: dict,
    *,
    variant: str = "style_card",
    max_lines: int | None = None,
    poet_name: str | None = None,
) -> dict:
    """Return a prompt plus the exact feature ranges used to compile it."""
    if variant not in ("baseline", "style_card", "style_card_anti_slop"):
        raise ValueError("variant 须为 baseline、style_card 或 style_card_anti_slop")
    summary = profile["summary"]
    if variant == "baseline":
        text = _baseline_prompt(max_lines)
    else:
        blocks = [
            "写一首现代诗，不是分行散文。让换行承担停顿、悬置和强调，而不是把一段话切成几行。",
            "【分行】" + _lineation_block(summary, max_lines),
            "【语言】" + _language_block(summary),
            "【重复】" + _repetition_block(summary),
            "【结尾】" + _ending_block(summary),
        ]
        if variant == "style_card_anti_slop":
            blocks.append("【反模式】" + _anti_slop_block())
        blocks.append("不要出现任何诗人姓名，不要复刻参考作品的成句或长片段。")
        text = "\n".join(blocks)

    used = {
        feature: {
            "label": FEATURE_LABELS.get(feature, feature),
            "p10": summary[feature]["p10"],
            "median": summary[feature]["median"],
            "p90": summary[feature]["p90"],
        }
        for feature in (
            "line_count", "median_line_length", "short_line_rate",
            "line_end_punct_rate", "unpunctuated_break_rate",
            "line_length_cv", "connective_per_100", "simile_per_100",
            "dash_ellipsis_per_100", "abstract_per_100",
        )
        if feature in summary
    }
    return {
        "schema_version": VERSION,
        "variant": variant,
        "poet_name": poet_name,
        "max_lines": max_lines,
        "prompt": text,
        "char_count": len(text),
        "feature_ranges": used,
        "source_profile_n": profile.get("n"),
        "notes": [
            "数字来自训练语料的 p10—p90，不是硬性审美标准。",
            "没有把诗人姓名、原句或标志性名词写进提示词。",
            "抽象词和直接判断未被禁用；文学判断仍需人读。",
        ],
    }


def main() -> None:
    import argparse

    from experiments.modern_poetry_studio.audit import POETS, load_poet_poems

    parser = argparse.ArgumentParser(description="从语料 profile 编译现代诗提示词")
    parser.add_argument("--poet", choices=sorted(POETS), help="只用某位诗人的训练短诗；省略则合并三位")
    parser.add_argument("--variant", choices=("baseline", "style_card", "style_card_anti_slop"), default="style_card")
    parser.add_argument("--max-lines", type=int)
    parser.add_argument("--output", type=Path, default=Path("var/modern_poetry_studio/prompt-01.json"))
    args = parser.parse_args()
    if args.poet:
        poems = load_poet_poems(args.poet, "train")
        poet_name = POETS[args.poet]["name"]
    else:
        poems = [p for key in POETS for p in load_poet_poems(key, "train")]
        poet_name = None
    profile = corpus_profile([p["text"] for p in poems])
    record = compile_style_prompt(profile, variant=args.variant, max_lines=args.max_lines, poet_name=poet_name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(record["prompt"])
    print(f"\n提示词长度：{record['char_count']} 字；保存到 {args.output}")


if __name__ == "__main__":
    main()
