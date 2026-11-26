"""Phase 3: deterministic metrics + anonymous LLM-judge evaluation."""
from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone

from . import metrics
from .corpus import anonymous_references
from .generator import generate_poem
from .llm import BudgetExhausted, LLMOutputError, is_output_truncation_error
from .validation import JUDGE_DIMENSIONS, STYLE_DIMENSIONS, validate_judge


JUDGE_SYSTEM = """你是匿名诗歌评审。你会看到：
1. 一组匿名参考诗，它们来自同一来源/风格；
2. 一首匿名生成诗；
3. 生成这首诗的题目、体裁与要求。

你不知道、也不应猜测生成提示词、候选编号、实验分组、作者身份或生成策略；不要评论这些内容。
你的任务是评估“生成诗在写作风格上与参考诗的接近程度”，而不是复述参考诗的内容。

评分维度（每项 0—5 分）：
- lexical：字词选择与语言习惯。具体名词/动词与抽象词的比例、虚词和口语/书面语习惯、词域是否相近。不要因为题材相同就给高分。
- syntax：句法结构与表达方式。短句/长句、跨行、排比、倒装、省略、问句、破折号、解释性从句的使用是否相近。
- lineation：分行、节奏及韵律。行数、行长分布、分节、行尾落点、重复、标点节奏、跨行停顿。参考作品是现代自由诗，不要求古典格律。
- imagery：意象组织与修辞手法。意象类型（自然/日常/身体/器物）、并置方式、重复呼告、比喻/拟人/通感，以及是否解释比喻。
- emotion：情感表达方式。抒情出现的位置、强度、是否直说、情感与场景动作的关系、克制或外放的程度。
- structure：语义组织与篇章结构。起承转合、空间/时间推进、视角变化、段落比例。
- progression：推进感与发展动力。全诗是否有某种力量在推动：动作、空间、时间、情感、意象关系或视角是否发生变化；后一节是否改变、加深或回应前一节，而不是并列堆叠。判断的是“诗在往前走”，不是叙事是否完整。
- concreteness：具象与抽象的比例。物象是否可触摸、是否用抽象名词承担抒情、具体细节的密度。
- repetition：复沓、呼告、回环、句法重复、关键词复现的位置与次数。
- addressivity：人称选择、呼告对象、我与世界/他者的关系。
- mythic_register：神话、历史、文化原型与日常经验的比例；是否用原型提升抒情。
- closure：结尾方式。具体物象、未完成疑问、格言/总结、回环等，以及结尾与全诗的关系。
- literary_quality：文学质量。语言新鲜度、意象准确度、节奏控制、完成度、是否陈词滥调。不要因为风格相似就提高质量分。
- topic_adherence：题意符合程度。是否回应题目、体裁和具体要求，是否跑题或只借题发挥。
- originality：原创性。是否避免复制参考诗的成句或连续长片段，是否有自己的语言组织。不是“越不像越好”，而是不抄袭、不套作。

评分锚点：
5 = 与参考高度一致/很强，证据充分；
4 = 明显一致/较好；
3 = 部分一致/中等，有可辨识差异；
2 = 略有相似/较弱，多为表层；
1 = 基本不同/很差；
0 = 文本缺失或完全无法评价（正常文本不要用 0）。

每个维度必须给出：
- score：0—5 的数值；
- evidence：至少一条来自生成诗的短引文（可加参考诗引文），不得编造；
- rationale：说明相同点和差异点；
- uncertainty：只能是英文 low / medium / high 之一。证据不足时必须标 high，不要假装确定。

输出格式硬性要求：
- 只输出一个 JSON 对象，不要 markdown，不要在对象前后添加解释。
- 顶层只能有 dimensions、overall_notes、confidence 三个键。
- dimensions 中每个维度键只出现一次；不要重复 dimensions，不要输出第二个 JSON 对象。
- evidence 最多 2 条，每条不超过 30 个汉字；rationale 不超过 80 个汉字。
- 不要用未转义的双引号包裹引文；引文直接写成字符串内容。

JSON 结构：
{"dimensions": {"lexical": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "syntax": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "lineation": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "imagery": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "emotion": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "structure": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "progression": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "concreteness": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "repetition": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "addressivity": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "mythic_register": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "closure": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "literary_quality": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "topic_adherence": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "originality": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}}, "overall_notes": "...", "confidence": "low|medium|high"}
"""


def _judge_payload(selection, topic, poem, config, kind="references"):
    return {
        "kind": "rpe_judge_poem",
        "rubric_version": config["evaluation"]["rubric_version"],
        "task": {
            "topic": topic["topic"],
            "genre": topic.get("genre") or config["generation"]["default_genre"],
            "requirements": topic.get("requirements", ""),
        },
        "reference_poems": anonymous_references(selection[kind]),
        "generated_poem": {
            "title": poem.get("title"),
            "lines": poem.get("raw_lines") or poem.get("lines") or [],
            "text": poem.get("text") or "\n".join(poem.get("lines") or []),
        },
    }


