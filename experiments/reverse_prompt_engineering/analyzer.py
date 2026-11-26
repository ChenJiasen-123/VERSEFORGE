"""Phase 4: evidence-based style difference analysis for one candidate."""
from __future__ import annotations

import json

from .corpus import anonymous_references
from .llm import BudgetExhausted, LLMOutputError, is_output_truncation_error
from .validation import validate_analysis


ANALYZER_SYSTEM = """你是比较诗学的细读者。你会看到一组匿名参考诗、某一份风格指令，以及按该指令人为生成的诗。
你的任务是对照“生成诗”和“参考诗”，找出可迁移风格上的相同与差异，并检查风格指令本身是否有效。不要猜测作者身份，不要写作者生平，不要因为题材不同就直接判为风格失败。

请逐项分析：
1. 已经成功复现的风格特征：字词、句法、分行节奏、意象修辞、情感表达、篇章结构。
2. 尚未复现的风格特征。
3. 生成作品中出现、但参考作品并不具有的写作倾向。
4. 候选 Prompt 中无效、含糊、重复或相互冲突的指令。
5. 当前生成结果是否过度依赖某个题材、意象或固定句式。

证据规则：
- 每一项都要给出短引文或可核对的位置描述；没有证据就写“证据不足”，不要编造。
- 明确区分 claim_type：
  - observation：可以直接从文本核对的观察；
  - interpretation：文学解释或推测。
- confidence 用 low / medium / high；证据不足时用 low。
- 最后给出简洁、可操作的修改建议；建议要能直接转成增删改 Prompt 的动作。

只输出 JSON，不要 markdown。JSON 结构：
{
  "reproduced": [{"feature": "...", "generated_evidence": "...", "reference_evidence": "...", "claim_type": "observation|interpretation", "confidence": "low|medium|high"}],
  "missing": [{"feature": "...", "generated_evidence": "...", "reference_evidence": "...", "claim_type": "...", "confidence": "..."}],
  "extraneous": [{"feature": "...", "generated_evidence": "...", "claim_type": "...", "confidence": "..."}],
  "prompt_issues": [{"quote": "...", "issue_type": "ineffective|vague|redundant|conflicting|over_specific", "explanation": "...", "claim_type": "...", "confidence": "..."}],
  "topic_overreliance": {"assessment": "...", "evidence": "...", "claim_type": "...", "confidence": "..."},
  "summary": "一段简洁总结",
  "actionable_suggestions": ["...", "..."]
}"""


def _generated_poems(evaluation, limit=6):
    rows = []
    for item in evaluation.get("evaluations", []):
        if not item.get("ok"):
            continue
        gen = item.get("generation") or {}
        rows.append({
            "topic_id": item.get("topic_id"),
            "topic": item.get("topic"),
            "repetition": item.get("repetition"),
            "title": gen.get("title"),
            "lines": gen.get("raw_lines") or gen.get("lines") or [],
            "text": gen.get("text") or "",
        })
        if len(rows) >= limit:
            break
    return rows


def _fallback(candidate, reason):
    return {
        "reproduced": [],
        "missing": [],
        "extraneous": [],
        "prompt_issues": [{
            "quote": "",
            "issue_type": "ineffective",
            "explanation": reason,
            "claim_type": "observation",
            "confidence": "high",
        }],
        "topic_overreliance": {
            "assessment": "无法判断：没有可用的生成作品。",
            "evidence": "",
            "claim_type": "observation",
            "confidence": "high",
        },
        "summary": reason,
        "actionable_suggestions": [
            "保留父代中已经具体、可执行且不依赖姓名的指令。",
            "删除无法从生成文本验证的抽象评价。",
            "增加一条关于分行、句法或具体物象的可观察限制。",
        ],
        "fallback": True,
        "mock": bool(candidate.get("mock")),
    }


def analyze_candidate(llm, config, candidate, evaluation, selection):
    generated = _generated_poems(evaluation)
    if not generated:
        return _fallback(candidate, "父代没有产生可用作品，无法做真实差异分析；使用保守的本地回退建议。")
    payload = {
        "kind": "rpe_analyze_candidate",
        "reference_poems": anonymous_references(selection["references"]),
        "candidate_prompt": candidate["prompt"],
        "generated_poems": generated,
        "analysis_dimensions": [
            "lexical", "syntax", "lineation", "imagery", "emotion", "structure",
            "prompt_instruction_quality", "topic_overreliance",
        ],
        "output_schema": "见系统消息",
    }
    try:
        data, meta = llm.call_json(
            purpose="rpe_analyze_candidate",
            system=ANALYZER_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=config["population"]["analysis_max_tokens"],
            temperature=config["population"]["analysis_temperature"],
            thinking=config["population"].get("thinking"),
            validator=validate_analysis,
            cache_variant=f"{candidate['id']}:analysis",
        )
        data["analysis_model"] = meta.get("model")
        data["analysis_meta"] = meta
        data["fallback"] = False
        data["mock"] = bool(getattr(llm, "mock", False))
        return data
    except BudgetExhausted:
        raise
    except LLMOutputError as exc:
        fallback = _fallback(candidate, f"LLM 差异分析失败：{type(exc).__name__}: {exc}")
        fallback["analysis_error"] = str(exc)
        return fallback
    except RuntimeError as exc:
        if not is_output_truncation_error(exc):
            raise
        fallback = _fallback(candidate, f"LLM 差异分析输出被截断：{exc}")
        fallback["analysis_error"] = str(exc)
        return fallback
    except (ValueError, TypeError) as exc:
        fallback = _fallback(candidate, f"LLM 差异分析失败：{type(exc).__name__}: {exc}")
        fallback["analysis_error"] = str(exc)
        return fallback
