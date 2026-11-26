"""Phase 1: generate the initial population of style prompts."""
from __future__ import annotations

import json

from .corpus import anonymous_references
from .llm import LLMOutputError, is_output_truncation_error
from .metrics import corpus_stylometry_summary
from .validation import validate_initializer, validate_prompt


INIT_SYSTEM = """你是一位中文现代诗比较诗学与创作指导专家。你会看到若干来自同一诗人的匿名参考作品，以及这批作品的客观表面分布统计（行长、长短行变异、无标点断行率、词汇重现率等）。
你的任务不是写文学评论，也不是猜测作者，而是归纳这批参考诗最核心、可迁移的声口、呼吸、意象张力与抒情组织规律，写成一份精炼、高密度的“风格指令”，使另一个完全看不到参考诗的写作者，在面对任何全新现代日常题目时，也能写出神似而非形似机械拼装的诗作。

硬性要求：
1. 精炼高密度：输出 5—6 条编号原则（可加一句简短总纲），总字数控制在 260—460 字左右（不超过 600 字）。
2. 严禁硬编码全诗总行数或总节数（如禁止写“全诗控制在4—8节”“总行数15—40行”），篇幅服从具体题目要求；但应提醒单节保持紧凑克制（通常每节 3—5 行，不写出超过 6 行的臃肿长节）。
3. 严禁写入具体示范名物词表或示范台词：不要在指令里举例写“木桶、麦穗、粮仓、马、村庄”或“我愿……”“你无力偿还……”等具体词句（否则写作者会在无关题目里照搬这些词句导致串味扣分）！只描述“从题目自身的现场具体器物出发，直接跃向大地、黑夜、水火、时间、身体等原初尺度”的关系机制与句法功能。
4. 严禁机械填空模板与写后计数自检：不要规定“至少三节首行原样重复”，禁止写“完成后自检”“数出明喻处数”。复沓与呼告须随语境改变句法位置或语义重量。
5. 抓住精神重力与无标点呼吸的统一：行末极少落标点，靠自然断行、行内留白以及舒展长句与峭拔短行的反差建立节奏；朴素直陈与具象动作并置，结尾承接前文落地留白，不作格言总结。
6. 禁止出现任何诗人姓名，禁止引用参考原句，禁止出现“参考上面”“这些诗”等依赖语，禁止使用“富有诗意”“意境深远”等空泛套话。
7. 只输出 JSON，不要 markdown，不要额外解释。

JSON 结构：
{"prompt": "完整风格指令", "design_notes": "归纳依据简述（不引用长句）", "covered_dimensions": ["lexical", "syntax", "lineation", "imagery", "emotion", "structure", "mythic_register"]}"""


def _rules(config):
    return {
        **config["prompt_rules"],
        "min_prompt_chars": config["population"]["min_prompt_chars"],
        "max_prompt_chars": config["population"]["max_prompt_chars"],
    }


def _payload(config, selection, *, focus, index, total, mode):
    ref_texts = [p["text"] for p in selection["references"]]
    return {
        "kind": "rpe_initialize" if mode == "population" else "rpe_reverse_once",
        "task": "从匿名参考作品及客观分布统计反推可迁移的中文现代诗风格指令",
        "mode": mode,
        "candidate_index": index,
        "candidate_total": total,
        "focus": focus,
        "reference_stylometry_summary": corpus_stylometry_summary(ref_texts),
        "reference_poems": anonymous_references(selection["references"]),
        "constraints": {
            "prompt_chars": [config["population"]["min_prompt_chars"], config["population"]["max_prompt_chars"]],
            "target_chars_ideal": [240, 520],
            "instruction_units_range": [
                config["prompt_rules"]["min_instruction_units"],
                config["prompt_rules"].get("max_instruction_units", 8),
            ],
            "no_poet_names": True,
            "no_reference_quotes": True,
            "no_hardcoded_poem_line_or_stanza_totals": True,
            "no_post_writing_counting_checklists": True,
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
        feedback = (
            "上一次生成的指令违反了以下硬性规则：" + "；".join(validation["errors"]) +
            "。请完整重写更精炼的 prompt（5—7条，不写全诗总行数/总节数，不写自检计数清单，不引用原句）。"
        )
        data, meta, prompt, validation = _one_call(
            llm, config, selection, focus=focus, index=index, total=total, mode=mode,
            cache_tag=f"{cache_tag}-repair{repair + 1}",
            payload_extra={"_validation_feedback": feedback},
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
        "整体声口与诗学气度：整体把握说话姿态、生命尺度、长短句呼吸与意象组织关系。",
        "无标点断行与呼吸落差：聚焦行末极少标点、靠自然断行与行内空格蓄势，以及舒展长句与峭拔短行交替的声音结构。",
        "日常现场与原初元素的嫁接：聚焦如何把具体处境与大地、黑夜、雨水、身体、时间等具有重量的元素直接碰撞，拒绝琐碎零件罗列。",
        "命名句式、呼告姿态与变奏复沓：聚焦判断命名句、赤诚呼告，以及核心词跨节回返时如何改变语境与句法位置而非机械重复。",
        "抒情直陈与具象承载的平衡：聚焦如何在质朴动作与直接生命感叹之间保持张力，以及结尾停在回响与承接上的方式。",
        "质朴词域与反散文化句法：聚焦高频基础实词的反复锤炼、压缩并列句式，以及克制解释性连词和密集明喻的语言习惯。",
    ]
    candidates = []
    for index in range(size):
        focus = focuses[index % len(focuses)]
        try:
            candidates.append(make_prompt_candidate(
                llm, config, selection, focus=focus, index=index, total=size,
                mode="population", cache_tag=f"init-v3-{index}",
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
            focus="整体归纳最显著、可跨题材独立复用的现代诗声口、呼吸与意象组织规律。",
            index=0, total=1, mode="one_shot_reverse", cache_tag="benchmark-b-reverse-v3",
        )
    except (LLMOutputError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError) and not is_output_truncation_error(exc):
            raise
        return _invalid_record(
            origin="one_shot_reverse", focus="one_shot_reverse", index=0,
            error=str(exc), mock=getattr(llm, "mock", False),
        )
