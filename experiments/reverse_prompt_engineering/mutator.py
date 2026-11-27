"""Phase 5: targeted prompt mutation + elite semantic crossover.

All optimization acts strictly on the natural-language Style Prompt, never by
editing generated poems directly.
"""
from __future__ import annotations

import json
import statistics

from .validation import STYLE_DIMENSIONS, validate_crossover, validate_mutation, validate_prompt


MUTATION_STRATEGIES = (
    (
        "forge_single_core",
        "锻造唯一诗核与破壁翻转：要求落笔前先从题目抓出一个唯一的反常悖论或刺痛真相作为全诗‘诗核’，全诗只沿同一根主导物象轴一竿子插到底（严禁每节换一套互不相干的‘像……’散珠比喻），并在中后段完成一次不可逆的破壁决断，彻底改掉四节平铺巡礼最后‘轻轻合上/放进抽屉’安全退场的空心结构。",
    ),
    (
        "sculptural_edge_no_prose",
        "锁死刀锋骨力并禁绝散文逗号与贴喻：完整保住冷峻陡峭的句法肌肉——严禁行内加逗号的日常口语流水句，严禁‘像/仿佛/如同’贴喻，全部改用‘X是Y’本体重命名与重物硬撞；行末不落标点，行内仅在关键折断处偶留空格（不逐行劈半），拉开跨行长句与二至四字短行的剧烈落差。",
    ),
    (
        "prune_fake_vocative_and_templates",
        "剔除虚假呼告与收尾套路并精炼减重：取消‘不管什么题都强行造一个模糊的你来呼告’和‘前两行固定模板/末行弯腰摸冷物’的套路——有人际对象才直呼其人，独处或器物现场便以第一人称冷峻直逼命题核心；将规则精炼在 5—6 条（300—540字）。",
    ),
)

MUTATOR_SYSTEM = """你是“风格 Prompt 演化变异器”。你会收到一份父代风格指令、差异分析诊断以及本轮指定的变异策略方向。
你的任务是优化“产生诗歌的 Prompt”，绝不直接修改诗歌。

允许的变异操作：add、delete、replace、split、merge、adjust、conflict_fix。

硬性要求：
1. 必须产生实质改进（不得原样返回父代文本），同时保留已验证有效、自然的条款。
2. 优先用 replace / merge / delete 替代盲目堆砌 add；整体保持在 5—6 条编号原则、总字数 260—460 字为佳（绝不超过上限），提醒单节紧凑（常为 3—5 行，不写出超 6 行的臃肿节）。
3. 严禁硬编码全诗总行数或总节数（如禁止“全诗4—8节”“总行数15—40行”），篇幅完全服从具体题目要求。
4. 严禁在指令里举例写具体示范名物（如“木桶、麦穗、粮仓、马、村庄”）或示范台词（如“你无力偿还”“我愿……”），防止生成模型在所有题目中生搬硬套示范词句；一律改写为基于题目自身现场物象的关系机制。
5. 严禁写入机械填空句式配额（如“至少三节首行原样重复某句”），并明确避免连续多节在句首用同一个称呼词顶格领起（复沓应错开句首/句中位置并推进动作关系），行内空格停顿须克制有度而非每行切碎；禁止写后计数自检元指令（如“完成后自检”“数出明喻”）。
6. 禁止出现任何诗人姓名，禁止引用参考原句，禁止出现“参考上面”“这些诗”等依赖语，禁止“意境深远”类套话。
7. 每条修改在 changes 中记录 op、target、reason。只输出 JSON，不要 markdown。

JSON 结构：
{"prompt": "完整子代 Prompt", "changes": [{"op": "replace|delete|merge|adjust|add|conflict_fix|split", "target": "被修改的条款", "reason": "基于哪条诊断观察"}], "preserved": ["保留了什么有效机制"], "summary": "一句话说明本次变异的核心改进"}"""


