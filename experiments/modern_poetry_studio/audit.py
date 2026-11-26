"""Offline audit: can our surface metrics separate human poetry from model poems?

This script never calls an API.  It answers three questions before any prompt
engineering is allowed:

1. Which features are stable inside a poet's short-poem corpus?
2. Which features separate the three poets from one another?
3. Which features separate human poems from the model poems already in ``runs/``
   and the RPE live run?

The output is a diagnostic report, not a quality ranking.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from poetry_agent.style.corpus import load_corpus
from poetry_agent.style.stylometry import (
    FEATURE_LABELS,
    NUMERIC_FEATURES,
    corpus_profile,
    distinctive_terms,
    profile,
)

ROOT = Path(__file__).resolve().parents[2]

POETS = {
    "haizi": {"name": "海子", "path": "var/haizi/corpus.jsonl"},
    "beidao": {"name": "北岛", "path": "var/beidao/corpus.jsonl"},
    "shuting": {"name": "舒婷", "path": "var/shuting/corpus.jsonl"},
}

EXCLUDE_FLAGS = ("is_fragment", "is_duplicate", "misattributed", "is_translation")
MIN_LINES = 6
MAX_LINES = 60


def _text_hash(text: str) -> str:
    body = re.sub(r"[^\u3400-\u9fff]", "", text)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _eligible(row: dict, names: tuple[str, ...]) -> bool:
    metadata = row.get("metadata") or {}
    if any(metadata.get(flag) for flag in EXCLUDE_FLAGS):
        return False
    if any(name in row.get("text", "") for name in names):
        return False
    count = len([line for line in row.get("text", "").splitlines() if line.strip()])
    return MIN_LINES <= count <= MAX_LINES


def load_poet_poems(poet_key: str, split: str) -> list[dict]:
    meta = POETS[poet_key]
    rows, _ = load_corpus(ROOT / meta["path"])
    names = (meta["name"],)
    result = []
    for row in rows:
        if row.get("split") != split:
            continue
        if not _eligible(row, names):
            continue
        result.append({
            "poet": poet_key,
            "poet_name": meta["name"],
            "poem_id": row["poem_id"],
            "title": row.get("title") or "",
            "text": row["text"],
            "split": split,
        })
    return result


def load_existing_model_poems() -> list[dict]:
    """Collect real (non-mock) modern-poem outputs already present in the repo."""
    result = []
    seen = set()
    for path in sorted((ROOT / "runs").rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        task = data.get("task")
        poem = data.get("poem")
        if not isinstance(task, dict) or task.get("genre") != "modern":
            continue
        if data.get("mode") == "mock" or not isinstance(poem, dict):
            continue
        lines = poem.get("lines")
        if not isinstance(lines, list) or not lines:
            continue
        text = "\n".join(str(line) for line in lines)
        body_hash = _text_hash(text)
        if body_hash in seen:
            continue
        seen.add(body_hash)
        result.append({
            "source": str(path.relative_to(ROOT)),
            "title": poem.get("title") or "",
            "text": text,
            "origin": "repo_runs",
        })

    for path in sorted((ROOT / "experiments/reverse_prompt_engineering/runs").glob("*/evaluations/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        for evaluation in data.get("evaluations", []):
            generation = evaluation.get("generation") or {}
            if not generation.get("ok") or generation.get("mock"):
                continue
            text = generation.get("text") or "\n".join(generation.get("lines") or [])
            if not text.strip():
                continue
            body_hash = _text_hash(text)
            if body_hash in seen:
                continue
            seen.add(body_hash)
            result.append({
                "source": str(path.relative_to(ROOT)),
                "title": generation.get("title") or "",
                "text": text,
                "origin": "rpe_live",
            })
    return result


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[order[k]] = rank
        i = j
    return ranks


def auc(pos: list[float], neg: list[float]) -> float:
    """P(random positive > random negative), ties count 0.5."""
    if not pos or not neg:
        return 0.5
    values = list(pos) + list(neg)
    ranks = _ranks(values)
    n1, n2 = len(pos), len(neg)
    rank_sum = sum(ranks[:n1])
    u1 = rank_sum - n1 * (n1 + 1) / 2.0
    return u1 / (n1 * n2)


def _separation(a: float) -> float:
    return max(a, 1.0 - a)


def _within_relative_iqr(summary: dict) -> float:
    median = summary["median"]
    if abs(median) < 1e-9:
        return 0.0 if summary["p75"] == summary["p25"] else 1.0
    return (summary["p75"] - summary["p25"]) / abs(median)


def _feature_analysis(poet_profiles: dict[str, dict], model_profile: dict) -> list[dict]:
    rows = []
    for feature in NUMERIC_FEATURES:
        per_poet = {key: poet_profiles[key]["values"][feature] for key in poet_profiles}
        within = [
            _within_relative_iqr(poet_profiles[key]["summary"][feature])
            for key in poet_profiles
        ]
        human_values = [value for values in per_poet.values() for value in values]
        model_values = model_profile["values"][feature]
        hm_auc = auc(human_values, model_values)
        pairs = []
        keys = list(per_poet)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                pair_auc = auc(per_poet[keys[i]], per_poet[keys[j]])
                pairs.append((keys[i], keys[j], pair_auc))
        best_pair = max(pairs, key=lambda item: _separation(item[2])) if pairs else ("", "", 0.5)
        rows.append({
            "feature": feature,
            "label": FEATURE_LABELS.get(feature, feature),
            "human_values": human_values,
            "model_values": model_values,
            "human_model_auc": round(hm_auc, 6),
            "human_model_separation": round(_separation(hm_auc), 6),
            "poet_best_pair": list(best_pair[:2]),
            "poet_best_auc": round(best_pair[2], 6),
            "poet_separation": round(_separation(best_pair[2]), 6),
            "within_relative_iqr": round(statistics.mean(within), 6),
        })
    return rows


def _summarize_feature(feature_row: dict) -> dict:
    return {
        "feature": feature_row["feature"],
        "label": feature_row["label"],
        "human_model_auc": feature_row["human_model_auc"],
        "human_model_separation": feature_row["human_model_separation"],
        "poet_best_pair": feature_row["poet_best_pair"],
        "poet_best_auc": feature_row["poet_best_auc"],
        "poet_separation": feature_row["poet_separation"],
        "within_relative_iqr": feature_row["within_relative_iqr"],
    }


def build_audit() -> dict:
    train = {key: load_poet_poems(key, "train") for key in POETS}
    held = {key: load_poet_poems(key, "held_out") for key in POETS}
    model_poems = load_existing_model_poems()

    poet_profiles = {
        key: corpus_profile([poem["text"] for poem in train[key]], ids=[poem["poem_id"] for poem in train[key]])
        for key in POETS
    }
    all_train_texts = [poem["text"] for key in POETS for poem in train[key]]
    human_profile = corpus_profile(all_train_texts)
    model_profile = corpus_profile([poem["text"] for poem in model_poems])

    feature_rows = _feature_analysis(poet_profiles, model_profile)
    ranked_hm = sorted(feature_rows, key=lambda row: row["human_model_separation"], reverse=True)
    ranked_poet = sorted(feature_rows, key=lambda row: row["poet_separation"], reverse=True)

    distinctive = {}
    for key in POETS:
        others = [poem["text"] for other in POETS if other != key for poem in train[other]]
        distinctive[key] = distinctive_terms(
            [poem["text"] for poem in train[key]], others, n=2, top=25
        )

    counts = {
        "train": {key: len(train[key]) for key in POETS},
        "held_out": {key: len(held[key]) for key in POETS},
        "model": len(model_poems),
    }

    samples = {
        "human": [
            {"poet": poem["poet"], "title": poem["title"], "text": poem["text"]}
            for key in POETS for poem in train[key][:2]
        ],
        "model": [
            {"source": poem["source"], "title": poem["title"], "text": poem["text"]}
            for poem in model_poems[:8]
        ],
    }

    return {
        "schema_version": "modern-poetry-audit-v1",
        "counts": counts,
        "profiles": {key: {"n": poet_profiles[key]["n"], "summary": poet_profiles[key]["summary"]} for key in POETS},
        "human_profile": {"n": human_profile["n"], "summary": human_profile["summary"]},
        "model_profile": {"n": model_profile["n"], "summary": model_profile["summary"]},
        "feature_analysis": [_summarize_feature(row) for row in feature_rows],
        "top_human_model": [_summarize_feature(row) for row in ranked_hm[:15]],
        "top_poet": [_summarize_feature(row) for row in ranked_poet[:15]],
        "distinctive_bigrams": distinctive,
        "samples": samples,
        "notes": [
            "AUC=0.5 表示该特征在两组间没有区分；1.0 表示完全分离。",
            "separation=max(AUC,1-AUC)，仅作诊断，不是文学质量分。",
            "within_relative_iqr 越低，说明该特征在诗人内部越稳定。",
            "模型稿来自仓库既有真实运行与 RPE live 生成，题材与人类语料不同，差异可能含题材混杂。",
        ],
    }


def _fmt(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.3f}"


def write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# 现代诗表面指标离线审计",
        "",
        "本报告只检查可观察的表面分布，不给出文学质量分。模型稿与人类语料的题材不同，AUC 差异可能混入题材因素。",
        "",
        "## 语料",
        "",
        "| 来源 | 篇数 |",
        "|---|---:|",
    ]
    for key, count in report["counts"]["train"].items():
        lines.append(f"| {POETS[key]['name']} 训练短诗 | {count} |")
    for key, count in report["counts"]["held_out"].items():
        lines.append(f"| {POETS[key]['name']} 留出短诗 | {count} |")
    lines.append(f"| 既有真实模型稿 | {report['counts']['model']} |")
    lines += [
        "",
        "## 最能区分“人类诗 / 模型稿”的特征",
        "",
        "| 特征 | AUC | 方向 | 诗人内部相对 IQR |",
        "|---|---:|---|---:|",
    ]
    for row in report["top_human_model"]:
        direction = "人类更高" if row["human_model_auc"] > 0.5 else "模型更高"
        lines.append(
            f"| {row['label']} | {row['human_model_auc']:.3f} | {direction} | {row['within_relative_iqr']:.2f} |"
        )
    lines += [
        "",
        "## 最能区分三位诗人的特征",
        "",
        "| 特征 | 最佳诗对 | AUC | 诗人内部相对 IQR |",
        "|---|---|---:|---:|",
    ]
    for row in report["top_poet"]:
        pair = " / ".join(POETS[key]["name"] for key in row["poet_best_pair"])
        lines.append(
            f"| {row['label']} | {pair} | {row['poet_best_auc']:.3f} | {row['within_relative_iqr']:.2f} |"
        )

    lines += ["", "## 三位诗人的分布中位数（训练短诗）", ""]
    for key in POETS:
        summary = report["profiles"][key]["summary"]
        lines += [f"### {POETS[key]['name']}", "", "| 特征 | 中位数 | p10—p90 |", "|---|---:|---|"]
        for feature in (
            "line_count", "stanza_count", "median_line_length", "line_length_cv",
            "short_line_rate", "line_end_punct_rate", "unpunctuated_break_rate",
            "abstract_per_100", "connective_per_100", "simile_per_100",
            "stanza_return_rate", "summary_ending_flag",
        ):
            item = summary[feature]
            lines.append(f"| {FEATURE_LABELS[feature]} | {_fmt(item['median'])} | {_fmt(item['p10'])}—{_fmt(item['p90'])} |")
        lines.append("")

    lines += ["## 区分性字词片段（字符 bigram，log-odds）", ""]
    for key, result in report["distinctive_bigrams"].items():
        terms = "、".join(row["term"] for row in result["positive"][:15])
        lines.append(f"- **{POETS[key]['name']}**：{terms}")
    lines += [
        "",
        "## 读法提醒",
        "",
        "- 这些指标只能说明“表面习惯接近/偏离”，不能说明诗的好坏。",
        "- 如果某特征在诗人内部波动很大，就不应写进固定提示词。",
        "- 如果某特征主要区分题材而非诗人，也不应作为风格指纹。",
        "- 下一步才用通过审计的特征编译提示词；未通过审计的指标不进入生成流程。",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="离线审计现代诗表面指标")
    parser.add_argument("--output", type=Path, default=ROOT / "var/modern_poetry_studio/audit-01")
    args = parser.parse_args()
    report = build_audit()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(report, args.output / "audit.md")
    print(f"篇数：{report['counts']}")
    print(f"报告：{args.output / 'audit.md'}")
    print("Top human/model separation:")
    for row in report["top_human_model"][:10]:
        print(f"  {row['label']}: AUC={row['human_model_auc']:.3f}, within={row['within_relative_iqr']:.2f}")
    print("Top poet separation:")
    for row in report["top_poet"][:10]:
        print(f"  {row['label']}: {row['poet_best_pair']} AUC={row['poet_best_auc']:.3f}")


if __name__ == "__main__":
    main()
