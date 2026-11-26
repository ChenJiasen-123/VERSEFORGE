"""Phase 1: generate the initial population of style prompts."""
from __future__ import annotations

import json

from .corpus import anonymous_references
from .llm import LLMOutputError, is_output_truncation_error
from .validation import validate_initializer, validate_prompt


INIT_SYSTEM = """你是一位中文现代诗写作指导教师。你会看到若干匿名参考作品。
你的任务不是写文学评论，也不是猜测作者，而是把多篇作品共同的可迁移写作规律，写成一份可被另一个写作者独立使用的“风格指令”，使其在拿到全新题目、且完全看不到参考作品时，仍能写出在以下方面相近的诗：字词选择、句法、分行与节奏、意象与修辞、情感表达、篇章结构。

硬性要求：
1. 指令必须具体、可执行，使用“动作+对象+约束”的写法，例如“每节2—5行，行尾多落在具体名词或短促动作上”。
2. 概括多篇作品中反复出现的规律，不要把某一篇的题材、人物、地名、情节当成通则。
3. 把可迁移的写作手法与仅属于原题材的内容分开；不要要求新诗继续写旧题材。
4. 禁止使用“富有诗意”“意境深远”“语言优美”“情感真挚”等无法操作的套话。
5. 禁止出现任何诗人姓名，也不得依赖姓名触发风格模仿。
6. 禁止引用参考作品的完整诗句或连续长片段；只能概括，不能复制。
7. 指令必须能独立使用，不得写“参考上面”“这些诗”“如前文”等依赖参考作品的话。
8. 输出 5—10 条编号指令，每条尽量短；可加一句总体说明。
9. 只输出 JSON，不要 markdown，不要解释 JSON 之外的任何内容。

JSON 结构：
{"prompt": "完整风格指令", "design_notes": "你如何从多篇作品中归纳，不能引用长句", "covered_dimensions": ["lexical", "syntax", "lineation", "imagery", "emotion", "structure"]}"""


def _rules(config):
    return {
        **config["prompt_rules"],
        "min_prompt_chars": config["population"]["min_prompt_chars"],
        "max_prompt_chars": config["population"]["max_prompt_chars"],
    }


def _payload(config, selection, *, focus, index, total, mode):
    return {
        "kind": "rpe_initialize" if mode == "population" else "rpe_reverse_once",
        "task": "从匿名参考作品反推可复用的中文诗歌风格指令",
        "mode": mode,
        "candidate_index": index,
        "candidate_total": total,
        "focus": focus,
        "reference_poems": anonymous_references(selection["references"]),
        "constraints": {
            "prompt_chars": [config["population"]["min_prompt_chars"], config["population"]["max_prompt_chars"]],
            "instruction_units_min": config["prompt_rules"]["min_instruction_units"],
            "no_poet_names": True,
            "no_reference_quotes": True,
            "must_be_independently_usable": True,
            "do_not_send_or_infer_author_identity": True,
        },
        "output_schema": {
            "prompt": "string",
            "design_notes": "string",
            "covered_dimensions": "array[string]",
        },
    }


def _one_call(llm, config, selection, *, focus, index, total, mode, cache_tag, payload_extra=None):
    payload = _payload(config, selection, focus=focus, index=index, total=total, mode=mode)
    if payload_extra:
        payload.update(payload_extra)
    data, meta = llm.call_json(
        purpose="rpe_initialize" if mode == "population" else "rpe_reverse_once",
        system=INIT_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False),
        max_tokens=config["population"]["init_max_tokens"],
        temperature=config["population"]["init_temperature"] if mode == "population" else 0.7,
        thinking=config["population"].get("thinking"),
        validator=validate_initializer,
        cache_variant=cache_tag,
    )
    prompt = data.get("prompt", "").strip()
    validation = validate_prompt(
        prompt, rules=_rules(config), references=selection["references"],
        target_name=selection["target_name"], target_aliases=selection.get("target_aliases"),
        min_chars=config["population"]["min_prompt_chars"],
        max_chars=config["population"]["max_prompt_chars"],
    )
    return data, meta, prompt, validation