CROSSOVER_SYSTEM = """你是“风格 Prompt 语义重组器（Semantic Crossover）”。你会收到两份表现优秀但侧重点互补的父代风格指令（Parent A 与 Parent B），以及它们各自在评审维度上的优势剖析。
你的任务是吸收两者的互补长处，融合成一份统一、无冲突、精炼自然的子代风格指令。

硬性要求：
1. 真正融合而非简单拼接：提取 Parent A 最擅长的声口/意象/结构机制与 Parent B 最擅长的分行呼吸/句法/抒情机制，消除两者之间的矛盾与重复。
2. 保持精炼高密度：合成后控制在 5—6 条编号原则（可含一句总纲），总字数 260—460 字左右，绝不超过字数上限；保持单节呼吸紧凑（常为 3—5 行，不超 6 行）。
3. 主动剔除任何父代中残留的：具体示范名物清单/示范台词（防止跨题目串味照搬）、机械数字配额、固定填空句式、全诗总行数/总节数限制以及写后自检清单。
4. 禁止诗人姓名、参考原句、依赖参考材料的表述与空泛套话。
5. 只输出 JSON，不要 markdown。

JSON 结构：
{"prompt": "融合后的完整子代 Prompt", "from_parent_a": ["继承自A的核心机制"], "from_parent_b": ["继承自B的核心机制"], "resolved_conflicts": ["消除了什么冗余或冲突"], "summary": "一句话说明重组子代如何兼得双亲优势"}"""


def _rules(config):
    return {
        **config["prompt_rules"],
        "min_prompt_chars": config["population"]["min_prompt_chars"],
        "max_prompt_chars": config["population"]["max_prompt_chars"],
    }


def _select_strategy(parent: dict, round_index: int) -> tuple[str, str]:
    prompt_len = len(parent.get("prompt", ""))
    free_len = int(config_free := 520)
    if prompt_len > free_len:
        return MUTATION_STRATEGIES[1]
    return MUTATION_STRATEGIES[round_index % len(MUTATION_STRATEGIES)]


def _payload(config, parent, analysis, strategy):
    return {
        "kind": "rpe_mutate_prompt",
        "mutation_strategy": {"name": strategy[0], "guidance": strategy[1]},
        "parent_prompt": parent["prompt"],
        "parent_length_chars": len(parent.get("prompt", "")),
        "analysis": {
            "reproduced": analysis.get("reproduced", []),
            "missing": analysis.get("missing", []),
            "extraneous": analysis.get("extraneous", []),
            "prompt_issues": analysis.get("prompt_issues", []),
            "topic_overreliance": analysis.get("topic_overreliance"),
            "summary": analysis.get("summary", ""),
            "actionable_suggestions": analysis.get("actionable_suggestions", []),
        },
        "allowed_operations": ["replace", "delete", "merge", "adjust", "conflict_fix", "add", "split"],
        "constraints": {
            "prompt_chars": [config["population"]["min_prompt_chars"], config["population"]["max_prompt_chars"]],
            "ideal_chars": [240, int(config["evaluation"].get("prompt_length_free", 540))],
            "instruction_units_range": [
                config["prompt_rules"]["min_instruction_units"],
                config["prompt_rules"].get("max_instruction_units", 8),
            ],
            "no_poet_names": True,
            "no_reference_quotes": True,
            "no_hardcoded_poem_line_or_stanza_totals": True,
            "no_post_writing_counting_checklists": True,
            "must_differ_from_parent": True,
            "must_be_independently_usable": True,
        },
    }


def _validate_child_vs_parent(prompt: str, parent_prompt: str, config: dict, selection: dict) -> dict:
    validation = validate_prompt(
        prompt, rules=_rules(config), references=selection["references"],
        target_name=selection["target_name"], target_aliases=selection.get("target_aliases"),
        min_chars=config["population"]["min_prompt_chars"],
        max_chars=config["population"]["max_prompt_chars"],
    )
    if prompt.strip() == parent_prompt.strip():
        errors = list(validation["errors"]) + ["子代 Prompt 与父代完全相同，未发生有效变异"]
        validation = {**validation, "ok": False, "errors": errors}
    return validation


