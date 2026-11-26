"""Build an anonymized pairwise review packet from generation runs.

The review packet contains only the poem bodies and A/B labels.  Titles,
prompt variants, run ids and model names live in ``mapping.json`` so the
reviewer can read without knowing which method produced which text.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_run(run_dir: Path) -> dict:
    return json.loads((run_dir / "generations.json").read_text(encoding="utf-8"))


def _pick_by_topic(records: list[dict]) -> dict[str, dict]:
    chosen = {}
    for record in records:
        if not record.get("ok") or not record.get("text"):
            continue
        topic_id = record.get("topic_id")
        if topic_id and topic_id not in chosen:
            chosen[topic_id] = record
    return chosen


def _body(record: dict) -> str:
    stanzas = record.get("stanzas")
    if isinstance(stanzas, list) and stanzas:
        rows = []
        for stanza in stanzas:
            if isinstance(stanza, list):
                rows.append("\n".join(str(line) for line in stanza if str(line).strip()))
            elif isinstance(stanza, str) and stanza.strip():
                rows.append(stanza.strip())
        body = "\n\n".join(row for row in rows if row)
        if body:
            return body
    return record.get("text", "")


def build_packet(
    baseline_runs: list[Path],
    style_runs: list[Path],
    *,
    seed: int = 20261126,
) -> dict:
    baseline = {}
    for run_dir in baseline_runs:
        for topic_id, record in _pick_by_topic(_load_run(run_dir)["records"]).items():
            baseline.setdefault(topic_id, {"record": record, "run": str(run_dir)})
    style = {}
    for run_dir in style_runs:
        for topic_id, record in _pick_by_topic(_load_run(run_dir)["records"]).items():
            style.setdefault(topic_id, {"record": record, "run": str(run_dir)})

    shared = sorted(set(baseline) & set(style))
    if not shared:
        raise ValueError("baseline 与 style 运行没有共同题目")

    rng = random.Random(seed)
    pairs = []
    order = shared[:]
    rng.shuffle(order)
    for index, topic_id in enumerate(order, 1):
        left = baseline[topic_id]
        right = style[topic_id]
        if rng.random() < 0.5:
            a, b = left, right
        else:
            a, b = right, left
        pairs.append({
            "pair_id": f"p{index:02d}",
            "topic_id": topic_id,
            "topic": left["record"].get("topic"),
            "a": {
                "text": _body(a["record"]),
                "source": "baseline",
                "run": a["run"],
                "title": a["record"].get("title"),
            },
            "b": {
                "text": _body(b["record"]),
                "source": "style_card_anti_slop",
                "run": b["run"],
                "title": b["record"].get("title"),
            },
        })
    return {
        "schema_version": "modern-blind-v1",
        "created_at": _now(),
        "seed": seed,
        "instructions": "只读正文；不要根据标题、长度或方法猜测。允许平局与无法判断。",
        "pairs": pairs,
    }


def _review_markdown(packet: dict) -> str:
    lines = [
        "# 现代诗匿名盲评：基线 vs 风格卡",
        "",
        "本表只显示正文，隐藏标题、生成方法与运行编号。请先完整读两首，再作答。",
        "",
        "**判断问题：**",
        "",
        "1. 哪一首整体更像一首诗？",
        "2. 哪一首的换行更必要：合并成散文后会失去更多？",
        "3. 哪一首的意象更在动作、位置或时间里发生关系，而不是并列展示？",
        "4. 哪一首的结尾更承接前文，而不是补一句可替换的话？",
        "",
        "允许选“平局”或“无法判断”。理由必须引用具体行；不要只写“更有诗意”。",
        "",
        "---",
        "",
    ]
    for pair in packet["pairs"]:
        lines += [
            f"## {pair['pair_id']}",
            "",
            f"题目：{pair['topic']}",
            "",
            "### 作品 A",
            "",
            pair["a"]["text"],
            "",
            "### 作品 B",
            "",
            pair["b"]["text"],
            "",
            "### 作答",
            "",
            "- 1. 更像一首诗：A / B / 平局 / 无法判断",
            "- 2. 换行更必要：A / B / 平局 / 无法判断",
            "- 3. 意象关系更成立：A / B / 平局 / 无法判断",
            "- 4. 结尾更承接：A / B / 平局 / 无法判断",
            "- 5. 更愿意再读一遍：A / B / 平局",
            "",
            "理由（引用具体行）：",
            "",
            "",
            "---",
            "",
        ]
    lines += [
        "## 总体",
        "",
        "读完三组后，用一句话说明：哪一组差异最明显，为什么？",
        "",
        "",
    ]
    return "\n".join(lines)


def _response_template(packet: dict) -> dict:
    return {
        "reviewer": "",
        "reviewed_at": "",
        "pairs": [
            {
                "pair_id": pair["pair_id"],
                "more_poetic": "",
                "lineation": "",
                "imagery": "",
                "ending": "",
                "reread": "",
                "reason": "",
                "evidence": "",
            }
            for pair in packet["pairs"]
        ],
        "overall": "",
    }


def _mapping(packet: dict) -> dict:
    return {
        "schema_version": packet["schema_version"],
        "created_at": packet["created_at"],
        "seed": packet["seed"],
        "pairs": [
            {
                "pair_id": pair["pair_id"],
                "topic_id": pair["topic_id"],
                "topic": pair["topic"],
                "a": {
                    "source": pair["a"]["source"],
                    "run": pair["a"]["run"],
                    "title": pair["a"]["title"],
                },
                "b": {
                    "source": pair["b"]["source"],
                    "run": pair["b"]["run"],
                    "title": pair["b"]["title"],
                },
            }
            for pair in packet["pairs"]
        ],
    }


def write_packet(packet: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "blind.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "review.md").write_text(_review_markdown(packet), encoding="utf-8")
    (output_dir / "response-template.json").write_text(
        json.dumps(_response_template(packet), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "mapping.json").write_text(json.dumps(_mapping(packet), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"盲评表：{output_dir / 'review.md'}")
    print(f"作答模板：{output_dir / 'response-template.json'}")
    print(f"映射（不要先看）：{output_dir / 'mapping.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成匿名配对盲评包")
    parser.add_argument("--baseline-run", type=Path, action="append", required=True)
    parser.add_argument("--style-run", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261126)
    args = parser.parse_args()
    packet = build_packet(args.baseline_run, args.style_run, seed=args.seed)
    write_packet(packet, args.output)


if __name__ == "__main__":
    main()