def _normalize_uncertainty(value):
    if not isinstance(value, str):
        return "high"
    text = value.strip().lower()
    if "high" in text or "高" in text:
        return "high"
    if "low" in text or "低" in text:
        return "low"
    if "medium" in text or "中" in text:
        return "medium"
    return "high"


def _normalize_judge(data):
    dimensions = {}
    for key in JUDGE_DIMENSIONS:
        item = data.get("dimensions", {}).get(key, {})
        dimensions[key] = {
            "score": float(item.get("score", 0)),
            "evidence": item.get("evidence") or [],
            "rationale": item.get("rationale", ""),
            "uncertainty": _normalize_uncertainty(item.get("uncertainty")),
        }
    return {
        "dimensions": dimensions,
        "overall_notes": data.get("overall_notes", ""),
        "confidence": data.get("confidence", "unknown"),
        "raw": data,
    }


def judge_poem(llm, config, selection, topic, poem, *, kind="references", cache_variant=None):
    payload = _judge_payload(selection, topic, poem, config, kind=kind)
    data, meta = llm.call_json(
        purpose="rpe_judge_poem",
        system=JUDGE_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False),
        max_tokens=config["evaluation"]["judge_max_tokens"],
        temperature=config["evaluation"]["judge_temperature"],
        thinking=config["evaluation"].get("judge_thinking"),
        validator=lambda value: validate_judge(value, config["evaluation"].get("judge_evidence_required", True)),
        cache_variant=cache_variant,
    )
    return _normalize_judge(data), meta


def _per_poem_fitness(config, deterministic, judge, form_ok, copy):
    ev = config["evaluation"]
    weights = ev.get("style_dimension_weights") or {key: 1.0 / len(STYLE_DIMENSIONS) for key in STYLE_DIMENSIONS}
    weight_total = sum(weights.get(key, 0.0) for key in STYLE_DIMENSIONS) or 1.0
    judge_style = sum(
        weights.get(key, 0.0) * judge["dimensions"][key]["score"] for key in STYLE_DIMENSIONS
    ) / weight_total * 20.0
    quality = judge["dimensions"]["literary_quality"]["score"] * 20.0
    topic = judge["dimensions"]["topic_adherence"]["score"]
    originality = judge["dimensions"]["originality"]["score"]
    style = (ev["deterministic_style_weight"] * deterministic["score"] +
             ev["judge_style_weight"] * judge_style)
    base = (1.0 - ev["quality_weight"]) * style + ev["quality_weight"] * quality
    penalty = 0.0
    if not form_ok:
        penalty += ev["form_penalty"]
    penalty += max(0.0, ev["topic_threshold"] - topic) * ev["topic_penalty_scale"]
    penalty += max(0.0, ev["originality_threshold"] - originality) * ev["originality_penalty_scale"]
    penalty += max(0.0, ev["quality_floor"] - judge["dimensions"]["literary_quality"]["score"]) * ev["quality_penalty_scale"]
    if copy["copy_flag"]:
        penalty += ev["copy_penalty"]
    fitness = max(0.0, min(100.0, base - penalty))
    high_uncertainty = [k for k, v in judge["dimensions"].items() if v["uncertainty"] == "high"]
    eligible = (
        form_ok and not copy["copy_flag"] and
        topic >= ev["topic_threshold"] and
        originality >= ev["originality_threshold"] and
        judge["dimensions"]["literary_quality"]["score"] >= ev["quality_floor"]
    )
    return {
        "fitness": round(fitness, 4),
        "eligible": bool(eligible),
        "base": round(base, 4),
        "penalty": round(penalty, 4),
        "style_score": round(style, 4),
        "deterministic_style_score": round(deterministic["score"], 4),
        "judge_style_score": round(judge_style, 4),
        "literary_quality_score": round(quality, 4),
        "literary_quality_raw": judge["dimensions"]["literary_quality"]["score"],
        "topic_adherence": topic,
        "originality": originality,
        "form_ok": bool(form_ok),
        "copy_flag": bool(copy["copy_flag"]),
        "high_uncertainty_dimensions": high_uncertainty,
    }


