"""Phase 4: evidence-based, evaluation-grounded style difference analysis."""
from __future__ import annotations

import json
import statistics

from .corpus import anonymous_references
from .llm import BudgetExhausted, LLMOutputError, is_output_truncation_error
from .metrics import corpus_stylometry_summary, diagnose_poem_vs_corpus
from .validation import STYLE_DIMENSIONS, validate_analysis


ANALYZER_SYSTEM = """你是比较诗学的细读者与提示词诊断专家。你会看到：
1. 一组匿名参考诗及其客观表面分布统计；
2. 当前候选风格指令（Prompt）；
3. 按该指令在若干现代题目上生成的诗；
4. 匿名评审与确定性风格指标给出的瓶颈诊断摘要（最低分维度、表面分布偏离、反套路警告、格式违规）。

你的任务是结合文本细读与定量诊断，精准定位“为什么当前生成诗还不够像参考诗，或哪里写成了僵硬的规则练习作”，并审查 Prompt 本身的病因。不要猜测作者身份。

请重点检查：
1. 已经自然复现的风格特征。
2. 得分偏低或尚未复现的核心维度（尤其关注：无标点呼吸分行、长短句张力、质朴而有重量的词域、原初元素/时间生命尺度与日常物件的碰撞、赤诚呼告与变奏回返）。
3. 生成诗暴露出的“AI 规则套路病”：如行末句句加标点像散文、多节死板套同一呼告填空句式、清点琐碎工业零件而无精神开阔度、滥用解释性连词或明喻。
4. Prompt 病因审查：哪些条款无效、含糊、互相冲突、规定过死（导致填空模板化），或冗余膨胀。
5. 给出 3—5 条高优先级、可直接转化为“替换/删减/精炼 Prompt”的修改建议（优先删改僵硬配额，不要建议增加写后计数自检，也不要建议规定全诗总行数/总节数）。

证据规则：
- 给出短引文或具体指标证据；明确区分 observation 与 interpretation；confidence 用 low / medium / high。

只输出 JSON，不要 markdown。JSON 结构：
{
  "reproduced": [{"feature": "...", "generated_evidence": "...", "reference_evidence": "...", "claim_type": "observation|interpretation", "confidence": "low|medium|high"}],
  "missing": [{"feature": "...", "generated_evidence": "...", "reference_evidence": "...", "claim_type": "...", "confidence": "..."}],
  "extraneous": [{"feature": "...", "generated_evidence": "...", "claim_type": "...", "confidence": "..."}],
  "prompt_issues": [{"quote": "...", "issue_type": "ineffective|vague|redundant|conflicting|over_specific|template_inducing", "explanation": "...", "claim_type": "...", "confidence": "..."}],
  "topic_overreliance": {"assessment": "...", "evidence": "...", "claim_type": "...", "confidence": "..."},
  "summary": "一段直击核心瓶颈的总结",
  "actionable_suggestions": ["...", "..."]
}"""


def _generated_poems(evaluation, ref_texts, limit=6):
    rows = []
    for item in evaluation.get("evaluations", []):
        if not item.get("ok"):
            continue
        gen = item.get("generation") or {}
        text = gen.get("text") or ""
        diag = diagnose_poem_vs_corpus(text, ref_texts) if text and ref_texts else {}
        rows.append({
            "topic_id": item.get("topic_id"),
            "topic": item.get("topic"),
            "repetition": item.get("repetition"),
            "title": gen.get("title"),
            "lines": gen.get("raw_lines") or gen.get("lines") or [],
            "text": text,
            "form_ok": gen.get("form_ok", True),
            "form_issues": gen.get("form_issues") or [],
            "surface_deviations": diag.get("deviations", []),
            "anti_slop_flags": diag.get("anti_slop_flags", []),
        })
        if len(rows) >= limit:
            break
    return rows


def _evaluation_digest(evaluation: dict) -> dict:
    ok_rows = [item for item in evaluation.get("evaluations", []) if item.get("ok")]
    if not ok_rows:
        return {}
    dim_means = {}
    weak_notes = {}
    for dim in STYLE_DIMENSIONS:
        if dim == "progression":
            continue
        scores = [
            item["judge"]["dimensions"][dim]["score"]
            for item in ok_rows if "judge" in item and dim in item["judge"].get("dimensions", {})
        ]
        if scores:
            dim_means[dim] = round(statistics.mean(scores), 2)
    ordered_weak = sorted(dim_means.items(), key=lambda kv: kv[1])
    for dim, _ in ordered_weak[:4]:
        rationales = []
        for item in ok_rows:
            r = item.get("judge", {}).get("dimensions", {}).get(dim, {}).get("rationale")
            if r and r not in rationales:
                rationales.append(r)
        weak_notes[dim] = rationales[:2]
    form_failures = [
        {"topic_id": item.get("topic_id"), "issues": (item.get("generation") or {}).get("form_issues", [])}
        for item in evaluation.get("evaluations", [])
        if (item.get("generation") or {}).get("form_issues")
    ]
    return {
        "eligible_rate": evaluation.get("eligible_rate"),
        "style_score": evaluation.get("style_score"),
        "deterministic_style_score": evaluation.get("deterministic_style_score"),
        "judge_style_score": evaluation.get("judge_style_score"),
        "literary_quality_score": evaluation.get("literary_quality_score"),
        "dimension_means_sorted_weakest_first": ordered_weak,
        "weakest_dimension_rationales": weak_notes,
        "form_failures": form_failures,
    }


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
            "保留父代中已经自然有效且不依赖姓名的原则。",
            "删去会导致机械填空或与题目篇幅冲突的硬配额。",
            "强化无标点呼吸分行与意象精神尺度的可操作指引。",
        ],
        "fallback": True,
        "mock": bool(candidate.get("mock")),
    }


def analyze_candidate(llm, config, candidate, evaluation, selection):
    ref_texts = [p["text"] for p in selection["references"]]
    generated = _generated_poems(evaluation, ref_texts)
    if not generated:
        return _fallback(candidate, "父代没有产生可用作品，无法做真实差异分析；使用保守的本地回退建议。")
    payload = {
        "kind": "rpe_analyze_candidate",
        "reference_stylometry_summary": corpus_stylometry_summary(ref_texts),
        "reference_poems": anonymous_references(selection["references"]),
        "candidate_prompt": candidate["prompt"],
        "evaluation_digest": _evaluation_digest(evaluation),
        "generated_poems": generated,
        "analysis_dimensions": [
            "lexical", "syntax", "lineation", "imagery", "emotion", "structure",
            "mythic_register", "repetition", "prompt_instruction_quality", "topic_overreliance",
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
            cache_variant=f"{candidate['id']}:analysis:v3",
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