def mutate_candidate(llm, config, parent, analysis, selection, *, round_id=None, strategy_index=0):
    attempts = []
    if len(parent.get("prompt", "")) > int(config["evaluation"].get("prompt_length_free", 540)):
        strategy = MUTATION_STRATEGIES[1]
    else:
        strategy = MUTATION_STRATEGIES[int(strategy_index) % len(MUTATION_STRATEGIES)]
    payload = _payload(config, parent, analysis, strategy)
    tag_base = f"{parent['id']}:mutation:{round_id or parent.get('generation', 0)}:{strategy[0]}"
    data, meta = llm.call_json(
        purpose="rpe_mutate_prompt",
        system=MUTATOR_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False),
        max_tokens=config["population"]["mutation_max_tokens"],
        temperature=config["population"]["mutation_temperature"],
        thinking=config["population"].get("thinking"),
        validator=validate_mutation,
        cache_variant=tag_base,
    )
    prompt = data.get("prompt", "").strip()
    validation = _validate_child_vs_parent(prompt, parent.get("prompt", ""), config, selection)
    attempts.append({"attempt": 1, "validation": validation, "meta": meta})
    for repair in range(config["population"]["max_prompt_repair_attempts"]):
        if validation["ok"]:
            break
        retry_payload = _payload(config, parent, analysis, strategy)
        retry_payload["_validation_feedback"] = (
            "上一次子代 Prompt 未通过校验：" + "；".join(validation["errors"]) +
            "。请输出完整重写后的子代 Prompt（5—7条，不写全诗总行数/总节数，不写自检计数，且必须与父代有实质改进）。"
        )
        data, meta = llm.call_json(
            purpose="rpe_mutate_prompt",
            system=MUTATOR_SYSTEM,
            user=json.dumps(retry_payload, ensure_ascii=False),
            max_tokens=config["population"]["mutation_max_tokens"],
            temperature=config["population"]["mutation_temperature"],
            thinking=config["population"].get("thinking"),
            validator=validate_mutation,
            cache_variant=f"{tag_base}:repair{repair + 1}",
        )
        prompt = data.get("prompt", "").strip()
        validation = _validate_child_vs_parent(prompt, parent.get("prompt", ""), config, selection)
        attempts.append({"attempt": repair + 2, "validation": validation, "meta": meta})
    return {
        "prompt": prompt,
        "valid": validation["ok"],
        "validation": validation,
        "strategy": strategy[0],
        "changes": data.get("changes", []),
        "preserved": data.get("preserved", []),
        "summary": data.get("summary", ""),
        "attempts": attempts,
        "model": meta.get("model"),
        "mock": bool(getattr(llm, "mock", False)),
    }


def _parent_profile_digest(candidate: dict) -> dict:
    evaluation = candidate.get("evaluation") or {}
    ok_rows = [row for row in evaluation.get("evaluations", []) if row.get("ok")]
    dims = {}
    for dim in STYLE_DIMENSIONS:
        vals = [
            row["judge"]["dimensions"][dim]["score"]
            for row in ok_rows if "judge" in row and dim in row["judge"].get("dimensions", {})
        ]
        if vals:
            dims[dim] = round(statistics.mean(vals), 2)
    top_dims = sorted(dims.items(), key=lambda kv: kv[1], reverse=True)[:4]
    weak_dims = sorted(dims.items(), key=lambda kv: kv[1])[:3]
    return {
        "id": candidate["id"],
        "eligible_rate": candidate.get("eligible_rate"),
        "eligible_style": candidate.get("eligible_style"),
        "deterministic_style_score": candidate.get("deterministic_style_score"),
        "judge_style_score": candidate.get("judge_style_score"),
        "literary_quality_score": candidate.get("literary_quality_score"),
        "strongest_dimensions": top_dims,
        "weakest_dimensions": weak_dims,
        "prompt": candidate.get("prompt", ""),
    }


