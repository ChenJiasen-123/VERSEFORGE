"""Small CLI for the modern-poetry studio.

Examples
--------
python -m experiments.modern_poetry_studio.run audit
python -m experiments.modern_poetry_studio.run prompt --poet beidao --variant style_card_anti_slop
python -m experiments.modern_poetry_studio.run generate --mode mock --prompt <file>
python -m experiments.modern_poetry_studio.run evaluate --run <dir>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from poetry_agent.style.stylometry import corpus_profile

from experiments.modern_poetry_studio.audit import POETS, build_audit, load_poet_poems, write_markdown
from experiments.modern_poetry_studio.evaluate import evaluate_run, write_markdown as write_eval_markdown
from experiments.modern_poetry_studio.generate import DEFAULT_TOPICS, run_generation
from experiments.modern_poetry_studio.prompt import compile_style_prompt

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "var/modern_poetry_studio"


def _profile(poet: str | None):
    if poet:
        poems = load_poet_poems(poet, "train")
    else:
        poems = [p for key in POETS for p in load_poet_poems(key, "train")]
    return corpus_profile([p["text"] for p in poems])


def cmd_audit(args):
    output = args.output or DEFAULT_ROOT / "audit-01"
    report = build_audit()
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, output / "audit.md")
    print(f"报告：{output / 'audit.md'}")


def cmd_prompt(args):
    profile = _profile(args.poet)
    record = compile_style_prompt(
        profile,
        variant=args.variant,
        max_lines=args.max_lines,
        poet_name=POETS[args.poet]["name"] if args.poet else None,
    )
    output = args.output or DEFAULT_ROOT / f"prompt-{args.poet or 'all'}-{args.variant}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(record["prompt"])
    print(f"\n长度：{record['char_count']} 字；保存：{output}")


def cmd_generate(args):
    prompt_record = json.loads(args.prompt.read_text(encoding="utf-8"))
    result = run_generation(
        mode=args.mode,
        prompt_record=prompt_record,
        topics=DEFAULT_TOPICS,
        repetitions=args.repetitions,
        output_dir=args.output or DEFAULT_ROOT / "generations",
        authorize_spend=args.authorize_spend,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        thinking=args.thinking,
    )
    print(json.dumps({"run_id": result["run_id"], "calls": result["call_count"]}, ensure_ascii=False))


def cmd_evaluate(args):
    result = evaluate_run(args.run, poet=args.poet)
    (args.run / "evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_eval_markdown(result, args.run / "evaluation.md")
    print(f"报告：{args.run / 'evaluation.md'}")


def cmd_all_offline(args):
    output = args.output or DEFAULT_ROOT / "offline-01"
    output.mkdir(parents=True, exist_ok=True)
    report = build_audit()
    (output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, output / "audit.md")

    prompt_dir = output / "prompts"
    prompt_dir.mkdir(exist_ok=True)
    prompt_files = {}
    for poet in (None, *POETS):
        for variant in ("style_card", "style_card_anti_slop"):
            record = compile_style_prompt(
                _profile(poet),
                variant=variant,
                max_lines=18,
                poet_name=POETS[poet]["name"] if poet else None,
            )
            key = f"{poet or 'all'}-{variant}"
            path = prompt_dir / f"{key}.json"
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            prompt_files[key] = path
    print(f"审计与提示词：{output}")
    print("提示词文件：")
    for key, path in prompt_files.items():
        print(f"  {key}: {path}")


def main():
    parser = argparse.ArgumentParser(description="现代诗风格工作流")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="离线审计表面指标")
    audit.add_argument("--output", type=Path)
    audit.set_defaults(func=cmd_audit)

    prompt = sub.add_parser("prompt", help="编译风格提示词")
    prompt.add_argument("--poet", choices=sorted(POETS))
    prompt.add_argument("--variant", choices=("baseline", "style_card", "style_card_anti_slop"), default="style_card")
    prompt.add_argument("--max-lines", type=int)
    prompt.add_argument("--output", type=Path)
    prompt.set_defaults(func=cmd_prompt)

    generate = sub.add_parser("generate", help="生成现代诗")
    generate.add_argument("--mode", choices=("mock", "live"), default="mock")
    generate.add_argument("--prompt", type=Path, required=True)
    generate.add_argument("--repetitions", type=int, default=1)
    generate.add_argument("--output", type=Path)
    generate.add_argument("--authorize-spend", action="store_true")
    generate.add_argument("--temperature", type=float, default=1.0)
    generate.add_argument("--max-tokens", type=int, default=1200)
    generate.add_argument("--thinking", choices=("enabled", "disabled"), default="disabled")
    generate.set_defaults(func=cmd_generate)

    evaluate = sub.add_parser("evaluate", help="评估生成稿")
    evaluate.add_argument("--run", type=Path, required=True)
    evaluate.add_argument("--poet", choices=sorted(POETS))
    evaluate.set_defaults(func=cmd_evaluate)

    offline = sub.add_parser("all-offline", help="离线跑审计 + 提示词编译")
    offline.add_argument("--output", type=Path)
    offline.set_defaults(func=cmd_all_offline)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
