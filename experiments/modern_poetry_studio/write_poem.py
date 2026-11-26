"""Write poems from a story core.

This is deliberately separated from ``generate.py``: that module writes from a
style prompt, while this module writes from a concrete person's story.  The
story core supplies inner experience and era; the prompt supplies language and
formal constraints.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from poetry_agent.client import DeepSeekClient, load_env

from experiments.modern_poetry_studio.generate import parse_poem
from experiments.modern_poetry_studio.story_core import FIELDS

ROOT = Path(__file__).resolve().parents[2]

SYSTEM = """你是中文现代诗写作者。你会收到一个故事核：一个具体的人、他背后的集体、两种世界的相撞、一笔欠债、一个转折日、一个生命问题。

写一首诗。要求：

【内容】
1. 不要解释时代，不要写“城市/乡下/时代”的论点。让物象、动作、并置承担冲突。
2. 个人经验是入口，不是终点。诗中要能感到这个人背后的一代人、一个地方、一种生活方式。
3. 至少一个具体身体细节：手、袖口、骨头、气味、重量、冻疮、指甲缝。
4. 生命问题要触及，但不要直接提问、不要总结、不要替读者说出意义。让它在动作或物象里出现。
5. 不要写“他/她”的旁观式故事；用第一人称，或一个清楚、具体的说话位置。

【语言】
6. 不要口语流水账。不要“把……投进去”“她以为够我……”“正在盖物流园”这种散文交代。
7. 用短句、碎片、倒装、名词性短语；允许长句，但必须压缩。不要每行都写成完整句。
8. 一个核心物象在全诗变形：棉袄→袖子→手→种子；铁箱→嘴→坟→传送带。不要换一堆不相干的意象。
9. 可以借用海子常用意象（火、黑夜、骨头、麦地、太阳、神、河流），但最多 3—5 个，而且每个都必须和物件/人物发生关系，不能当装饰。
10. 不要照抄海子的原句或句式，尤其不要“你所说的 X，究竟是什么意思”。
11. 不要为了金句而金句。如果有一句能单独站住，它必须只属于这首诗；换到别的诗里就不成立。

【结构】
12. 12—20 行，分 2—4 节。
13. 开头不要解释背景，直接进入物象、动作或说话。
14. 结尾不要总结、不要升华、不要用“我该把你交给谁”“谁在门里谁在门外”这种直接问题。停在一个动作、物象、声音或未完成的句子上。
15. 不要出现任何诗人姓名。

只输出 JSON：
{"title": "标题", "stanzas": [["第一行", "第二行"], ["下一节第一行"]]}"""


def build_user(core: dict, max_lines: int = 20) -> str:
    return json.dumps(
        {
            "story_core": {field: core[field] for field in FIELDS},
            "hard_max_lines": max_lines,
            "output_schema": {"title": "string", "stanzas": "array[array[string]]"},
        },
        ensure_ascii=False,
    )


class MockPoemClient:
    mock = True
    model = "mock-poem-writer"

    def complete(self, system, user, timeout, max_tokens=4096, thinking=None, temperature=None):
        lines = [
            "她把母亲的蓝外套抱在胸前",
            "像抱着一捆还没冷透的火",
            "回收箱张着嘴，等她把最后一件衣服",
            "交出去。雨落在铁皮上",
            "发出空空的回声",
            "",
            "她想起母亲补袜子时",
            "总把线头咬断在嘴里",
            "现在线头还在，袜子不在了",
            "她把外套塞进投口",
            "又抽回来",
            "袖口里掉出一粒纽扣",
            "滚进下水道的缝",
            "",
            "她蹲下去摸，摸到一手黑水",
            "站起来时，天已经亮了",
        ]
        return {
            "content": json.dumps({"title": "蓝外套", "stanzas": [lines[:5], lines[6:13], lines[14:]]}, ensure_ascii=False),
            "usage": {},
            "request_settings": {"mock": True},
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_poems(
    client,
    core: dict,
    *,
    repetitions: int = 2,
    max_lines: int = 20,
    temperature: float = 1.0,
    max_tokens: int = 1400,
) -> dict:
    if repetitions < 1:
        raise ValueError("repetitions 须为正整数")
    poems = []
    for index in range(repetitions):
        response = client.complete(
            SYSTEM, build_user(core, max_lines), timeout=90,
            max_tokens=max_tokens, thinking="disabled", temperature=temperature,
        )
        raw = response.get("content", "")
        poem = parse_poem(raw)
        issues = []
        if len(poem["lines"]) > max_lines:
            issues.append(f"正文 {len(poem['lines'])} 行，超过 {max_lines} 行")
        if any(name in "\n".join(poem["lines"]) for name in ("海子", "北岛", "舒婷", "顾城")):
            issues.append("正文出现诗人姓名")
        poems.append({
            "index": index,
            "ok": not issues,
            "title": poem["title"],
            "lines": poem["lines"],
            "stanzas": poem["stanzas"],
            "text": "\n".join(poem["lines"]),
            "issues": issues,
            "usage": response.get("usage", {}),
            "request_settings": response.get("request_settings", {}),
            "created_at": _now(),
        })
        print(f"[{index + 1}/{repetitions}] {poem['title']} ok={not issues} lines={len(poem['lines'])}")
    return {
        "story_core": core,
        "max_lines": max_lines,
        "repetitions": repetitions,
        "poems": poems,
        "created_at": _now(),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="从故事核写诗")
    parser.add_argument("--core", type=Path, required=True, help="story_core.py 生成的 JSON")
    parser.add_argument("--index", type=int, default=1, help="选第几个故事核，从1开始")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--max-lines", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("var/modern_poetry_studio/poems"))
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--authorize-spend", action="store_true")
    parser.add_argument("--temperature", type=float, default=1.0)
    args = parser.parse_args()
    if args.mode == "live" and not args.authorize_spend:
        raise SystemExit("live 模式需要 --authorize-spend")
    cores = json.loads(args.core.read_text(encoding="utf-8"))["cores"]
    if not 1 <= args.index <= len(cores):
        raise SystemExit(f"--index 须在 1—{len(cores)} 之间")
    core = cores[args.index - 1]
    if args.mode == "mock":
        client = MockPoemClient()
    else:
        load_env(ROOT / ".env")
        client = DeepSeekClient()
    result = generate_poems(
        client, core, repetitions=args.repetitions, max_lines=args.max_lines,
        temperature=args.temperature,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = args.output / f"{stamp}-{core['title'][:12]}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for poem in result["poems"]:
        print(f"\n--- {poem['title']} ({len(poem['lines'])}行)")
        print(poem["text"])
    print(f"\n保存：{path}")


if __name__ == "__main__":
    main()
