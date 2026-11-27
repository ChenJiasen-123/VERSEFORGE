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
from .validation import JUDGE_DIMENSIONS, STYLE_DIMENSIONS, validate_judge, validate_pairwise_judge


UNCERTAINTY_WEIGHT_FACTORS = {
    "low": 1.00,
    "medium": 0.95,
    "high": 0.80,
}

JUDGE_SYSTEM = """你是匿名现代诗比较诗学评审。你会看到：
1. 一组匿名参考诗（来自同一诗人语料）；
2. 一首在全新题目下独立生成的匿名诗；
3. 生成这首诗的题目、体裁与格式要求。

你不知道、也不应猜测生成提示词、候选编号、实验分组、作者身份或生成策略；不要评论这些内容。
你的任务是严格评估“生成诗在深层写作风格、语言呼吸、身体与元素重力及纵向推进上与参考诗的接近程度”，同时识破机械按规则拼装的套路稿。

评分维度（每项 0—5 分，支持 0.25 细粒度分档，如 2.5、2.75、3.0、3.25、3.5、3.75、4.0、4.25、4.5）：
- poetic_core：诗核凝聚与刺破力（第一核心维度）。全诗是否像参考诗那样立在一颗唯一、偏执、不可替换的“诗核”（一个反常的生存悖论、刺痛发现或本体决断）上，让每一节都像锤子砸向同一颗钉子般围绕同一主意象轴掘进，并在中后段完成不可逆的破壁一击或认知翻转。若各节各自换一套漂亮比喻（散珠无绳）、四节绕着器物同心圆平铺巡礼、为凑深情凭空塞入无来历的“你”，或结尾用“轻轻合上/放进抽屉/弯腰捡起”安全退场而无核心震动，一律不超过 2.50。
- lexical：字词选择与语言肌理。基础高频实词的质朴度与重量感、身体与原初自然词的纯度、动词骨力是否接近参考诗。若只会堆砌琐碎零件词或混入“蛋黄/治愈/烟火”等小清新网文熟词，不超过 2.5。
- syntax：句法结构与表达方式。本体论直接判断命名句（“X 是 Y”）、陡峭短主谓句与跨行张力是否自然接近参考诗。若滑向行内加逗号的日常口语叙事句（“我说有，其实……”）或频繁贴“像/仿佛”明喻，不超过 2.5。
- lineation：分行、节奏及刀锋呼吸。长句奔涌与三五字陡峭短行的悬殊落差、无标点断行、偶发克制的行内空格顿挫是否形成冷峻骨力。若每行加逗号/句号呈散文分句，或超半数行机械劈成两截电报体、行长均齐平板，不超过 2.5。
- imagery：意象主轴与变形张力。全诗是否死死咬住 1—2 个主导物象将它推向变形与极境，而非每节换一个互不咬合的装饰性喻体。
- emotion：情感重力与决断温度。痛感、眷恋或孤绝是否从全诗唯一的“诗核”悖论中剧烈刺出（既有具身重力，又有关键处毫不闪躲的直白决断），既不流于冷漠清点，也不流于温吞口语煽情。
- structure：语义组织与篇章结构。节与节之间是否构成围绕同一诗核的蓄势—加码—破壁—回响，而非四块可随意调换顺序的平行切片。
- progression：纵向掘进力。后一节是否把同一诗核挖得更深、更痛或推向更大生命尺度；若只是水平换角度描摹同一物件，不超过 2.5。
- concreteness：具象与命题的咬合度。具体动作与核心生存命题是否锁死为一体，而非外贴“肋骨/地心”空壳。
- repetition：主核复沓与变奏加码。核心意象或执念短语跨节回返时是否逐次加重分量，禁止三节以上句首同词机械填空克隆（克隆不超过 2.25）。
- addressivity：发话位置的必然性。有人际对象时真切直呼；纯独处或器物现场可坚持冷峻第一人称直视。若在无人物铺垫的诗里强行虚构泛指的“你”（如凭空数“你”的指纹、发给“你”）凑深情，判为虚假呼告，不超过 2.50。
- mythic_register：原初元素与存在尺度。能否从核心悖论内部自然撕开黑夜、大地、生死或时间的纵深，而非生硬外贴大词。
- closure：收束的骨力与余震。结尾是否把全诗诗核钉死在最重或最锋利的一笔（如陡峭的本体断语、悖论落定或未闭合的回响），严禁千篇一律用“轻轻合上门/放进抽屉/锁车门/弯腰数完”温顺退场（套路轻放不超过 2.75）。
- literary_quality：独立文学质量。是否有让人读后心头一震、过目不忘的核心诗句与整体浑成度。“句句精致但读完无核的练习作”或“温吞散文化口水诗”均不得高于 2.75。
- topic_adherence：题意符合程度。是否准确回应题目核心处境与格式要求。
- originality：原创性。是否避免照搬参考诗原句、专有名词或陈旧比喻套路。

高分辨率评分锚点（重点拉开 3.0—4.0 密集区，拒绝笼统给分）：
5.00 = 声口、呼吸、身体重力与纵向推进高度神似，浑然天成；
4.25—4.50 = 核心特征鲜明契合，痛感与呼吸自然贯通，几无匠气；
4.00 = 多处核心特征明显一致，语言峭拔自然，偶有极细微松动；
3.75 = 大部分段落声口炽热、尺度打开，仅个别句稍显常规；
3.50 = 呼吸与物象碰撞基本成立，接近参考诗气度，但纵向推进或痛感尚差半口气；
3.25 = 表层断行与词域合格，局部有亮句，但整体偏稳或略显工整；
3.00 = 仅部分表层特征相近，整体声口偏普通现代诗或隐约可见规则痕迹；
2.50—2.75 = 明显带有按规则造句痕迹、节奏平直或尺度局促；
2.00 = 仅有零星模仿，或流于机械节首模板/分行散文；
1.00 = 风格完全相悖或严重失控；0.00 = 文本缺失。

每个维度必须给出：
- score：0—5 的数值（支持 0.25 步长）；
- evidence：1—2 条来自生成诗的短引文（不得编造）；
- rationale：简明指出相同点与关键差距（不超过 70 个汉字）；
- uncertainty：只能是 low / medium / high 之一。

输出格式硬性要求：
- 只输出一个合法 JSON 对象，不要 markdown，不要解释。
- 顶层只能有 dimensions、overall_notes、confidence 三个键。
- 不要在字符串内部使用未转义的英文双引号。

JSON 结构：
{"dimensions": {"poetic_core": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "lexical": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "syntax": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "lineation": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "imagery": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "emotion": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "structure": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "progression": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "concreteness": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "repetition": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "addressivity": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "mythic_register": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "closure": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "literary_quality": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "topic_adherence": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}, "originality": {"score": 0, "evidence": ["..."], "rationale": "...", "uncertainty": "low"}}, "overall_notes": "...", "confidence": "low|medium|high"}
"""