def make_prompt_candidate(llm, config, selection, *, focus, index, total, mode="population",
                          cache_tag="init-0"):
    """Generate one prompt and repair deterministic rule violations a bounded number of times."""
    attempts = []
    data, meta, prompt, validation = _one_call(
        llm, config, selection, focus=focus, index=index, total=total, mode=mode, cache_tag=cache_tag,
    )
    attempts.append({"attempt": 1, "validation": validation, "meta": meta})
    repairs = config["population"]["max_prompt_repair_attempts"]
    for repair in range(repairs):
        if validation["ok"]:
            break
        payload = _payload(config, selection, focus=focus, index=index, total=total, mode=mode)
        payload["_validation_feedback"] = (
            "上一次生成的指令违反了以下硬性规则：" + "；".join(validation["errors"]) +
            "。请完整重写 prompt，保留有效的具体指令，只修复违规处，不要引用参考原句。"
        )
        data, meta, prompt, validation = _one_call(
            llm, config, selection, focus=focus, index=index, total=total, mode=mode,
            cache_tag=f"{cache_tag}-repair{repair + 1}", payload_extra={"_validation_feedback": payload["_validation_feedback"]},
        )
        attempts.append({"attempt": repair + 2, "validation": validation, "meta": meta})
    return {
        "origin": "initializer" if mode == "population" else "one_shot_reverse",
        "focus": focus,
        "source_index": index,
        "prompt": prompt,
        "design_notes": data.get("design_notes", "") if data else "",
        "covered_dimensions": data.get("covered_dimensions", []) if data else [],
        "valid": validation["ok"],
        "validation": validation,
        "attempts": attempts,
        "model": meta.get("model") if meta else None,
        "mock": bool(getattr(llm, "mock", False)),
    }


def initialize_population(llm, config, selection):
    size = config["population"]["size"]
    focuses = [
        "字词与语气：优先具体的名词和动词，少用抽象形容词。",
        "句法与分行：让短句、跨行停顿和重复结构承担节奏。",
        "意象与修辞：让日常物件与自然物并置，避免解释性比喻。",
        "情感与抒情位置：先写动作和场景，再让情感从缝隙里出现。",
        "篇章推进：用空间或时间移动组织全诗，结尾落在具体物象上。",
        "声音与重复：用重复、呼告和短句回环制造音乐性。",
        "视角与人称：通过人称变化或观看位置变化组织抒情。",
    ]
    candidates = []
    for index in range(size):
        focus = focuses[index % len(focuses)]
        try:
            candidates.append(make_prompt_candidate(
                llm, config, selection, focus=focus, index=index, total=size,
                mode="population", cache_tag=f"init-{index}",
            ))
        except (LLMOutputError, RuntimeError) as exc:
            if isinstance(exc, RuntimeError) and not is_output_truncation_error(exc):
                raise
            candidates.append(_invalid_record(
                origin="initializer", focus=focus, index=index, error=str(exc), mock=getattr(llm, "mock", False),
            ))
    return candidates


def _invalid_record(*, origin, focus, index, error, mock):
    return {
        "origin": origin,
        "focus": focus,
        "source_index": index,
        "prompt": "",
        "design_notes": "",
        "covered_dimensions": [],
        "valid": False,
        "validation": {"ok": False, "errors": [error], "warnings": [], "metrics": {}},
        "attempts": [],
        "model": None,
        "mock": mock,
    }


def reverse_once(llm, config, selection):
    try:
        return make_prompt_candidate(
            llm, config, selection,
            focus="一次性通读全部参考作品，归纳最显著的共同写作规律。",
            index=0, total=1, mode="one_shot_reverse", cache_tag="benchmark-b-reverse",
        )
    except (LLMOutputError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError) and not is_output_truncation_error(exc):
            raise
        return _invalid_record(
            origin="one_shot_reverse", focus="one_shot_reverse", index=0,
            error=str(exc), mock=getattr(llm, "mock", False),
        )
