"""Phase 3: deterministic metrics + anonymous LLM-judge evaluation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import statistics
from datetime import datetime, timezone

from . import metrics
from .corpus import anonymous_references
from .generator import generate_poem
from .llm import BudgetExhausted, LLMOutputError, is_output_truncation_error
from .validation import JUDGE_DIMENSIONS, STYLE_DIMENSIONS, validate_judge


JUDGE_SYSTEM = """你是匿名现代诗比较诗学评审。你会看到：
1. 一组匿名参考诗（来自同一诗人语料）；
2. 一首在全新题目下独立生成的匿名诗；
3. 生成这首诗的题目、体裁与格式要求。

你不知道、也不应猜测生成提示词、候选编号、实验分组、作者身份或生成策略；不要评论这些内容。
你的任务是严格评估“生成诗在深层写作风格、语言呼吸与诗学气度上与参考诗的接近程度”，同时识破机械按规则拼装的套路稿。

评分维度（每项 0—5 分，可使用 0.5 分档，如 2.5、3.5、4.5）：
- lexical：字词选择与语言肌理。高频核心实词的质朴度与重量感、动词力度、虚词节奏与书面/口语平衡是否接近参考诗。若只会堆砌琐碎工业零件词而缺乏参考诗的纯度，不超过 2.5。
- syntax：句法结构与表达方式。直接命名/判断句、短主谓句、省略、倒装、排比与跨行衔接是否自然接近参考诗，而非散文交代句或机械填空句。
- lineation：分行、节奏及呼吸。长短行落差、无标点断行、行内停顿、行尾落点是否形成真实呼吸。若每行末尾机械加逗号/句号呈分行散文状，不超过 2.5。
- imagery：意象组织与并置张力。日常现场物象是否能与大地、黑夜、水火、天象、身体等具有重量的物象发生真实碰撞与变形，而非静态罗列清单或每节贴一个廉价明喻。
- emotion：情感表达姿态。抒情是否兼具参考诗特有的赤诚/痛感与具体承载（可在动作与物象中直陈或呼告，不靠矫情形容词，也不流于干瘪冷漠的技术清点）。
- structure：语义组织与篇章结构。节与节之间的起承、跳接、回环或视角打开是否接近参考诗。
- progression：推进感与发展动力（单列诊断）。全诗是否有内在力量推动后一节加深或改变前一节，而非原地并列堆叠或机械按空间方位报流水账。
- concreteness：具象与抽象的张力。具象物是否可触可感，抽象/存在性词汇出现时是否有具体物象或生命处境支撑。
- repetition：复沓、呼告与变奏回环。复现短语、词根或呼告时是否随语境改变语义重量或句法位置。若多节首行死板照抄同一填空模板（如每节硬套“XX，XX，你……”），判为机械复沓，不超过 2.0。
- addressivity：人称选择、说话位置、呼告对象及“我”与世界/他者的关系尺度。
- mythic_register：元素尺度与精神高度。面对具体日常题目时，能否自然打开时间纵深、原初自然元素或存在/生命高度，而非困在狭隘琐碎的事务描写里。
- closure：结尾方式。末行是否自然承接全诗建立的关系并留有余响，避免空洞格言升华或生硬明喻封死。
- literary_quality：独立文学质量。语言准确度、声气连贯度、意象新鲜度与整体感染力。像“按清单拼装的规则练习作”不得高于 2.5；不要因题材讨巧虚抬分数。
- topic_adherence：题意符合程度。是否准确回应题目核心场景与具体要求。
- originality：原创性。是否避免照搬参考诗原句、专有名词或标志性成句组合，形成独立成篇的诗作。

评分锚点：
5.0 = 声口、呼吸与意象气度高度神似，浑然成篇，证据充分；
4.0 = 多处核心特征明显一致，语言自然，偶有局部差距；
3.0 = 部分表层特征相近，但整体声口偏普通现代诗或局部略显刻意；
2.0 = 仅有零星表层模仿，或明显流于机械模板/分行散文；
1.0 = 风格完全相悖或严重失控；
0.0 = 文本缺失或完全无法评价（正常文本不用 0）。

每个维度必须给出：
- score：0—5 的数值（支持 0.5 步长）；
- evidence：1—2 条来自生成诗的短引文（不得编造）；
- rationale：简明指出相同点与关键差距（不超过 70 个汉字）；
- uncertainty：只能是 low / medium / high 之一。

