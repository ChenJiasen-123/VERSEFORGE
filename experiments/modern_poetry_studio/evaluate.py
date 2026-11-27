"""Evaluate generated poems against a human-corpus band and print a reading sheet.

The report intentionally separates:
* surface placement (in-band rate, robust z),
* anti-slop flags,
* the full text for human reading.

It does not produce a single "poetry score".
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

from poetry_agent.style.stylometry import compare, corpus_profile

from experiments.modern_poetry_studio.audit import POETS, load_poet_poems

ROOT = Path(__file__).resolve().parents[2]


def target_profile(poet: str | None = None) -> dict:
    if poet:
        poems = load_poet_poems(poet, "train")
    else:
        poems = [p for key in POETS for p in load_poet_poems(key, "train")]
    return corpus_profile([p["text"] for p in poems])


def held_out_band(poet: str | None = None) -> dict:
    if poet:
        poems = load_poet_poems(poet, "held_out")
    else:
        poems = [p for key in POETS for p in load_poet_poems(key, "held_out")]
    return corpus_profile([p["text"] for p in poems])


def _aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    flags = Counter(flag["code"] for row in rows for flag in row["flags"])
    return {
        "n": len(rows),
        "in_band_mean": round(statistics.mean(row["comparison"]["in_band_rate"] for row in rows), 6),
        "in_band_median": round(statistics.median(row["comparison"]["in_band_rate"] for row in rows), 6),
        "delta_mean": round(statistics.mean(row["comparison"]["mean_abs_robust_z"] for row in rows), 6),
        "delta_median": round(statistics.median(row["comparison"]["mean_abs_robust_z"] for row in rows), 6),
        "flag_counts": dict(sorted(flags.items(), key=lambda item: (-item[1], item[0]))),
    }


def evaluate_records(records: list[dict], profile: dict) -> list[dict]:
    rows = []
    for record in records:
        if not record.get("ok") or not record.get("text"):
            rows.append({"record": record, "comparison": None, "flags": []})
            continue
        comparison = compare(record["text"], profile)
        rows.append({
            "record": record,
            "comparison": comparison,
            "flags": comparison["flags"],
        })
    return rows


def evaluate_run(run_dir: Path, *, poet: str | None = None) -> dict:
    data = json.loads((run_dir / "generations.json").read_text(encoding="utf-8"))
    profile = target_profile(poet)
    held = held_out_band(poet)
    rows = evaluate_records(data["records"], profile)
    held_rows = evaluate_records(
        [{"ok": True, "text": p["text"], "title": p["title"], "topic_id": p["poem_id"]}
         for p in (load_poet_poems(poet, "held_out") if poet else [p for key in POETS for p in load_poet_poems(key, "held_out")])],
        profile,
    )
    return {
        "schema_version": "modern-eval-v1",
        "run": data,
        "target_poet": poet,
        "target_n": profile["n"],
        "aggregate": _aggregate([row for row in rows if row["comparison"]]),
        "human_held_out_aggregate": _aggregate([row for row in held_rows if row["comparison"]]),
        "rows": rows,
        "limitations": [
            "in_band_rate 只表示与目标语料表面分布的接近程度，不是文学质量分。",
            "模型稿与人类语料的题材不同；差异可能来自题目而非风格。",
            "反模式 flag 是诊断，不是禁用词表；抽象词、直接陈述和总结结尾在人类诗里也存在。",
            "没有人类盲评时，不得声称“更像诗”或“质量提升”。",
        ],
    }


def _pct(value: float) -> str:
    return f"{value:.0%}"


def write_markdown(result: dict, path: Path) -> None:
    run = result["run"]
    lines = [
        "# 现代诗生成评估（表面指标 + 阅读稿）",
        "",
        f"- 运行：`{run['run_id']}`",
        f"- 模式：`{run['mode']}`；模型：`{run['model']}`",
        f"- 提示词变体：`{run.get('prompt_variant')}`；长度：{run.get('prompt_sha256', '')[:12]}",
        f"- 目标语料：{result.get('target_poet') or '三位诗人合并'}，n={result['target_n']}",
        "",
        "## 聚合",
        "",
        "| 组 | n | in-band 均值 | 平均 robust z | 主要 flags |",
        "|---|---:|---:|---:|---|",
    ]
    for label, agg in (("生成稿", result["aggregate"]), ("人类留出稿（参照）", result["human_held_out_aggregate"])):
        flags = "、".join(f"{k}×{v}" for k, v in list(agg.get("flag_counts", {}).items())[:6]) or "无"
        lines.append(f"| {label} | {agg.get('n', 0)} | {_pct(agg.get('in_band_mean', 0))} | {agg.get('delta_mean', 0):.2f} | {flags} |")
    lines += [
        "",
        "> in-band 越高只说明表面分布越接近目标语料，**不是**质量更高。人类留出稿也不是满分标准。",
        "",
        "## 逐首指标",
        "",
        "| 题目 | 标题 | 行数 | in-band | robust z | flags |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in result["rows"]:
        record = row["record"]
        comparison = row["comparison"]
        if not comparison:
            lines.append(f"| {record.get('topic_id')} | 生成失败 | 0 | — | — | {record.get('issues')} |")
            continue
        flags = "、".join(flag["code"] for flag in row["flags"]) or "—"
        lines.append(
            f"| {record.get('topic_id')} | {record.get('title')} | {comparison['profile']['line_count']} | "
            f"{_pct(comparison['in_band_rate'])} | {comparison['mean_abs_robust_z']:.2f} | {flags} |"
        )

    lines += ["", "## 阅读稿", ""]
    for index, row in enumerate(result["rows"], 1):
        record = row["record"]
        lines += [f"### {index}. {record.get('title')}（{record.get('topic_id')}）", ""]
        if record.get("text"):
            lines += [line if line.strip() else "" for line in record["text"].splitlines()]
        else:
            lines.append(f"生成失败：{record.get('issues')}")
        lines.append("")
        if row["comparison"]:
            flags = row["flags"]
            if flags:
                lines.append("表面诊断：" + "；".join(f"{f['label']}（{f['detail']}）" for f in flags))
            else:
                lines.append("表面诊断：无触发 flag。")
            lines.append("")
        lines.append("阅读问题：换行是否必要？意象是否在动作/位置中变化？说话位置是否清楚？结尾是否承接前文，还是补了一句可替换的话？")
        lines.append("")

    lines += [
        "## 局限",
        "",
        *[f"- {item}" for item in result["limitations"]],
        "",
        "本报告不是盲评，也不是优胜结论；下一步应把匿名正文交给真实读者做配对比较。",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="评估现代诗生成稿")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--poet", choices=sorted(POETS))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate_run(args.run, poet=args.poet)
    output = args.output or (args.run / "evaluation.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(result, args.run / "evaluation.md")
    print(f"聚合：{result['aggregate']}")
    print(f"人类留出：{result['human_held_out_aggregate']}")
    print(f"报告：{args.run / 'evaluation.md'}")


if __name__ == "__main__":
    main()