def crossover_candidates(llm, config, parent_a, parent_b, selection, *, round_id="g01", pair_index=0):
    """Recombine two complementary elite parents into one unified, compact child prompt."""
    payload = {
        "kind": "rpe_crossover_prompt",
        "parent_a": _parent_profile_digest(parent_a),
        "parent_b": _parent_profile_digest(parent_b),
        "constraints": {
            "prompt_chars": [config["population"]["min_prompt_chars"], config["population"]["max_prompt_chars"]],
            "ideal_chars": [250, int(config["evaluation"].get("prompt_length_free", 540))],
            "instruction_units_range": [
                config["prompt_rules"]["min_instruction_units"],
                config["prompt_rules"].get("max_instruction_units", 8),
            ],
            "no_poet_names": True,
            "no_reference_quotes": True,
            "no_hardcoded_poem_line_or_stanza_totals": True,
            "no_post_writing_counting_checklists": True,
            "must_be_independently_usable": True,
        },
    }
    attempts = []
    tag_base = f"{parent_a['id']}x{parent_b['id']}:crossover:{round_id}:{pair_index}"
    data, meta = llm.call_json(
        purpose="rpe_crossover_prompt",
        system=CROSSOVER_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False),
        max_tokens=config["population"]["mutation_max_tokens"],
        temperature=config["population"]["mutation_temperature"],
        thinking=config["population"].get("thinking"),
        validator=validate_crossover,
        cache_variant=tag_base,
    )
    prompt = data.get("prompt", "").strip()
    validation = validate_prompt(
        prompt, rules=_rules(config), references=selection["references"],
        target_name=selection["target_name"], target_aliases=selection.get("target_aliases"),
        min_chars=config["population"]["min_prompt_chars"],
        max_chars=config["population"]["max_prompt_chars"],
    )
    if prompt in (parent_a.get("prompt", "").strip(), parent_b.get("prompt", "").strip()):
        validation = {**validation, "ok": False, "errors": list(validation["errors"]) + ["重组子代与某一父代完全相同"]}
    attempts.append({"attempt": 1, "validation": validation, "meta": meta})
    for repair in range(config["population"]["max_prompt_repair_attempts"]):
        if validation["ok"]:
            break
        retry_payload = dict(payload)
        retry_payload["_validation_feedback"] = (
            "上一次重组子代未通过校验：" + "；".join(validation["errors"]) +
            "。请重新输出精炼统一的完整 Prompt（5—7条，不写全诗总行数/总节数，不写自检清单）。"
        )
        data, meta = llm.call_json(
            purpose="rpe_crossover_prompt",
            system=CROSSOVER_SYSTEM,
            user=json.dumps(retry_payload, ensure_ascii=False),
            max_tokens=config["population"]["mutation_max_tokens"],
            temperature=config["population"]["mutation_temperature"],
            thinking=config["population"].get("thinking"),
            validator=validate_crossover,
            cache_variant=f"{tag_base}:repair{repair + 1}",
        )
        prompt = data.get("prompt", "").strip()
        validation = validate_prompt(
            prompt, rules=_rules(config), references=selection["references"],
            target_name=selection["target_name"], target_aliases=selection.get("target_aliases"),
            min_chars=config["population"]["min_prompt_chars"],
            max_chars=config["population"]["max_prompt_chars"],
        )
        attempts.append({"attempt": repair + 2, "validation": validation, "meta": meta})
    changes = (
        [{"op": "crossover_a", "target": item, "reason": f"继承父代 {parent_a['id']}"} for item in data.get("from_parent_a", [])] +
        [{"op": "crossover_b", "target": item, "reason": f"继承父代 {parent_b['id']}"} for item in data.get("from_parent_b", [])]
    )
    return {
        "prompt": prompt,
        "valid": validation["ok"],
        "validation": validation,
        "strategy": "semantic_crossover",
        "changes": changes or [{"op": "crossover", "target": "双亲融合", "reason": data.get("summary", "")}],
        "preserved": list(data.get("from_parent_a", [])) + list(data.get("from_parent_b", [])),
        "resolved_conflicts": data.get("resolved_conflicts", []),
        "summary": data.get("summary", ""),
        "attempts": attempts,
        "model": meta.get("model"),
        "mock": bool(getattr(llm, "mock", False)),
    }
