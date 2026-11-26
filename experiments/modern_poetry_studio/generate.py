"""Generate modern poems from an inspectable style prompt.

Live mode is opt-in: it refuses to run without ``--authorize-spend`` and prints
the number of calls before sending anything.  Mock mode is deterministic and
exists only for tests and for checking the pipeline.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from poetry_agent.client import DeepSeekClient, load_env

ROOT = Path(__file__).resolve().parents[2]

SYSTEM = """你是中文现代诗写作者。你会收到一份风格指令、一个题目和行数要求。
你看不到参考作品、诗人姓名或任何评价结果。请独立完成一首诗。

要求：
1. 按风格指令写作，但不要在诗里解释、引用或复述指令。
2. 题目是新的；不要复述任何既有作品的成句、人物或情节。
3. 正文行数不得超过 hard_max_lines；宁可少写，不要超行。
4. 只输出 JSON，不要 markdown。
JSON 结构：{"title": "标题", "stanzas": [["第一行", "第二行"], ["下一节第一行"]]}
每节是一个字符串数组；行内不要放换行。"""

DEFAULT_TOPICS = [
    {
        "id": "t01",
        "topic": "深夜医院走廊尽头的自动售货机",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；写深夜、机器与人的疲惫；不得出现任何诗人姓名。",
    },
    {
        "id": "t02",
        "topic": "洪水退去后的乡村小学操场",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；写灾后清理与儿童返校；不得出现任何诗人姓名。",
    },
    {
        "id": "t03",
        "topic": "跨江大桥下的夜班渡轮",
        "max_lines": 20,
        "requirements": "12—20行，分2—4节；写夜班工人、江水与城市灯光；不得出现任何诗人姓名。",
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_poem(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError("模型未返回有效 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("输出必须是 JSON 对象")
    title = data.get("title")
    stanzas = data.get("stanzas")
    lines = data.get("lines")
    def split_lines(value):
        if not isinstance(value, str):
            raise ValueError("每一行须为字符串")
        parts = [part.strip() for part in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        parts = [part for part in parts if part]
        if not parts:
            raise ValueError("每一行须为非空单行字符串")
        return parts

    if isinstance(stanzas, list) and stanzas:
        flat = []
        for stanza in stanzas:
            if isinstance(stanza, str):
                flat.extend(split_lines(stanza))
            elif isinstance(stanza, list) and stanza:
                for line in stanza:
                    flat.extend(split_lines(line))
            else:
                raise ValueError("stanzas 的每一节须为非空数组或字符串")
        body = flat
    elif isinstance(lines, list) and lines:
        body = []
        for line in lines:
            body.extend(split_lines(line))
    else:
        raise ValueError("缺少 lines 或 stanzas")
    if not isinstance(title, str) or not title.strip() or "\n" in title:
        raise ValueError("缺少有效标题")
    return {"title": title.strip(), "lines": body, "stanzas": stanzas if isinstance(stanzas, list) else None}


def build_user(style_prompt: str, topic: dict) -> str:
    return json.dumps(
        {
            "style_prompt": style_prompt,
            "topic": topic["topic"],
            "hard_max_lines": topic.get("max_lines", 20),
            "requirements": topic.get("requirements", ""),
            "output_schema": {"title": "string", "stanzas": "array[array[string]]"},
        },
        ensure_ascii=False,
    )


class StudioMockClient:
    mock = True
    model = "mock-modern-studio"

    def complete(self, system, user, timeout, max_tokens=4096, thinking=None, temperature=None):
        topic = json.loads(user)["topic"]
        lines = [
            "走廊尽头，一台机器亮着",
            "光是冷的",
            "我投下硬币",
            "它吐出一罐水",
            "",
            "我站在那儿",
            "听压缩机低低地响",
            "像有人在墙里呼吸",
            "",
            "最后我走了",
            "机器还亮着",
        ]
        return {
            "content": json.dumps(
                {"title": "模拟作品（非模型生成）", "stanzas": [lines[:4], lines[5:8], lines[9:]]},
                ensure_ascii=False,
            ),
            "usage": {},
            "request_settings": {"mock": True, "topic": topic},
        }


def generate_one(client, style_prompt: str, topic: dict, *, temperature: float = 1.0,
                 max_tokens: int = 1200, thinking: str = "disabled",
                 max_attempts: int = 2) -> dict:
    user = build_user(style_prompt, topic)
    last_error = None
    last_raw = ""
    last_response = {}
    for attempt in range(1, max_attempts + 1):
        system = SYSTEM
        if attempt > 1:
            system += "\n上一次输出不是合法 JSON。请只输出合法 JSON；行内引号必须转义或改用中文引号。"
        response = client.complete(
            system,
            user,
            timeout=90,
            max_tokens=max_tokens,
            thinking=thinking,
            temperature=temperature,
        )
        last_response = response
        last_raw = response.get("content", "")
        try:
            poem = parse_poem(last_raw)
        except ValueError as exc:
            last_error = str(exc)
            continue
        max_lines = int(topic.get("max_lines", 20))
        issues = []
        if len(poem["lines"]) > max_lines:
            issues.append(f"正文 {len(poem['lines'])} 行，超过 {max_lines} 行")
        if any(name in "\n".join(poem["lines"]) for name in ("海子", "北岛", "舒婷", "顾城")):
            issues.append("正文出现诗人姓名")
        return {
            "ok": not issues,
            "topic_id": topic.get("id"),
            "topic": topic.get("topic"),
            "title": poem["title"],
            "lines": poem["lines"],
            "stanzas": poem["stanzas"],
            "text": "\n".join(poem["lines"]),
            "issues": issues,
            "attempts": attempt,
            "usage": response.get("usage", {}),
            "request_settings": response.get("request_settings", {}),
            "mock": bool(getattr(client, "mock", False)),
            "created_at": _now(),
        }
    return {
        "ok": False,
        "topic_id": topic.get("id"),
        "topic": topic.get("topic"),
        "title": None,
        "lines": [],
        "stanzas": None,
        "text": "",
        "issues": [f"JSON 解析失败：{last_error}"],
        "attempts": max_attempts,
        "raw_content": last_raw[:4000],
        "usage": last_response.get("usage", {}),
        "request_settings": last_response.get("request_settings", {}),
        "mock": bool(getattr(client, "mock", False)),
        "created_at": _now(),
    }


def run_generation(
    *,
    mode: str,
    prompt_record: dict,
    topics: list[dict],
    repetitions: int,
    output_dir: Path,
    authorize_spend: bool = False,
    temperature: float = 1.0,
    max_tokens: int = 1200,
    thinking: str = "disabled",
) -> dict:
    if mode not in ("mock", "live"):
        raise ValueError("mode 须为 mock 或 live")
    if mode == "live" and not authorize_spend:
        raise ValueError("live 模式需要 --authorize-spend；本命令会产生真实 API 费用")
    if repetitions < 1:
        raise ValueError("repetitions 须为正整数")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{mode}-{uuid4().hex[:6]}"
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "prompt.json").write_text(json.dumps(prompt_record, ensure_ascii=False, indent=2), encoding="utf-8")

    if mode == "mock":
        client = StudioMockClient()
    else:
        load_env(ROOT / ".env")
        client = DeepSeekClient()

    calls = len(topics) * repetitions
    manifest = {
        "run_id": run_id,
        "mode": mode,
        "is_mock": mode == "mock",
        "model": client.model,
        "created_at": _now(),
        "prompt_variant": prompt_record.get("variant"),
        "prompt_sha256": _hash(prompt_record["prompt"]),
        "prompt_char_count": len(prompt_record["prompt"]),
        "topics": topics,
        "repetitions": repetitions,
        "estimated_calls": calls,
        "warning": (
            "MOCK RUN：固定模拟文本，不能作为模型行为或研究结论。"
            if mode == "mock" else
            "LIVE RUN：真实 API 调用；作品需要人工阅读，自动指标不是质量结论。"
        ),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    records = []
    ledger = []
    for topic in topics:
        for repetition in range(repetitions):
            record = generate_one(
                client, prompt_record["prompt"], topic,
                temperature=temperature, max_tokens=max_tokens, thinking=thinking,
            )
            record["repetition"] = repetition
            record["prompt_variant"] = prompt_record.get("variant")
            records.append(record)
            ledger.append({
                "at": _now(),
                "cache_hit": False,
                "mock": record["mock"],
                "model": client.model,
                "purpose": "modern_generate_poem",
                "topic_id": topic.get("id"),
                "repetition": repetition,
                "usage": record.get("usage", {}),
                "request_settings": record.get("request_settings", {}),
            })
            print(f"[{len(records)}/{calls}] {topic.get('id')} rep={repetition} ok={record['ok']} title={record['title']}")

    result = {
        "run_id": run_id,
        "mode": mode,
        "is_mock": mode == "mock",
        "created_at": _now(),
        "model": client.model,
        "prompt_variant": prompt_record.get("variant"),
        "prompt_sha256": _hash(prompt_record["prompt"]),
        "records": records,
        "ledger": ledger,
        "call_count": len([row for row in ledger if not row["mock"]]),
        "limits": [
            "同题重复次数有限，不能据此估计稳定风格效果。",
            "自动指标只检查表面分布，不判断诗的好坏。",
            "没有人类盲评时，不得声称质量提升。",
        ],
    }
    (run_dir / "generations.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (run_dir / "ledger.jsonl").open("w", encoding="utf-8") as fh:
        for row in ledger:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"运行目录：{run_dir}")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="用编译好的风格提示词生成现代诗")
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--prompt", type=Path, required=True, help="prompt.py 生成的 JSON")
    parser.add_argument("--topics", type=Path, help="题目 JSON；省略时用内置三题")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("var/modern_poetry_studio/generations"))
    parser.add_argument("--authorize-spend", action="store_true")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--thinking", choices=("enabled", "disabled"), default="disabled")
    args = parser.parse_args()
    prompt_record = json.loads(args.prompt.read_text(encoding="utf-8"))
    topics = json.loads(args.topics.read_text(encoding="utf-8")) if args.topics else DEFAULT_TOPICS
    result = run_generation(
        mode=args.mode,
        prompt_record=prompt_record,
        topics=topics,
        repetitions=args.repetitions,
        output_dir=args.output,
        authorize_spend=args.authorize_spend,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        thinking=args.thinking,
    )
    print(json.dumps({"run_id": result["run_id"], "calls": result["call_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
