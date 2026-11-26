"""Phase 5: LLM-guided, evidence-driven prompt mutation.

Exactly one child prompt is produced per parent.  The optimizer is never
allowed to edit a generated poem directly.
"""
from __future__ import annotations

import json

from .validation import validate_mutation, validate_prompt


MUTATOR_SYSTEM = """你是“风格 Prompt 变异器”。你会收到：
- 一份父代风格指令；
- 对该指令生成作品的差异分析，包括已复现特征、缺失特征、多余倾向、指令问题和可操作建议。

你的任务是修改“产生诗歌的 Prompt”，不是修改诗歌本身。每个父代只产生一个子代 Prompt。

允许的变异操作：
- add：增加一条可执行指令；
- delete：删除无效或有害指令；
- replace：用更具体的指令替换含糊指令；
- split：把复合指令拆成两条；
- merge：合并语义重复的指令；
- adjust：调整某条指令的具体程度；
- conflict_fix：修复相互冲突的指令。

硬性要求：
1. 尽可能保留已经证明有效的部分；不要为了变化而重写全部内容。
2. 每条修改都要在 changes 中记录 op、target、reason；reason 要引用差异分析中的观察，不能空泛。
3. 不得出现任何诗人姓名，不得依赖姓名触发模仿。
4. 不得引用参考作品的完整诗句或连续长片段。
5. 不得写“参考上面”“这些诗”“如前文”等依赖参考材料的说法；子代必须能独立使用。
6. 不得加入无法操作的评价词（如“富有诗意”“意境深远”）。
7. 子代 Prompt 的长度和指令单元必须符合给定约束。
8. 只输出 JSON，不要 markdown。

JSON 结构：
{"prompt": "完整子代 Prompt", "changes": [{"op": "add|delete|replace|split|merge|adjust|conflict_fix", "target": "被修改的指令或位置", "reason": "基于哪条差异分析"}], "preserved": ["保留了什么"], "summary": "一句话说明本次变异的预期效果"}"""


def _rules(config):
    return {
        **config["prompt_rules"],
        "min_prompt_chars": config["population"]["min_prompt_chars"],
        "max_prompt_chars": config["population"]["max_prompt_chars"],
    }


def _payload(config, parent, analysis):
    return {
        "kind": "rpe_mutate_prompt",
        "parent_prompt": parent["prompt"],
        "analysis": {
            "reproduced": analysis.get("reproduced", []),
            "missing": analysis.get("missing", []),
            "extraneous": analysis.get("extraneous", []),
            "prompt_issues": analysis.get("prompt_issues", []),
            "topic_overreliance": analysis.get("topic_overreliance"),
            "summary": analysis.get("summary", ""),
            "actionable_suggestions": analysis.get("actionable_suggestions", []),
        },
        "allowed_operations": ["add", "delete", "replace", "split", "merge", "adjust", "conflict_fix"],
        "constraints": {
            "prompt_chars": [config["population"]["min_prompt_chars"], config["population"]["max_prompt_chars"]],
            "instruction_units_min": config["prompt_rules"]["min_instruction_units"],
            "no_poet_names": True,
            "no_reference_quotes": True,
            "must_be_independently_usable": True,
            "one_child_per_parent": True,
        },
        "output_schema": {
            "prompt": "string",
            "changes": [{"op": "string", "target": "string", "reason": "string"}],
            "preserved": ["string"],
            "summary": "string",
        },
    }


def mutate_candidate(llm, config, parent, analysis, selection, *, round_id=None):
    attempts = []
    payload = _payload(config, parent, analysis)
    data, meta = llm.call_json(
        purpose="rpe_mutate_prompt",
        system=MUTATOR_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False),
        max_tokens=config["population"]["mutation_max_tokens"],
        temperature=config["population"]["mutation_temperature"],
        thinking=config["population"].get("thinking"),
        validator=validate_mutation,
        cache_variant=f"{parent['id']}:mutation:{round_id or parent.get('generation', 0)}",
    )
    prompt = data.get("prompt", "").strip()
    validation = validate_prompt(
        prompt, rules=_rules(config), references=selection["references"],
        target_name=selection["target_name"], target_aliases=selection.get("target_aliases"),
        min_chars=config["population"]["min_prompt_chars"],
        max_chars=config["population"]["max_prompt_chars"],
    )
    attempts.append({"attempt": 1, "validation": validation, "meta": meta})
    for repair in range(config["population"]["max_prompt_repair_attempts"]):
        if validation["ok"]:
            break
        retry_payload = _payload(config, parent, analysis)
        retry_payload["_validation_feedback"] = (
            "上一次子代 Prompt 违反了以下硬性规则：" + "；".join(validation["errors"]) +
            "。请输出完整子代 Prompt，保留仍然有效的指令，只修复违规处。"
        )
        data, meta = llm.call_json(
            purpose="rpe_mutate_prompt",
            system=MUTATOR_SYSTEM,
            user=json.dumps(retry_payload, ensure_ascii=False),
            max_tokens=config["population"]["mutation_max_tokens"],
            temperature=config["population"]["mutation_temperature"],
            thinking=config["population"].get("thinking"),
            validator=validate_mutation,
            cache_variant=f"{parent['id']}:mutation:{round_id or parent.get('generation', 0)}:repair{repair + 1}",
        )
        prompt = data.get("prompt", "").strip()
        validation = validate_prompt(
            prompt, rules=_rules(config), references=selection["references"],
            target_name=selection["target_name"], target_aliases=selection.get("target_aliases"),
            min_chars=config["population"]["min_prompt_chars"],
            max_chars=config["population"]["max_prompt_chars"],
        )
        attempts.append({"attempt": repair + 2, "validation": validation, "meta": meta})
    return {
        "prompt": prompt,
        "valid": validation["ok"],
        "validation": validation,
        "changes": data.get("changes", []),
        "preserved": data.get("preserved", []),
        "summary": data.get("summary", ""),
        "attempts": attempts,
        "model": meta.get("model"),
        "mock": bool(getattr(llm, "mock", False)),
    }