输出格式硬性要求：
- 只输出一个合法 JSON 对象，不要 markdown，不要解释。
- 顶层只能有 dimensions、overall_notes、confidence 三个键。
- 不要在字符串内部使用未转义的英文双引号。

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
    """Generate and evaluate a candidate on every supplied topic."""
    judge_llm = judge_llm or llm
    repetitions = int(repetitions if repetitions is not None else config["generation"]["repetitions"])
    ref_texts = [p["text"] for p in selection[kind]]
    copy_texts = list(ref_texts)
    if kind == "held_out":
        copy_texts.extend(p["text"] for p in selection["references"])
    rubric_tag = config["evaluation"].get("rubric_version", "v2")
    jobs = [
        (topic, rep)
        for topic in topics
        for rep in range(repetition_offset, repetition_offset + repetitions)
    ]

    def _run_one(job):
        topic, rep = job
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
            "rubric_version": rubric_tag,
            "mock": bool(getattr(llm, "mock", False)),
        }
        if not gen["ok"]:
            evaluation["error"] = "生成失败"
            return evaluation
        try:
            deterministic = metrics.style_similarity(gen["text"], ref_texts)
            copy = metrics.copy_diagnostics(
                gen["text"], copy_texts,
                lcs_chars=config["evaluation"]["copy_lcs_chars"],
                line_chars=config["evaluation"]["copy_line_chars"],
                rouge1_cap=config["evaluation"]["copy_rouge1_cap"],
            )
            copy["reference_sets"] = [kind, "references"] if kind == "held_out" else [kind]
            rouge = [metrics.rouge1_char(gen["text"], ref) for ref in ref_texts]
            judge, judge_meta = judge_poem(
                judge_llm, config, selection, topic, gen, kind=kind,
                cache_variant=f"{candidate['id']}:{topic['id']}:rep{rep}:{kind}:judge:{rubric_tag}",
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
        return evaluation

    is_mock = bool(getattr(llm, "mock", True))
    if is_mock or len(jobs) <= 1 or not hasattr(llm, "call_json"):
        evaluations = [_run_one(job) for job in jobs]
    else:
        workers = min(6, len(jobs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            evaluations = list(pool.map(_run_one, jobs))
    return aggregate_evaluations(candidate, evaluations, config)


def selection_objective(result):
    """Compare pass rates, then mean style score on passing poems."""
    style = result.get("eligible_style")
    return result.get("eligible_rate", 0.0), style if style is not None else -1.0


def aggregate_evaluations(candidate, evaluations, config):
    ok = [row for row in evaluations if row.get("ok")]
    eligible_styles = [row["components"]["style_score"] for row in ok if row["components"]["eligible"]]
    aggregate = {
        "eligible_count": len(eligible_styles),
        "eligible_rate": len(eligible_styles) / len(evaluations) if evaluations else 0.0,
        "eligible_style": round(statistics.mean(eligible_styles), 4) if eligible_styles else None,
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
        "aggregation": "rank by eligible rate over all attempts, then mean style on eligible poems; fitness is a tiebreaker",
    }
    if not ok:
        return aggregate
    values = [row["components"]["fitness"] for row in ok]
    score_std = round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0
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
        "score_std": score_std,
        "mean_rouge1_f1": round(statistics.mean(row["rouge1_diagnostic"]["mean_f1"] for row in ok), 6),
    })
    fail_rate = (len(evaluations) - len(ok)) / len(evaluations) if evaluations else 1.0
    if fail_rate:
        aggregate["fitness"] = round(max(0.0, aggregate["fitness"] - 25.0 * fail_rate), 4)
    if len(values) > 1 and score_std > 0:
        aggregate["fitness"] = round(max(0.0, aggregate["fitness"] - 0.12 * score_std), 4)
    ev = config["evaluation"]
    prompt_len = len(candidate.get("prompt", ""))
    over = max(0, prompt_len - int(ev.get("prompt_length_free", 0)))
    length_penalty = min(
        float(ev.get("prompt_length_penalty_max", 0.0)),
        over / 100.0 * float(ev.get("prompt_length_penalty_per_100_chars", 0.0)),
    )
    aggregate["prompt_length_chars"] = prompt_len
    aggregate["prompt_length_penalty"] = round(length_penalty, 4)
    if length_penalty:
        aggregate["fitness"] = round(max(0.0, aggregate["fitness"] - length_penalty), 4)
    aggregate["eligible"] = (
        len(ok) == len(evaluations) and
        all(row["components"]["eligible"] for row in ok)
    )
    return aggregate