PAIRWISE_JUDGE_SYSTEM = """你是匿名现代诗双盲比较评审。你会看到：
1. 一组来自同一诗人的匿名参考诗；
2. 同一道现代诗题目下独立生成的两首匿名诗（作品 1 与 作品 2）。

你不知道它们的生成提示词或顺序含义，也不得偏袒排在前面或后面的作品。
请按以下优先级严格裁定哪一首更接近参考诗的深层魂魄且是一首真正立得住的好诗：
1. 首看“诗核凝聚与刺破力”：哪一首拥有唯一、锋利、一竿子插到底的核心悖论/中心主象并在中后段完成破壁一击（淘汰每节换一套“像……”散珠比喻、四节平铺巡礼、凭空生造虚假“你”以及结尾“轻轻合上/放进抽屉”温顺退场的空心作）；
2. 次看“刀锋骨力与呼吸”：哪一首同时保住了无散文逗号的陡峭断行、长短句悬殊张力与重物象本体命名（淘汰加逗号的日常口语流水句与小清新熟喻）。
- 若作品 1 明显或稳定更胜出，winner 填 "1"；
- 若作品 2 明显或稳定更胜出，winner 填 "2"；
- 若两者难分高下或各有明显硬伤，winner 填 "tie"。

只输出合法 JSON 对象，不要 markdown：
{"winner": "1|2|tie", "confidence": "low|medium|high", "evidence_1": "作品1短引文", "evidence_2": "作品2短引文", "rationale": "不超过80字的关键差异对比"}
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
    effective_weights = {}
    for key in STYLE_DIMENSIONS:
        base_w = float(weights.get(key, 0.0))
        unc = judge["dimensions"][key].get("uncertainty", "medium")
        effective_weights[key] = base_w * UNCERTAINTY_WEIGHT_FACTORS.get(unc, 0.90)
    weight_total = sum(effective_weights.values()) or 1.0
    judge_style = sum(
        effective_weights[key] * judge["dimensions"][key]["score"] for key in STYLE_DIMENSIONS
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
    """Compare pass rates, then mean style score (+ symmetric pairwise tiebreak if any)."""
    style = result.get("eligible_style")
    if style is None:
        return result.get("eligible_rate", 0.0), -1.0
    bonus = float(result.get("pairwise_tiebreak_bonus") or 0.0)
    return result.get("eligible_rate", 0.0), round(float(style) + bonus, 4)


def pairwise_compare_candidates(judge_llm, config, cand_a, cand_b, selection, *, kind="references"):
    """Position-swapped symmetric pairwise comparison (AB + BA) on shared-topic poems.

    Eliminates LLM position bias: a topic-rep pair counts as a win ONLY if both
    presentation orders (A vs B and B vs A) select the same poem.  Order flips
    are recorded as position-bias neutral ties (0.5 : 0.5), introducing zero
    random directional noise.
    """
    evals_a = {
        (row["topic_id"], row["repetition"]): row
        for row in (cand_a.get("evaluation") or {}).get("evaluations", [])
        if row.get("ok") and row.get("components", {}).get("eligible")
    }
    evals_b = {
        (row["topic_id"], row["repetition"]): row
        for row in (cand_b.get("evaluation") or {}).get("evaluations", [])
        if row.get("ok") and row.get("components", {}).get("eligible")
    }
    max_pairs = int(config["evaluation"].get("pairwise_max_pairs", 7))
    shared_keys = sorted(evals_a.keys() & evals_b.keys())[:max_pairs]
    if not shared_keys:
        return {
            "candidate_a": cand_a["id"],
            "candidate_b": cand_b["id"],
            "pairs_compared": 0,
            "consistent_wins_a": 0,
            "consistent_wins_b": 0,
            "ties_or_order_flips": 0,
            "order_flips": 0,
            "net_rate_a": 0.5,
            "bonus_a": 0.0,
            "details": [],
        }

    refs = anonymous_references(selection[kind])
    rubric_tag = config["evaluation"].get("rubric_version", "v3")

    def _call_one_direction(key, first_id, first_row, second_id, second_row):
        gen1 = first_row["generation"]
        gen2 = second_row["generation"]
        if (gen1.get("text") or "").strip() == (gen2.get("text") or "").strip():
            return {"winner": "tie", "confidence": "high", "rationale": "两首诗文本完全一致"}, {}
        payload = {
            "kind": "rpe_pairwise_poem",
            "rubric_version": rubric_tag,
            "topic": first_row.get("topic", ""),
            "reference_poems": refs,
            "poem_1": {"title": gen1.get("title"), "text": gen1.get("text", "")},
            "poem_2": {"title": gen2.get("title"), "text": gen2.get("text", "")},
        }
        data, meta = judge_llm.call_json(
            purpose="rpe_pairwise_poem",
            system=PAIRWISE_JUDGE_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=900,
            temperature=0.0,
            thinking=config["evaluation"].get("judge_thinking"),
            validator=validate_pairwise_judge,
            cache_variant=f"pw:{first_id}:vs:{second_id}:{key[0]}:rep{key[1]}:{kind}:{rubric_tag}",
        )
        return data, meta

    tasks = []
    for key in shared_keys:
        tasks.append((key, "AB", cand_a["id"], evals_a[key], cand_b["id"], evals_b[key]))
        tasks.append((key, "BA", cand_b["id"], evals_b[key], cand_a["id"], evals_a[key]))

    def _exec(task):
        key, direction, id1, r1, id2, r2 = task
        try:
            data, _ = _call_one_direction(key, id1, r1, id2, r2)
            return key, direction, str(data.get("winner", "tie")).strip().lower(), data.get("rationale", "")
        except BudgetExhausted:
            raise
        except Exception as exc:
            return key, direction, "tie", f"fallback_tie: {exc}"

    is_mock = bool(getattr(judge_llm, "mock", True))
    if is_mock or len(tasks) <= 1:
        raw_out = [_exec(t) for t in tasks]
    else:
        with ThreadPoolExecutor(max_workers=min(6, len(tasks))) as pool:
            raw_out = list(pool.map(_exec, tasks))

    by_key = {}
    for key, direction, winner, rationale in raw_out:
        by_key.setdefault(key, {})[direction] = (winner, rationale)

    wins_a = wins_b = ties = flips = 0
    details = []
    for key in shared_keys:
        ab_win, ab_rat = by_key[key].get("AB", ("tie", ""))
        ba_win, ba_rat = by_key[key].get("BA", ("tie", ""))
        if ab_win == "1" and ba_win == "2":
            verdict = "A"
            wins_a += 1
        elif ab_win == "2" and ba_win == "1":
            verdict = "B"
            wins_b += 1
        else:
            verdict = "tie"
            ties += 1
            if ab_win in ("1", "2") and ba_win in ("1", "2") and ab_win == ba_win:
                flips += 1
        details.append({
            "topic_id": key[0],
            "repetition": key[1],
            "ab_winner": ab_win,
            "ba_winner": ba_win,
            "symmetric_verdict": verdict,
            "rationale_ab": ab_rat,
            "rationale_ba": ba_rat,
        })

    n = len(shared_keys)
    points_a = wins_a + 0.5 * ties
    net_rate_a = points_a / n if n else 0.5
    max_bonus = float(config["evaluation"].get("pairwise_bonus_cap", 1.2))
    bonus_a = round(max(-max_bonus, min(max_bonus, (net_rate_a - 0.5) * 2.0 * max_bonus)), 4)
    return {
        "candidate_a": cand_a["id"],
        "candidate_b": cand_b["id"],
        "pairs_compared": n,
        "consistent_wins_a": wins_a,
        "consistent_wins_b": wins_b,
        "ties_or_order_flips": ties,
        "order_flips": flips,
        "net_rate_a": round(net_rate_a, 4),
        "bonus_a": bonus_a,
        "details": details,
    }


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
