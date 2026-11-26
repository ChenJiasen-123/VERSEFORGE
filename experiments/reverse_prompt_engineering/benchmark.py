"""Phase 7: independent benchmark against two baselines.

Group A: directly ask the model to imitate the named poet.
Group B: one-shot reverse-engineered prompt from the reference set.
Group C: RPE-GA optimized prompt.

Test topics and held-out reference poems are never used to mutate any prompt.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .evaluator import aggregate_evaluations, evaluate_candidate
from .initializer import reverse_once
from .metrics import han_only, reference_diversity


GROUP_LABELS = {
    "A": "Baseline A：直接要求模仿目标诗人",
    "B": "Baseline B：阅读参考作品后一次性反推 Prompt",
    "C": "Experimental C：RPE-GA 迭代优化 Prompt",
}


def _usage_snapshot(llm):
    summary = llm.budget.summary()
    return {
        "calls": summary["calls"],
        "input_tokens": summary["input_tokens"],
        "output_tokens": summary["output_tokens"],
        "total_tokens": summary["total_tokens"],
        "cache_hits": summary["cache_hits"],
        "estimated_cost": summary["estimated_cost"],
    }


def _usage_delta(before, after):
    delta = {}
    for key in before:
        if isinstance(before[key], (int, float)) and isinstance(after[key], (int, float)):
            delta[key] = round(after[key] - before[key], 6)
        else:
            delta[key] = after[key]
    return delta


def _sanitize_reverse_prompt(prompt, selection):
    """Remove verbatim reference lines from a one-shot baseline prompt.

    Baseline B is allowed to fail on its own merits, but generation must not
    receive a verbatim reference line.  We replace only exact full lines and
    the poet name; the rest of the one-shot prompt is retained and the
    intervention is recorded.
    """
    changes = []
    for index, ref in enumerate(selection["references"], 1):
        for line in ref["text"].splitlines():
            text = line.strip()
            if len(han_only(text)) >= 8 and text in prompt:
                replacement = "用概括性的语言描述这一层意思"
                prompt = prompt.replace(text, replacement)
                changes.append({"reference": index, "line": text, "replacement": replacement})
    names = [selection.get("target_name")] + list(selection.get("target_aliases") or [])
    for name in names:
        if name and name in prompt:
            prompt = prompt.replace(name, "某位诗人")
            changes.append({"name": name, "replacement": "某位诗人"})
    return prompt, changes


def _group_result(label, prompt, aggregate, usage, prompt_records):
    return {
        "label": label,
        "prompt": prompt,
        "prompt_records": prompt_records,
        "aggregate": {
            "fitness": aggregate.get("fitness"),
            "eligible": aggregate.get("eligible"),
            "style_score": aggregate.get("style_score"),
            "deterministic_style_score": aggregate.get("deterministic_style_score"),
            "judge_style_score": aggregate.get("judge_style_score"),
            "literary_quality_score": aggregate.get("literary_quality_score"),
            "topic_adherence": aggregate.get("topic_adherence"),
            "originality": aggregate.get("originality"),
            "form_ok_rate": aggregate.get("form_ok_rate"),
            "copy_rate": aggregate.get("copy_rate"),
            "score_std": aggregate.get("score_std"),
            "evaluation_count": aggregate.get("evaluation_count"),
            "successful_evaluations": aggregate.get("successful_evaluations"),
            "failed_evaluations": aggregate.get("failed_evaluations"),
            "mean_rouge1_f1": aggregate.get("mean_rouge1_f1"),
        },
        "usage": usage,
        "evaluations": aggregate.get("evaluations", []),
    }


def run_benchmark(*, config, selection, test_topics, best_prompt, llm, judge_llm=None,
                  store=None, state=None):
    """Run A/B/C on the same held-out references and the same test topics."""
    judge_llm = judge_llm or llm
    if not best_prompt:
        raise ValueError("没有可用的 RPE-GA 最优 Prompt，无法运行 C 组")
    before_all = _usage_snapshot(llm)
    results = {}
    topics_by_group = {}

    # Baseline A: per-topic direct imitation instruction.
    before = _usage_snapshot(llm)
    a_evaluations = []
    a_prompts = {}
    for topic in test_topics:
        prompt = config["benchmark"]["baseline_a_prompt"].format(
            target_name=selection["target_name"],
            topic=topic["topic"],
            requirements=topic.get("requirements", ""),
        )
        a_prompts[topic["id"]] = prompt
        candidate = {"id": f"bench-A-{topic['id']}", "prompt": prompt}
        evaluation = evaluate_candidate(
            llm, config, candidate, [topic], selection, judge_llm=judge_llm,
            repetitions=config["benchmark"]["repetitions"], kind="held_out",
        )
        a_evaluations.extend(evaluation.get("evaluations", []))
        if store:
            store.write_json(f"benchmark/evaluations/A-{topic['id']}.json", evaluation)
    a_aggregate = aggregate_evaluations({"id": "benchmark-A"}, a_evaluations, config)
    results["A"] = _group_result(
        GROUP_LABELS["A"], a_prompts, a_aggregate, _usage_delta(before, _usage_snapshot(llm)),
        [{"topic_id": k, "prompt": v} for k, v in a_prompts.items()],
    )
    topics_by_group["A"] = list(a_prompts)

    # Baseline B: one-shot reverse prompt from training references.
    before = _usage_snapshot(llm)
    reverse = reverse_once(llm, config, selection)
    reverse_errors = (reverse.get("validation") or {}).get("errors", [])
    contamination = [e for e in reverse_errors if ("姓名" in e or "完整诗句" in e or "连续重合" in e)]
    b_prompt, reverse_sanitized = _sanitize_reverse_prompt(reverse.get("prompt", ""), selection)
    if b_prompt:
        b_candidate = {"id": "bench-B", "prompt": b_prompt}
        b_evaluation = evaluate_candidate(
            llm, config, b_candidate, test_topics, selection, judge_llm=judge_llm,
            repetitions=config["benchmark"]["repetitions"], kind="held_out",
        )
    else:
        b_evaluation = aggregate_evaluations({"id": "bench-B"}, [], config)
    b_aggregate = aggregate_evaluations({"id": "benchmark-B"}, b_evaluation.get("evaluations", []), config)
    results["B"] = _group_result(
        GROUP_LABELS["B"], b_prompt, b_aggregate, _usage_delta(before, _usage_snapshot(llm)),
        [reverse],
    )
    results["B"]["reverse_validation"] = reverse.get("validation")
    results["B"]["reverse_contamination"] = contamination
    results["B"]["reverse_sanitized"] = reverse_sanitized
    topics_by_group["B"] = [t["id"] for t in test_topics]

    # Experimental C.
    before = _usage_snapshot(llm)
    c_candidate = {"id": "bench-C", "prompt": best_prompt}
    c_evaluation = evaluate_candidate(
        llm, config, c_candidate, test_topics, selection, judge_llm=judge_llm,
        repetitions=config["benchmark"]["repetitions"], kind="held_out",
    )
    c_aggregate = aggregate_evaluations({"id": "benchmark-C"}, c_evaluation.get("evaluations", []), config)
    results["C"] = _group_result(
        GROUP_LABELS["C"], best_prompt, c_aggregate, _usage_delta(before, _usage_snapshot(llm)),
        [{"prompt": best_prompt, "origin": "rpe_ga_best"}],
    )
    topics_by_group["C"] = [t["id"] for t in test_topics]

    after_all = _usage_snapshot(llm)
    metric_names = ["style_score", "literary_quality_score", "topic_adherence", "originality", "fitness"]
    comparisons = {}
    for base in ("A", "B"):
        comparisons[f"C_minus_{base}"] = {
            name: (
                round(results["C"]["aggregate"][name] - results[base]["aggregate"][name], 4)
                if results["C"]["aggregate"].get(name) is not None and results[base]["aggregate"].get(name) is not None
                else None
            )
            for name in metric_names
        }
    ranked = sorted(
        (key for key in results if results[key]["aggregate"]["style_score"] is not None),
        key=lambda key: results[key]["aggregate"]["style_score"], reverse=True,
    )
    report = {
        "schema_version": "rpe-benchmark-zh-v1",
        "is_mock": bool(getattr(llm, "mock", False)),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "test_topics": test_topics,
        "topics_by_group": topics_by_group,
        "validation_references": selection["held_out"],
        "validation_reference_diversity": reference_diversity([p["text"] for p in selection["held_out"]]),
        "groups": results,
        "comparison": comparisons,
        "ranking_by_style_score": ranked,
        "usage_total": _usage_delta(before_all, after_all),
        "fairness": {
            "same_test_topics": True,
            "same_reference_set": "held_out",
            "same_generation_parameters_within_group": True,
            "judge_sees_prompt_or_group": False,
            "prompts_mutated_after_test": False,
            "note": "A 组按题目生成模仿指令；B/C 使用固定 Prompt。三组均使用相同题目、参考集、生成参数和评审 rubric。",
        },
        "limitations": [
            "样本量小，单次运行不能证明统计显著性或普遍优越性。",
            "评委可能与被生成模型同家族；即使匿名和独立调用，仍存在自评偏差。",
            "风格相似度是特征与 LLM 评审的代理指标，不等于人类读者对‘像’的判断。",
        ] + ([
            "Mock 运行的分数与作品是模拟数据，不能用于研究结论。",
        ] if getattr(llm, "mock", False) else []),
    }
    if state is not None:
        state["benchmark"] = {
            key: report[key] for key in ("ranking_by_style_score", "comparison", "usage_total", "fairness", "limitations")
        }
        state["benchmark"]["details_path"] = "benchmark/benchmark.json"
    if store:
        store.write_json("benchmark/benchmark.json", report)
    return report
