"""Prompt-safety rules and JSON schema validators.

The rules are intentionally deterministic and conservative.  They reject the
most obvious forms of name-triggered imitation and verbatim corpus leakage;
they do not claim to prove that a prompt is stylistically good.
"""
from __future__ import annotations

import re

from .metrics import longest_common_substring_length


def _han_normalize(text: str) -> str:
    return re.sub(r"[^\u3400-\u9fff]", "", text)


def _instruction_units(prompt: str) -> list[str]:
    line_units = []
    for line in prompt.splitlines():
        body = re.sub(r"^\s*(?:[-*•·]|\d+[.、)]|[一二三四五六七八九十]+[、.)])\s*", "", line).strip()
        if len(body) >= 8:
            line_units.append(body)
    sentence_units = [part.strip() for part in re.split(r"[。；;]\s*", prompt) if len(part.strip()) >= 8]
    return line_units if len(line_units) >= len(sentence_units) else sentence_units


def validate_prompt(prompt, *, rules, references, target_name, target_aliases=None,
                    min_chars=None, max_chars=None) -> dict:
    errors, warnings = [], []
    aliases = [target_name] + list(target_aliases or [])
    min_chars = rules.get("min_prompt_chars", 120) if min_chars is None else min_chars
    max_chars = rules.get("max_prompt_chars", 1400) if max_chars is None else max_chars
    if not isinstance(prompt, str) or not prompt.strip():
        return {"ok": False, "errors": ["Prompt 为空或不是字符串"], "warnings": [],
                "metrics": {"char_count": 0, "instruction_units": 0}}
    prompt = prompt.strip()
    char_count = len(prompt)
    if char_count < min_chars:
        errors.append(f"Prompt 太短（{char_count} 字），低于 {min_chars} 字")
    if char_count > max_chars:
        errors.append(f"Prompt 太长（{char_count} 字），超过 {max_chars} 字")

    for name in aliases:
        if name and name in prompt:
            errors.append(f"Prompt 出现目标诗人姓名或别名“{name}”；风格指令不得依赖姓名触发模仿")

    for phrase in rules.get("forbidden_dependency_phrases") or []:
        if phrase in prompt:
            errors.append(f"Prompt 含有依赖参考材料的说法“{phrase}”，无法独立使用")

    found_vague = [phrase for phrase in rules.get("vague_phrases") or [] if phrase in prompt]
    if len(found_vague) > rules.get("max_vague_phrases", 2):
        errors.append("含糊套话过多：" + "、".join(found_vague))
    elif found_vague:
        warnings.append("含有含糊套话，建议替换为可执行指令：" + "、".join(found_vague))

    units = _instruction_units(prompt)
    if len(units) < rules.get("min_instruction_units", 3):
        errors.append(f"可执行指令单元不足（{len(units)} < {rules.get('min_instruction_units', 3)}）")

    normalized_prompt = _han_normalize(prompt)
    longest = 0
    for index, ref in enumerate(references, 1):
        length = longest_common_substring_length(prompt, ref["text"])
        if length > longest:
            longest = length
        ref_lines = [line for line in ref["text"].splitlines() if len(_han_normalize(line)) >= 8]
        for line in ref_lines:
            body = _han_normalize(line)
            if body and body in normalized_prompt:
                errors.append(f"Prompt 复制了参考作品{index}的完整诗句：“{line.strip()}”")
                break
    if longest >= rules.get("max_reference_ngram", 12):
        errors.append(
            f"Prompt 与参考作品存在 {longest} 字连续重合，超过上限 {rules.get('max_reference_ngram', 12)}"
        )
    elif longest >= rules.get("warn_reference_ngram", 8):
        warnings.append(f"Prompt 与参考作品有 {longest} 字连续重合，建议改为概括性表述")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "char_count": char_count,
            "instruction_units": len(units),
            "vague_phrases": found_vague,
            "longest_reference_common_substring": longest,
        },
    }


