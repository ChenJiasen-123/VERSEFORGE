import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from poetry_agent.client import DeepSeekClient, MockClient, load_env
from poetry_agent.core import Task
from poetry_agent.candidates import compose_candidates
from poetry_agent.robot import speak_mock, speech_text

ROOT = Path(__file__).resolve().parent


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="诗词创作Agent：DeepSeek＋规则检查＋有限修订")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--task", type=Path, help="JSON任务文件")
    source.add_argument("--topic", help="创作主题")
    parser.add_argument("--genre", choices=["modern", "qijue", 'wujue', 'ci'], default="modern")
    parser.add_argument('--wujue-pattern', choices=['ping_rhyme','ping_no_rhyme','ze_rhyme','ze_no_rhyme'])
    parser.add_argument('--ci-profile', choices=['baixiang_yijiangnan_liyu'])
    parser.add_argument('--qijue-pattern', choices=['ping_rhyme','ping_no_rhyme','ze_rhyme','ze_no_rhyme'])
    parser.add_argument("--max-lines", type=int, default=12)
    parser.add_argument("--required", action="append", default=[], help="可重复指定必用词")
    parser.add_argument("--forbidden", action="append", default=[], help="可重复指定禁用词")
    parser.add_argument("--requirements", default="")
    parser.add_argument("--mock", action="store_true", help="离线模拟，不调用API，不产生API费用")
    parser.add_argument("--aesthetic", action="store_true", help="按体裁启用审读、修订及候选比较；尚未证明质量提升")
    parser.add_argument('--aesthetic-examples', action='store_true', help='现代诗可选实验：读取用户正面点评片段，须同时启用--aesthetic')
    parser.add_argument('--generation-thinking', choices=['enabled', 'disabled'], help='可选生成思考模式；不指定时沿用服务默认，审读与比较仍独立设置')
    parser.add_argument("--speak", action="store_true", help="打印模拟朗诵文本，不播放声音")
    parser.add_argument("--max-revisions", type=int, choices=range(3), default=2)
    parser.add_argument('--candidates', type=int, choices=range(1, 4), default=1, help='独立生成候选数量，共享总时间预算')
    parser.add_argument('--revision-scope', choices=['local', 'rewrite'], default='local',
                        help='审美修订范围：local限制改动行数及篇幅，rewrite允许重写')
    parser.add_argument("--budget", type=int, default=120, help="流程时间预算，秒；网络超时不是硬实时截止")
    args = parser.parse_args()
    try:
        if not 1 <= args.budget <= 600:
            raise ValueError("时间预算须在1—600秒之间")
        task = Task(**json.loads(args.task.read_text(encoding="utf-8-sig"))) if args.task else Task(
            args.topic, args.genre, args.max_lines, args.required, args.forbidden, args.requirements,
            qijue_pattern=args.qijue_pattern, ci_profile=args.ci_profile, wujue_pattern=args.wujue_pattern)
        load_env(ROOT / ".env")
        client = MockClient() if args.mock else DeepSeekClient()
        print(f"模式：{'离线模拟' if args.mock else '真实API（可能产生费用）'}；模型：{client.model}")
        result = compose_candidates(task, client, args.candidates, args.max_revisions, args.budget, aesthetic=args.aesthetic,
                         revision_scope=args.revision_scope, use_examples=args.aesthetic_examples, generation_thinking=args.generation_thinking)
        result["run_id"] = uuid4().hex
        result["created_at"] = datetime.now(timezone.utc).isoformat()
        result["speech_text"] = speech_text(result["poem"]) if result["poem"] else None
        folder = ROOT / "runs"
        folder.mkdir(exist_ok=True)
        path = folder / (result["run_id"] + ".json")
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if result["poem"]:
            print("\n" + result["poem"]["title"] + "\n" + "\n".join(result["poem"]["lines"]))
        print("\n状态：" + result["status"])
        for issue in result["issues"]:
            print("- " + issue)
        print("提示：程序检查范围有限，作品仍需审校。")
        if result.get('prosody'):
            basic = result['prosody'].get('basic_target_check')
            if basic:
                label = {'pass': '所选基本谱与当前字表规则通过',
                         'failed': '发现明确冲突', 'unknown': '存在待核音义或缺字'}.get(basic['status'], '待核')
                print('指定基本谱检查：' + label + '；不等于完整合律认证。')
            else:
                print('格律状态：未指定基本谱；仅记录归部证据。')
        print(f"运行记录：{path}")
        if args.speak and result["poem"]:
            if result["status"] == "constraints_passed":
                speak_mock(result["poem"])
            else:
                print("存在未通过的约束，跳过模拟朗诵。")
        return 0 if result["status"] == "constraints_passed" else 2
    except (ValueError, TypeError, RuntimeError, OSError):
        # Error messages below never include raw model responses, file contents or API keys.
        exc = sys.exception()
        if isinstance(exc, RuntimeError) or (isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)):
            print(f"错误：{exc}", file=sys.stderr)
        else:
            print("错误：任务文件或输出目录无法读取/写入，或字段不符合要求。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