def evaluate_candidate(llm, config, candidate, topics, selection, *, judge_llm=None,
                       repetitions=None, repetition_offset=0, kind="references"):
    """Generate and evaluate a candidate on every supplied topic.

    ``kind`` selects the reference set.  Optimization always uses ``references``;
    final validation uses ``held_out``.
    """
    judge_llm = judge_llm or llm
    repetitions = int(repetitions if repetitions is not None else config["generation"]["repetitions"])
    ref_texts = [p["text"] for p in selection[kind]]
    evaluations = []
    for topic in topics:
        for rep in range(repetition_offset, repetition_offset + repetitions):
            cache_variant = f"{candidate['id']}:{topic['id']}:rep{rep}:{kind}"
            gen = generate_poem(llm, config, candidate["prompt"], topic, cache_variant=cache_variant)
            evaluation = {
                "topic_id": topic["id"],
                "topic": topic["topic"],
                "repetition": rep,
                "generation": gen,
                "ok": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "judge_model": getattr(judge_llm, "model", None),
                "rubric_version": config["evaluation"]["rubric_version"],
                "mock": bool(getattr(llm, "mock", False)),
            }
            if not gen["ok"]:
                evaluation["error"] = "生成失败"
                evaluations.append(evaluation)
                continue
            try:
                deterministic = metrics.style_similarity(gen["text"], ref_texts)
                copy = metrics.copy_diagnostics(
                    gen["text"], ref_texts,
                    lcs_chars=config["evaluation"]["copy_lcs_chars"],
                    line_chars=config["evaluation"]["copy_line_chars"],
                    rouge1_cap=config["evaluation"]["copy_rouge1_cap"],
                )
                rouge = [metrics.rouge1_char(gen["text"], ref) for ref in ref_texts]
                judge, judge_meta = judge_poem(
                    judge_llm, config, selection, topic, gen, kind=kind,
                    cache_variant=f"{candidate['id']}:{topic['id']}:rep{rep}:{kind}:judge:v2",
                )
                components = _per_poem_fitness(config, deterministic, judge, gen["form_ok"], copy)
                evaluation.update({
                    "ok": True,
                    "poem_id": hashlib.sha256(gen["text"].encode("utf-8")).hexdigest(),
                    "deterministic": deterministic,
                    "copy_diagnostics": copy,
                    "rouge1_diagnostic": {
                        "per_reference": rouge,
                        "mean_f1": round(statistics.mean(x["f1"] for x in rouge), 6),
                        "max_f1": round(max(x["f1"] for x in rouge), 6),
                        "note": "仅作文本重合诊断；不把高 ROUGE-1 当作风格模仿成功。",
                    },
                    "judge": judge,
                    "judge_meta": judge_meta,
                    "components": components,
                })
            except BudgetExhausted:
                raise
            except LLMOutputError as exc:
                evaluation["error"] = f"{type(exc).__name__}: {exc}"
            except RuntimeError as exc:
                if not is_output_truncation_error(exc):
                    raise
                evaluation["error"] = f"评审输出被截断：{exc}"
            except (ValueError, TypeError) as exc:
                evaluation["error"] = f"{type(exc).__name__}: {exc}"
            evaluations.append(evaluation)
    return aggregate_evaluations(candidate, evaluations, config)


def aggregate_evaluations(candidate, evaluations, config):
    ok = [row for row in evaluations if row.get("ok")]
    aggregate = {
        "candidate_id": candidate["id"],
        "evaluations": evaluations,
        "evaluation_count": len(evaluations),
        "successful_evaluations": len(ok),
        "failed_evaluations": len(evaluations) - len(ok),
        "fitness": None,
        "eligible": False,
        "style_score": None,
        "literary_quality_score": None,
        "topic_adherence": None,
        "originality": None,
        "form_ok_rate": 0.0,
        "copy_rate": 0.0,
        "score_std": None,
        "aggregation": "mean of per-poem fitness; failed generations penalized; eligibility requires form, non-copy, topic, originality and quality floors",
    }
    if not ok:
        return aggregate
    values = [row["components"]["fitness"] for row in ok]
    aggregate.update({
        "fitness": round(statistics.mean(values), 4),
        "style_score": round(statistics.mean(row["components"]["style_score"] for row in ok), 4),
        "deterministic_style_score": round(statistics.mean(row["components"]["deterministic_style_score"] for row in ok), 4),
        "judge_style_score": round(statistics.mean(row["components"]["judge_style_score"] for row in ok), 4),
        "literary_quality_score": round(statistics.mean(row["components"]["literary_quality_score"] for row in ok), 4),
        "topic_adherence": round(statistics.mean(row["components"]["topic_adherence"] for row in ok), 4),
        "originality": round(statistics.mean(row["components"]["originality"] for row in ok), 4),
        "form_ok_rate": round(sum(1 for row in ok if row["components"]["form_ok"]) / len(evaluations), 6),
        "copy_rate": round(sum(1 for row in ok if row["components"]["copy_flag"]) / len(evaluations), 6),
        "score_std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
        "mean_rouge1_f1": round(statistics.mean(row["rouge1_diagnostic"]["mean_f1"] for row in ok), 6),
    })
    fail_rate = (len(evaluations) - len(ok)) / len(evaluations) if evaluations else 1.0
    if fail_rate:
        aggregate["fitness"] = round(max(0.0, aggregate["fitness"] - 25.0 * fail_rate), 4)
    aggregate["eligible"] = (
        len(ok) == len(evaluations) and
        all(row["components"]["eligible"] for row in ok)
    )
    return aggregate
