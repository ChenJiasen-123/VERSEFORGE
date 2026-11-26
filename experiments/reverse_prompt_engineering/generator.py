"""Phase 2: generate poems from a candidate prompt and a creation topic.

The generation call never receives reference poems, the poet's name, a
candidate id, generation number, or evaluation feedback.
"""
from __future__ import annotations

import json
import re

from poetry_agent.core import Poem, Task, check
from .llm import BudgetExhausted, LLMOutputError, is_output_truncation_error
from .validation import validate_generation


GENERATOR_SYSTEM = """你是中文诗歌写作者。你会收到一份风格指令、一个创作题目和体裁要求。
你完全看不到任何参考作品、作者姓名或评价结果。请独立完成一首诗。

要求：
1. 严格按风格指令写作，但不要解释或引用风格指令。
2. 题目、体裁、行数、分节和题目中的明确要求优先于风格指令；如果风格指令与题目要求冲突，以题目要求为准，并在不违反题目的前提下尽量执行风格指令。
3. 题目是新的；不要复述任何既有作品的成句、人物或情节。
4. 只输出 JSON，不要 markdown。
JSON 结构：{"title": "标题", "lines": ["第一行", "第二行", ...]}
每一行必须是一个独立的字符串元素，不要在一行里放多个换行。分节可以用空字符串 "" 表示；不要用含空格的行代替空行。"""


_RANGE = r"(\d+)\s*[—–―~～-]\s*(\d+)"


def stanza_shape(raw_lines: list[str]) -> list[int]:
    """每节的非空行数；空字符串表示分节。"""
    blocks: list[int] = []
    current = 0
    for line in raw_lines:
        if line.strip():
            current += 1
        elif current:
            blocks.append(current)
            current = 0
    if current:
        blocks.append(current)
    return blocks


def requirement_issues(raw_lines: list[str], topic: dict) -> list[str]:
    """检查题目写明的总行数下限、分节数和每节行数。

    ``poetry_agent.core.check`` 只检查总行数上限；分节与下限此前无人执行，
    导致违反“分2—4节/每节1—6行/至少12行”的诗也能算格式通过。
    """
    issues: list[str] = []
    requirements = topic.get("requirements") or ""
    total = sum(1 for line in raw_lines if line.strip())
    blocks = stanza_shape(raw_lines)

    match = re.search(r"(?<!每节)" + _RANGE + r"\s*行", requirements)
    if match:
        low = int(match.group(1))
        if total < low:
            issues.append(f"正文{total}行，少于{low}行")

    match = re.search(r"分\s*" + _RANGE + r"\s*节", requirements)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if not low <= len(blocks) <= high:
            issues.append(f"正文{len(blocks)}节，题目要求{low}—{high}节")

    match = re.search(r"每节\s*" + _RANGE + r"\s*行", requirements)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        bad = [index for index, size in enumerate(blocks, 1) if not low <= size <= high]
        if bad:
            issues.append(f"第{'、'.join(map(str, bad))}节行数不在{low}—{high}行内")
    return issues


def task_from_topic(topic: dict, config: dict) -> Task:
    genre = topic.get("genre") or config["generation"]["default_genre"]
    kwargs = {
        "topic": topic["topic"],
        "genre": genre,
        "max_lines": int(topic.get("max_lines") or config["generation"]["default_max_lines"]),
        "extra_requirements": topic.get("requirements", ""),
    }
    if genre == "qijue":
        kwargs["qijue_pattern"] = topic.get("pattern")
    elif genre == "wujue":
        kwargs["wujue_pattern"] = topic.get("pattern")
    elif genre == "wulv":
        kwargs["lushi_pattern"] = topic.get("pattern")
    elif genre == "qilv":
        kwargs["lushi_pattern"] = topic.get("pattern")
    elif genre == "ci":
        kwargs["ci_profile"] = topic.get("ci_profile")
    return Task(**kwargs)


def generation_payload(style_prompt: str, topic: dict, config: dict) -> dict:
    return {
        "kind": "rpe_generate_poem",
        "style_prompt": style_prompt,
        "topic": topic["topic"],
        "genre": topic.get("genre") or config["generation"]["default_genre"],
        "max_lines": int(topic.get("max_lines") or config["generation"]["default_max_lines"]),
        "requirements": topic.get("requirements", ""),
        "output_schema": {"title": "string", "lines": "array[string]"},
    }


def generate_poem(llm, config, style_prompt: str, topic: dict, *, cache_variant: str) -> dict:
    payload = generation_payload(style_prompt, topic, config)
    try:
        data, meta = llm.call_json(
            purpose="rpe_generate_poem",
            system=GENERATOR_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=config["generation"]["max_tokens"],
            temperature=config["generation"]["temperature"],
            thinking=config["generation"]["thinking"],
            validator=validate_generation,
            cache_variant=cache_variant,
        )
        raw_lines = [line.strip() for line in data["lines"]]
        body_lines = [line for line in raw_lines if line]
        if not body_lines:
            raise ValueError("lines 没有非空正文")
        poem = Poem(str(data["title"]).strip(), body_lines)
        task = task_from_topic(topic, config)
        form_issues = check(poem, task) + requirement_issues(raw_lines, topic)
        text = "\n".join(raw_lines).strip("\n")
        return {
            "ok": True,
            "topic_id": topic["id"],
            "title": poem.title,
            "lines": poem.lines,
            "raw_lines": raw_lines,
            "text": text,
            "form_ok": not form_issues,
            "form_issues": form_issues,
            "meta": meta,
            "mock": bool(getattr(llm, "mock", False)),
        }
    except BudgetExhausted:
        raise
    except LLMOutputError as exc:  # unusable JSON is an evaluation failure
        return {
            "ok": False,
            "topic_id": topic.get("id"),
            "title": None,
            "lines": [],
            "text": "",
            "form_ok": False,
            "form_issues": [f"生成失败：{type(exc).__name__}: {exc}"],
            "meta": {},
            "mock": bool(getattr(llm, "mock", False)),
        }
    except RuntimeError as exc:
        if not is_output_truncation_error(exc):
            raise
        return {
            "ok": False,
            "topic_id": topic.get("id"),
            "title": None,
            "lines": [],
            "text": "",
            "form_ok": False,
            "form_issues": [f"生成输出被截断：{exc}"],
            "meta": {},
            "mock": bool(getattr(llm, "mock", False)),
        }
    except (ValueError, TypeError) as exc:  # unusable output is an evaluation failure
        return {
            "ok": False,
            "topic_id": topic.get("id"),
            "title": None,
            "lines": [],
            "text": "",
            "form_ok": False,
            "form_issues": [f"生成失败：{type(exc).__name__}: {exc}"],
            "meta": {},
            "mock": bool(getattr(llm, "mock", False)),
        }
