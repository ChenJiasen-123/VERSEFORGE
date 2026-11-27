"""Configuration loading and validation for the RPE-GA experiment.

The experiment is deliberately isolated from the normal poetry workflow.  It
reuses only the project's DeepSeek HTTP client and env loader.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - the project environment has PyYAML
    raise RuntimeError("RPE 实验需要 PyYAML：pip install pyyaml") from exc


DEFAULTS = {
    "experiment": {
        "name": "haizi-rpe-ga",
        "seed": 20251125,
        "output_root": "experiments/reverse_prompt_engineering/runs",
        "language": "zh",
        "notes": "",
    },
    "corpus": {
        "path": "var/haizi/corpus.jsonl",
        "id_prefix": "haizi-",
        "reference_split": "train",
        "reference_count": 15,
        "reference_poem_ids": [],
        "reference_order": "core_rank",
        "held_out_split": "held_out",
        "held_out_count": 13,
        "held_out_poem_ids": [],
        "exclude_flags": ["is_fragment", "is_duplicate", "misattributed", "is_translation"],
        "target_name": "海子",
        "target_aliases": [],
        "exclude_target_name_in_auto_selection": True,
        "max_reference_chars": 1200,
        "max_held_out_chars": 1200,
    },
    "topics": {
        "optimization": [],
        "test": [],
    },
    "generation": {
        "repetitions": 1,
        "temperature": 1.0,
        "max_tokens": 1200,
        "thinking": "disabled",
        "max_form_repair_attempts": 1,
        "default_genre": "modern",
        "default_max_lines": 20,
        "default_requirements": "12—20行，分2—4节；每节1—6行；使用现代汉语；不得出现任何诗人姓名。",
    },
    "population": {
        "size": 6,
        "generations": 8,
        "crossover_count": 2,
        "survivor_max_similarity": 0.88,
        "in_run_confirm_top_k": 2,
        "seed_prompts_path": None,
        "initialization_mode": "independent",
        "init_temperature": 0.95,
        "init_max_tokens": 1400,
        "mutation_temperature": 0.8,
        "mutation_max_tokens": 1800,
        "analysis_temperature": 0.2,
        "analysis_max_tokens": 4000,
        "thinking": "disabled",
        "min_prompt_chars": 120,
        "max_prompt_chars": 600,
        "max_prompt_repair_attempts": 2,
        "patience": 3,
        "min_improvement": 0.20,
        "checkpoint_every": 2,
    },
    "evaluation": {
        "judge_model": None,
        "judge_temperature": 0.0,
        "judge_max_tokens": 3800,
        "judge_thinking": "disabled",
        "rubric_version": "rpe-poetry-zh-v5",
        "deterministic_style_weight": 0.42,
        "judge_style_weight": 0.58,
        "quality_weight": 0.15,
        "prompt_length_free": 520,
        "prompt_length_penalty_per_100_chars": 3.0,
        "prompt_length_penalty_max": 8.0,
        "style_dimension_weights": {
            "poetic_core": 0.18,
            "imagery": 0.12,
            "emotion": 0.11,
            "lineation": 0.11,
            "syntax": 0.09,
            "progression": 0.09,
            "lexical": 0.08,
            "mythic_register": 0.07,
            "structure": 0.05,
            "closure": 0.04,
            "repetition": 0.03,
            "addressivity": 0.02,
            "concreteness": 0.01,
        },
        "pairwise_tiebreak_margin": 2.5,
        "pairwise_max_pairs": 7,
        "pairwise_bonus_cap": 1.2,
        "topic_threshold": 3.0,
        "originality_threshold": 3.0,
        "quality_floor": 2.0,
        "form_penalty": 30.0,
        "topic_penalty_scale": 15.0,
        "originality_penalty_scale": 15.0,
        "quality_penalty_scale": 15.0,
        "copy_penalty": 30.0,
        "copy_lcs_chars": 12,
        "copy_line_chars": 8,
        "copy_rouge1_cap": 0.80,
        "confirmation_top_k": 6,
        "confirmation_repetitions": 1,
        "judge_evidence_required": True,
    },
    "prompt_rules": {
        "max_reference_ngram": 12,
        "warn_reference_ngram": 8,
        "max_vague_phrases": 2,
        "min_instruction_units": 3,
        "max_instruction_units": 8,
        "forbid_hardcoded_poem_counts": True,
        "forbidden_meta_phrases": [
            "完成后自检", "定稿前自检", "成稿后逐条自查", "数出明喻",
            "任一项不满足则重写", "逐项统计", "自查清单",
        ],
        "forbidden_signature_props": [
            "麦地", "麦穗", "麦子", "粮仓", "草原", "德令哈", "青海湖", "敦煌", "亚洲铜", "以梦为马", "面朝大海",
        ],
        "forbidden_dependency_phrases": [
            "参考上面", "参考上述", "上述作品", "以上作品", "这些诗", "前文",
            "上面这些", "所给作品", "给出的诗", "参考作品", "参考诗",
            "上述", "这些作品", "原作", "旧作",
        ],
        "vague_phrases": [
            "富有诗意", "意境深远", "意境优美", "语言优美", "文采斐然",
            "情感真挚", "风格独特", "别具一格", "引人入胜", "浑然天成",
            "耐人寻味", "独具匠心", "诗意盎然", "跃然纸上",
        ],
    },
    "budget": {
        "max_api_calls": 5000,
        "max_total_tokens": 50000000,
        "request_timeout": 90,
        "max_parse_retries": 2,
        "price_per_million_input": None,
        "price_per_million_output": None,
        "require_authorization": True,
    },
    "benchmark": {
        "enabled": True,
        "repetitions": 2,
        "temperature": 1.0,
        "max_tokens": 1200,
        "baseline_a_prompt": "请模仿诗人{target_name}的风格，围绕题目“{topic}”创作一首现代诗。要求：{requirements}",
        "groups": ["A", "B", "C"],
    },
}


def _deep_merge(base, override):
    if not isinstance(override, dict):
        return copy.deepcopy(override)
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path: str | Path) -> dict:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config.yaml 顶层必须是对象")
    config = _deep_merge(DEFAULTS, raw)
    config["_config_path"] = str(path.resolve())
    validate_config(config)
    return config


def validate_config(config: dict) -> None:
    def require(condition, message):
        if not condition:
            raise ValueError("配置错误：" + message)

    exp = config["experiment"]
    require(isinstance(exp.get("name"), str) and exp["name"].strip(), "experiment.name 不能为空")
    require(type(exp.get("seed")) is int, "experiment.seed 须为整数")
    require(isinstance(exp.get("output_root"), str) and exp["output_root"].strip(), "experiment.output_root 不能为空")

    corpus = config["corpus"]
    require(isinstance(corpus.get("path"), str) and corpus["path"].strip(), "corpus.path 不能为空")
    require(type(corpus.get("reference_count")) is int and corpus["reference_count"] >= 1,
            "corpus.reference_count 须为正整数")
    require(type(corpus.get("held_out_count")) is int and corpus["held_out_count"] >= 1,
            "corpus.held_out_count 须为正整数")
    for key in ("reference_poem_ids", "held_out_poem_ids", "exclude_flags", "target_aliases"):
        require(isinstance(corpus.get(key), list), f"corpus.{key} 须为列表")
    require(isinstance(corpus.get("target_name"), str) and corpus["target_name"].strip(),
            "corpus.target_name 不能为空")
    require(isinstance(corpus.get("exclude_target_name_in_auto_selection"), bool),
            "corpus.exclude_target_name_in_auto_selection 须为布尔值")
    require(type(corpus.get("max_reference_chars")) is int and corpus["max_reference_chars"] >= 20,
            "corpus.max_reference_chars 须为不小于20的整数")
    require(type(corpus.get("max_held_out_chars")) is int and corpus["max_held_out_chars"] >= 20,
            "corpus.max_held_out_chars 须为不小于20的整数")

    for group in ("optimization", "test"):
        topics = config["topics"].get(group)
        require(isinstance(topics, list) and topics, f"topics.{group} 不能为空")
        ids = set()
        for topic in topics:
            require(isinstance(topic, dict), f"topics.{group} 的题目须为对象")
            require(isinstance(topic.get("id"), str) and topic["id"].strip(), f"topics.{group} 缺少 id")
            require(topic["id"] not in ids, f"topics.{group} 的 id 重复：{topic['id']}")
            ids.add(topic["id"])
            require(isinstance(topic.get("topic"), str) and topic["topic"].strip(),
                    f"topics.{group}.{topic['id']} 缺少 topic")
            genre = topic.get("genre", config["generation"]["default_genre"])
            require(genre in ("modern", "qijue", "wujue", "wulv", "qilv", "ci"),
                    f"topics.{group}.{topic['id']} 的 genre 不受支持")
            if genre in ("qijue", "wujue", "wulv", "qilv"):
                require(topic.get("pattern") in ("ping_rhyme", "ping_no_rhyme", "ze_rhyme", "ze_no_rhyme"),
                        f"topics.{group}.{topic['id']} 的格律体裁须提供 pattern")
            if genre == "ci":
                require(isinstance(topic.get("ci_profile"), str) and topic["ci_profile"],
                        f"topics.{group}.{topic['id']} 的词须提供 ci_profile")
    opt_ids = {t["id"] for t in config["topics"]["optimization"]}
    test_ids = {t["id"] for t in config["topics"]["test"]}
    require(not (opt_ids & test_ids), "优化题目与测试题目的 id 不能重复")

    gen = config["generation"]
    require(type(gen.get("repetitions")) is int and gen["repetitions"] >= 1, "generation.repetitions 须为正整数")
    require(type(gen.get("max_tokens")) is int and gen["max_tokens"] >= 128, "generation.max_tokens 须不小于128")
    require(type(gen.get("max_form_repair_attempts")) is int and 0 <= gen["max_form_repair_attempts"] <= 2,
            "generation.max_form_repair_attempts 须在0—2之间")
    _number_between(gen.get("temperature"), 0, 2, "generation.temperature")
    require(gen.get("thinking") in (None, "enabled", "disabled"), "generation.thinking 须为 enabled/disabled/null")

    pop = config["population"]
    require(type(pop.get("size")) is int and pop["size"] >= 2, "population.size 须为不小于2的整数")
    require(type(pop.get("generations")) is int and pop["generations"] >= 0, "population.generations 须为非负整数")
    require(type(pop.get("crossover_count", 0)) is int and pop.get("crossover_count", 0) >= 0,
            "population.crossover_count 须为非负整数")
    _number_between(pop.get("survivor_max_similarity", 0.88), 0.5, 1.0, "population.survivor_max_similarity")
    require(type(pop.get("in_run_confirm_top_k", 0)) is int and pop.get("in_run_confirm_top_k", 0) >= 0,
            "population.in_run_confirm_top_k 须为非负整数")
    require(pop.get("seed_prompts_path") is None or (isinstance(pop.get("seed_prompts_path"), str) and pop["seed_prompts_path"].strip()),
            "population.seed_prompts_path 须为非空字符串路径或 null")
    require(pop.get("initialization_mode") == "independent", "population.initialization_mode 目前仅支持 independent")
    for key in ("init_max_tokens", "mutation_max_tokens", "analysis_max_tokens"):
        require(type(pop.get(key)) is int and pop[key] >= 128, f"population.{key} 须不小于128")
    for key in ("init_temperature", "mutation_temperature", "analysis_temperature"):
        _number_between(pop.get(key), 0, 2, f"population.{key}")
    require(pop.get("thinking") in (None, "enabled", "disabled"), "population.thinking 须为 enabled/disabled/null")
    require(type(pop.get("min_prompt_chars")) is int and pop["min_prompt_chars"] >= 20, "population.min_prompt_chars 无效")
    require(type(pop.get("max_prompt_chars")) is int and pop["max_prompt_chars"] > pop["min_prompt_chars"],
            "population.max_prompt_chars 须大于 min_prompt_chars")
    require(type(pop.get("max_prompt_repair_attempts")) is int and 0 <= pop["max_prompt_repair_attempts"] <= 3,
            "population.max_prompt_repair_attempts 须在0—3之间")
    require(type(pop.get("patience")) is int and pop["patience"] >= 0, "population.patience 须为非负整数")
    require(type(pop.get("checkpoint_every")) is int and pop["checkpoint_every"] >= 0,
            "population.checkpoint_every 须为非负整数")
    _number_between(pop.get("min_improvement"), 0, 100, "population.min_improvement")

    ev = config["evaluation"]
    require(ev.get("judge_model") is None or isinstance(ev.get("judge_model"), str),
            "evaluation.judge_model 须为字符串或 null")
    _number_between(ev.get("judge_temperature"), 0, 2, "evaluation.judge_temperature")
    require(type(ev.get("judge_max_tokens")) is int and ev["judge_max_tokens"] >= 256, "evaluation.judge_max_tokens 无效")
    require(ev.get("judge_thinking") in (None, "enabled", "disabled"), "evaluation.judge_thinking 须为 enabled/disabled/null")
    for key in ("deterministic_style_weight", "judge_style_weight"):
        _number_between(ev.get(key), 0, 1, f"evaluation.{key}")
    require(abs(ev["deterministic_style_weight"] + ev["judge_style_weight"] - 1.0) < 1e-9,
            "evaluation 的两个风格权重之和须为1")
    from .validation import STYLE_DIMENSIONS
    weights = ev.get("style_dimension_weights")
    require(isinstance(weights, dict), "evaluation.style_dimension_weights 须为对象")
    require(set(weights) == set(STYLE_DIMENSIONS),
            "evaluation.style_dimension_weights 必须为每个风格维度提供权重")
    for key, value in weights.items():
        _number_between(value, 0, 1, f"evaluation.style_dimension_weights.{key}")
    require(abs(sum(weights.values()) - 1.0) < 1e-6,
            "evaluation.style_dimension_weights 权重之和须为1")
    _number_between(ev.get("quality_weight"), 0, 1, "evaluation.quality_weight")
    require(type(ev.get("prompt_length_free")) is int and ev["prompt_length_free"] >= 0,
            "evaluation.prompt_length_free 须为非负整数")
    _number_between(ev.get("prompt_length_penalty_per_100_chars"), 0, 10,
                    "evaluation.prompt_length_penalty_per_100_chars")
    _number_between(ev.get("prompt_length_penalty_max"), 0, 50, "evaluation.prompt_length_penalty_max")
    for key in ("topic_threshold", "originality_threshold", "quality_floor"):
        _number_between(ev.get(key), 0, 5, f"evaluation.{key}")
    for key in ("form_penalty", "topic_penalty_scale", "originality_penalty_scale",
                "quality_penalty_scale", "copy_penalty"):
        _number_between(ev.get(key), 0, 100, f"evaluation.{key}")
    require(type(ev.get("copy_lcs_chars")) is int and ev["copy_lcs_chars"] >= 4, "evaluation.copy_lcs_chars 无效")
    require(type(ev.get("copy_line_chars")) is int and ev["copy_line_chars"] >= 4, "evaluation.copy_line_chars 无效")
    _number_between(ev.get("copy_rouge1_cap"), 0, 1, "evaluation.copy_rouge1_cap")
    require(type(ev.get("confirmation_top_k")) is int and ev["confirmation_top_k"] >= 0,
            "evaluation.confirmation_top_k 须为非负整数")
    require(type(ev.get("confirmation_repetitions")) is int and ev["confirmation_repetitions"] >= 0,
            "evaluation.confirmation_repetitions 须为非负整数")

    rules = config["prompt_rules"]
    require(type(rules.get("max_reference_ngram")) is int and rules["max_reference_ngram"] >= 8,
            "prompt_rules.max_reference_ngram 须不小于8")
    require(type(rules.get("warn_reference_ngram")) is int and rules["warn_reference_ngram"] >= 4,
            "prompt_rules.warn_reference_ngram 须不小于4")
    require(type(rules.get("max_vague_phrases")) is int and rules["max_vague_phrases"] >= 0,
            "prompt_rules.max_vague_phrases 无效")
    require(type(rules.get("min_instruction_units")) is int and rules["min_instruction_units"] >= 1,
            "prompt_rules.min_instruction_units 无效")
    if rules.get("max_instruction_units") is not None:
        require(type(rules.get("max_instruction_units")) is int and rules["max_instruction_units"] >= rules["min_instruction_units"],
                "prompt_rules.max_instruction_units 须不小于 min_instruction_units")
    require(isinstance(rules.get("forbid_hardcoded_poem_counts", False), bool),
            "prompt_rules.forbid_hardcoded_poem_counts 须为布尔值")
    for key in ("forbidden_dependency_phrases", "vague_phrases"):
        require(isinstance(rules.get(key), list) and all(isinstance(x, str) and x for x in rules[key]),
                f"prompt_rules.{key} 须为非空字符串列表")
    if "forbidden_meta_phrases" in rules:
        require(isinstance(rules["forbidden_meta_phrases"], list) and all(isinstance(x, str) and x for x in rules["forbidden_meta_phrases"]),
                "prompt_rules.forbidden_meta_phrases 须为非空字符串列表")
    if "forbidden_signature_props" in rules:
        require(isinstance(rules["forbidden_signature_props"], list) and all(isinstance(x, str) and x for x in rules["forbidden_signature_props"]),
                "prompt_rules.forbidden_signature_props 须为非空字符串列表")

    budget = config["budget"]
    require(type(budget.get("max_api_calls")) is int and budget["max_api_calls"] >= 1,
            "budget.max_api_calls 须为正整数")
    require(type(budget.get("max_total_tokens")) is int and budget["max_total_tokens"] >= 1000,
            "budget.max_total_tokens 须不小于1000")
    require(type(budget.get("request_timeout")) is int and 1 <= budget["request_timeout"] <= 600,
            "budget.request_timeout 须在1—600秒之间")
    require(type(budget.get("max_parse_retries")) is int and 0 <= budget["max_parse_retries"] <= 3,
            "budget.max_parse_retries 须在0—3之间")
    for key in ("price_per_million_input", "price_per_million_output"):
        value = budget.get(key)
        require(value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0),
                f"budget.{key} 须为非负数或 null")
    require((budget.get("price_per_million_input") is None) == (budget.get("price_per_million_output") is None),
            "budget 的输入/输出单价须同时配置或同时留空")

    bench = config["benchmark"]
    require(isinstance(bench.get("enabled"), bool), "benchmark.enabled 须为布尔值")
    require(type(bench.get("repetitions")) is int and bench["repetitions"] >= 1, "benchmark.repetitions 须为正整数")
    _number_between(bench.get("temperature"), 0, 2, "benchmark.temperature")
    require(type(bench.get("max_tokens")) is int and bench["max_tokens"] >= 128, "benchmark.max_tokens 无效")
    require(isinstance(bench.get("baseline_a_prompt"), str) and "{topic}" in bench["baseline_a_prompt"],
            "benchmark.baseline_a_prompt 须包含 {topic}")
    require(isinstance(bench.get("groups"), list) and set(bench["groups"]) <= {"A", "B", "C"},
            "benchmark.groups 仅支持 A/B/C")


def _number_between(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"配置错误：{name} 须在{low}—{high}之间")


def config_digest(config: dict) -> str:
    from poetry_agent.style.corpus import digest

    clean = {k: v for k, v in config.items() if not str(k).startswith("_")}
    return digest(clean)


def public_config(config: dict) -> dict:
    return json.loads(json.dumps({k: v for k, v in config.items() if not str(k).startswith("_")}, ensure_ascii=False))