def validate_generation(data) -> list[str]:
    issues = []
    if not isinstance(data, dict):
        return ["输出必须是 JSON 对象"]
    title = data.get("title")
    lines = data.get("lines")
    if not isinstance(title, str) or not title.strip() or "\n" in title:
        issues.append("title 须为非空单行字符串")
    if not isinstance(lines, list) or not lines:
        issues.append("lines 须为非空数组")
    else:
        if any(not isinstance(line, str) or "\n" in line or "\r" in line for line in lines):
            issues.append("lines 每项须为单行字符串")
        elif not any(line.strip() for line in lines):
            issues.append("lines 至少需要一行非空正文")
    return issues


def validate_initializer(data) -> list[str]:
    issues = []
    if not isinstance(data, dict):
        return ["输出必须是 JSON 对象"]
    if not isinstance(data.get("prompt"), str) or not data["prompt"].strip():
        issues.append("prompt 须为非空字符串")
    if "design_notes" in data and not isinstance(data["design_notes"], str):
        issues.append("design_notes 须为字符串")
    if "covered_dimensions" in data and not isinstance(data["covered_dimensions"], list):
        issues.append("covered_dimensions 须为数组")
    return issues


def validate_mutation(data) -> list[str]:
    issues = []
    if not isinstance(data, dict):
        return ["输出必须是 JSON 对象"]
    if not isinstance(data.get("prompt"), str) or not data["prompt"].strip():
        issues.append("prompt 须为非空字符串")
    changes = data.get("changes")
    if not isinstance(changes, list) or not changes:
        issues.append("changes 须为非空数组")
    else:
        for item in changes:
            if not isinstance(item, dict):
                issues.append("changes 每项须为对象")
                break
            if not isinstance(item.get("op"), str) or not item["op"].strip():
                issues.append("每条 change 须有 op")
                break
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                issues.append("每条 change 须有 reason")
                break
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        issues.append("summary 须为非空字符串")
    return issues


ANALYSIS_LISTS = ("reproduced", "missing", "extraneous", "prompt_issues", "actionable_suggestions")


def validate_analysis(data) -> list[str]:
    issues = []
    if not isinstance(data, dict):
        return ["输出必须是 JSON 对象"]
    for key in ANALYSIS_LISTS:
        if not isinstance(data.get(key), list):
            issues.append(f"{key} 须为数组")
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        issues.append("summary 须为非空字符串")
    if isinstance(data.get("actionable_suggestions"), list) and not data["actionable_suggestions"]:
        issues.append("actionable_suggestions 不能为空")
    topic = data.get("topic_overreliance")
    if topic is not None and not isinstance(topic, dict):
        issues.append("topic_overreliance 须为对象")
    return issues


JUDGE_DIMENSIONS = (
    "lexical", "syntax", "lineation", "imagery", "emotion", "structure", "progression",
    "concreteness", "repetition", "addressivity", "mythic_register", "closure",
    "literary_quality", "topic_adherence", "originality",
)
STYLE_DIMENSIONS = (
    "lexical", "syntax", "lineation", "imagery", "emotion", "structure", "progression",
    "concreteness", "repetition", "addressivity", "mythic_register", "closure",
)


def validate_judge(data, require_evidence=True) -> list[str]:
    issues = []
    if not isinstance(data, dict):
        return ["输出必须是 JSON 对象"]
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, dict):
        return ["dimensions 须为对象"]
    for key in JUDGE_DIMENSIONS:
        item = dimensions.get(key)
        if not isinstance(item, dict):
            issues.append(f"缺少维度 {key}")
            continue
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 5:
            issues.append(f"{key}.score 须为0—5的数值")
        rationale = item.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            issues.append(f"{key}.rationale 须为非空字符串")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or (require_evidence and not evidence):
            issues.append(f"{key}.evidence 须为非空数组")
        uncertainty = item.get("uncertainty")
        if uncertainty is not None and not isinstance(uncertainty, str):
            issues.append(f"{key}.uncertainty 须为字符串")
    for key in (k for k in dimensions if k not in JUDGE_DIMENSIONS):
        item = dimensions[key]
        if not isinstance(item, dict) or not isinstance(item.get("score"), (int, float)):
            issues.append(f"未定义维度 {key} 缺少数值 score")
    if not isinstance(data.get("overall_notes"), str):
        issues.append("overall_notes 须为字符串")
    return issues
