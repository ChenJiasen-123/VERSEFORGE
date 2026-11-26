"""RPE-GA entry point.

Examples (from the repository root):
  python experiments/reverse_prompt_engineering/run.py --mode estimate
  python experiments/reverse_prompt_engineering/run.py --mode mock
  python experiments/reverse_prompt_engineering/run.py --mode live --authorize-spend --max-api-calls 320
  python experiments/reverse_prompt_engineering/run.py --mode live --authorize-spend --resume --run-id <id>

The default mode is ``estimate`` and performs no network calls.  Live mode
requires an explicit --authorize-spend flag.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.reverse_prompt_engineering.analyzer import ANALYZER_SYSTEM
from experiments.reverse_prompt_engineering.benchmark import run_benchmark
from experiments.reverse_prompt_engineering.config import load_config, public_config
from experiments.reverse_prompt_engineering.corpus import load_selection
from experiments.reverse_prompt_engineering.evaluator import JUDGE_SYSTEM
from experiments.reverse_prompt_engineering.generator import GENERATOR_SYSTEM
from experiments.reverse_prompt_engineering.initializer import INIT_SYSTEM
from experiments.reverse_prompt_engineering.llm import (
    BudgetExhausted, make_live_llms, restore_budget_from_ledger,
)
from experiments.reverse_prompt_engineering.mock import make_mock_llm
from experiments.reverse_prompt_engineering.mutator import MUTATOR_SYSTEM
from experiments.reverse_prompt_engineering.optimizer import Optimizer
from experiments.reverse_prompt_engineering.report import write_reports
from experiments.reverse_prompt_engineering.store import ExperimentStore, default_run_id


def estimate_experiment(config, selection):
    m = config["population"]["size"]
    k = config["population"]["generations"]
    T = len(config["topics"]["optimization"])
    R = config["generation"]["repetitions"]
    Tt = len(config["topics"]["test"])
    Rt = config["benchmark"]["repetitions"]
    topk = config["evaluation"].get("confirmation_top_k", 0) if k > 0 else 0
    confirm_reps = config["evaluation"].get("confirmation_repetitions", 0)
    confirm_calls = topk * T * confirm_reps * 2
    bench_enabled = bool(config["benchmark"]["enabled"])
    bench_calls = (1 + 3 * Tt * Rt * 2) if bench_enabled else 0
    init_calls = m
    per_gen_calls = m * (2 + 2 * T * R)
    expected_calls = init_calls + k * per_gen_calls + confirm_calls + bench_calls

    ref_chars = sum(len(p["text"]) for p in selection["references"])
    test_ref_chars = sum(len(p["text"]) for p in selection["held_out"])
    init_input = ref_chars + len(INIT_SYSTEM) + 1200
    analysis_input = ref_chars + len(ANALYZER_SYSTEM) + 6000 + 1200
    mutation_input = len(MUTATOR_SYSTEM) + 3000
    generation_input = len(GENERATOR_SYSTEM) + 1200
    judge_input = ref_chars + len(JUDGE_SYSTEM) + 1200
    bench_judge_input = test_ref_chars + len(JUDGE_SYSTEM) + 1200

    call_types = [
        ("initialization", init_calls, init_input, config["population"]["init_max_tokens"]),
        ("analysis", m * k, analysis_input, config["population"]["analysis_max_tokens"]),
        ("mutation", m * k, mutation_input, config["population"]["mutation_max_tokens"]),
        ("generation", m * k * T * R, generation_input, config["generation"]["max_tokens"]),
        ("judge", m * k * T * R, judge_input, config["evaluation"]["judge_max_tokens"]),
        ("confirmation_generation", topk * T * confirm_reps, generation_input, config["generation"]["max_tokens"]),
        ("confirmation_judge", topk * T * confirm_reps, judge_input, config["evaluation"]["judge_max_tokens"]),
        ("benchmark_reverse", 1 if bench_enabled else 0, init_input, config["population"]["init_max_tokens"]),
        ("benchmark_generation", 3 * Tt * Rt if bench_enabled else 0, generation_input, config["benchmark"]["max_tokens"]),
        ("benchmark_judge", 3 * Tt * Rt if bench_enabled else 0, bench_judge_input, config["evaluation"]["judge_max_tokens"]),
    ]
    input_tokens = sum(calls * math.ceil(input_chars / 1.2) for _, calls, input_chars, _ in call_types)
    output_low = sum(calls * out_max * 0.5 for _, calls, _, out_max in call_types)
    output_high = sum(calls * out_max for _, calls, _, out_max in call_types)
    upper_factor = 1 + config["budget"]["max_parse_retries"]
    prompt_calls = init_calls + m * k + (1 if bench_enabled else 0)
    upper_calls = expected_calls * upper_factor + prompt_calls * config["population"]["max_prompt_repair_attempts"]
    result = {
        "note": "估算值；真实 token 取决于模型分词与输出长度。未发起任何 API 调用。",
        "parameters": {
            "population_size": m, "generations": k, "optimization_topics": T,
            "generation_repetitions": R, "test_topics": Tt,
            "benchmark_repetitions": Rt, "confirmation_top_k": topk,
            "confirmation_repetitions": confirm_reps,
        },
        "expected_api_calls": expected_calls,
        "upper_bound_api_calls_with_parse_retries": upper_calls,
        "call_breakdown": {
            "initialization": init_calls,
            "per_generation": per_gen_calls,
            "all_generations": k * per_gen_calls,
            "confirmation": confirm_calls,
            "benchmark": bench_calls,
        },
        "tokens": {
            "input_estimate": int(input_tokens),
            "output_low_estimate": int(output_low),
            "output_high_estimate": int(output_high),
            "total_low_estimate": int(input_tokens + output_low),
            "total_high_estimate": int(input_tokens + output_high),
        },
        "configured_limits": {
            "max_api_calls": config["budget"]["max_api_calls"],
            "max_total_tokens": config["budget"]["max_total_tokens"],
        },
        "estimated_cost": _estimate_cost(config, input_tokens, output_low, output_high),
        "within_configured_limits": (
            expected_calls <= config["budget"]["max_api_calls"] and
            input_tokens + output_high <= config["budget"]["max_total_tokens"]
        ),
    }
    return result


def _estimate_cost(config, input_tokens, output_low, output_high):
    pi = config["budget"].get("price_per_million_input")
    po = config["budget"].get("price_per_million_output")
    if pi is None or po is None:
        return None
    return {
        "currency": "configured",
        "low": round((input_tokens * pi + output_low * po) / 1_000_000, 6),
        "high": round((input_tokens * pi + output_high * po) / 1_000_000, 6),
        "note": "使用 config.budget.price_per_million_* 计算；请先核对供应商当前价格。",
    }


def _print_estimate(estimate):
    print("RPE-GA 预实验估算（未调用 API）")
    print(f"- 预计 API 调用：{estimate['expected_api_calls']} 次"
          f"（含重试上界 {estimate['upper_bound_api_calls_with_parse_retries']} 次）")
    print(f"- 预计输入 token：{estimate['tokens']['input_estimate']:,}")
    print(f"- 预计输出 token：{estimate['tokens']['output_low_estimate']:,}—{estimate['tokens']['output_high_estimate']:,}")
    print(f"- 预计总 token：{estimate['tokens']['total_low_estimate']:,}—{estimate['tokens']['total_high_estimate']:,}")
    print(f"- 配置上限：{estimate['configured_limits']['max_api_calls']} 次 / "
          f"{estimate['configured_limits']['max_total_tokens']:,} token")
    if estimate.get("estimated_cost"):
        print(f"- 预计费用：{estimate['estimated_cost']['low']}—{estimate['estimated_cost']['high']} "
              f"（{estimate['estimated_cost']['currency']}，按配置单价）")
    else:
        print("- 预计费用：未配置单价，无法计算")
    if not estimate.get("within_configured_limits"):
        print("- 警告：预计调用或 token 可能超过当前配置上限；建议提高上限或降低规模。")
    print("- 估算不是承诺；实际调用次数与 token 以 ledger 为准。")


def _resolve_run_dir(config, project_root, run_id):
    root = Path(config["experiment"]["output_root"])
    if not root.is_absolute():
        root = project_root / root
    return root / run_id


def run_experiment(config, mode, *, project_root=PROJECT_ROOT, run_id=None, resume=False,
                   authorized=False, skip_benchmark=False):
    if mode not in ("mock", "live"):
        raise ValueError("run_experiment 的 mode 只能是 mock 或 live")
    if mode == "live" and not authorized:
        raise PermissionError("未授权付费调用：请先查看 --mode estimate，并显式传入 --authorize-spend")
    selection = load_selection(config, project_root)
    topics = config["topics"]
    run_id = run_id or default_run_id(config, mode)
    run_dir = _resolve_run_dir(config, project_root, run_id)
    if mode == "live":
        llm, judge_llm, same_model = make_live_llms(config, run_dir, project_root=project_root)
    else:
        llm = make_mock_llm(config, run_dir)
        judge_llm, same_model = llm, True
    if resume:
        restore_budget_from_ledger(llm.budget, run_dir / "ledger.jsonl")

    store = ExperimentStore(
        run_dir, config=config, selection=selection, topics=topics,
        mode=mode, resume=resume,
    )
    if resume and store.meta:
        old = {k: v for k, v in store.meta.get("config", {}).items() if k != "budget"}
        new = {k: v for k, v in public_config(config).items() if k != "budget"}
        if old != new:
            raise ValueError("断点续跑配置与首次运行不一致（除 budget 外）；请使用原配置或新建运行")
    state = store.load_state() if (resume and store.has_state()) else store.new_state()
    if state.get("mode") != mode:
        raise ValueError(f"断点续跑模式不一致：首次是 {state.get('mode')}，本次是 {mode}")
    state["generation_model"] = llm.model
    state["judge_model"] = judge_llm.model
    state["same_model_as_generator"] = same_model
    if same_model:
        state.setdefault("limitations", []).append(
            "生成与评审使用同一模型；已采用独立调用、匿名评审和 JSON 约束，但仍存在自评偏差，需要人工抽查。"
        )
    else:
        state.setdefault("limitations", []).append(
            "评审模型与生成模型不同，但现有客户端仍只调用 DeepSeek；可能共享训练家族偏差，需要人工抽查。"
        )
    if state.get("is_mock"):
        state.setdefault("limitations", []).append(
            "MOCK 运行：作品、评分、差异分析与适应度均为规则模拟，不是真实 API 结果。"
        )
    state["limitations"] = list(dict.fromkeys(state.get("limitations", [])))
    if state.get("status") not in ("optimization_completed", "completed", "benchmark_budget_exhausted"):
        store.update_status(state, "running")
        optimizer = Optimizer(
            config=config, selection=selection, topics=topics,
            llm=llm, store=store, judge_llm=judge_llm,
        )
        state = optimizer.run(state)
        if state.get("status") == "budget_exhausted":
            state["llm_summary"] = llm.budget.summary()
            store.save_state(state)
            write_reports(state, config, selection, store, benchmark=None)
            return state
    if state.get("status") == "budget_exhausted":
        state["llm_summary"] = llm.budget.summary()
        store.save_state(state)
        write_reports(state, config, selection, store, benchmark=None)
        return state

    benchmark = None
    existing_benchmark = store.path / "benchmark" / "benchmark.json"
    if skip_benchmark or not config["benchmark"]["enabled"]:
        state["benchmark"] = {"completed": False, "reason": "skipped_by_configuration_or_cli"}
    elif existing_benchmark.exists():
        benchmark = json.loads(existing_benchmark.read_text(encoding="utf-8"))
        state["benchmark"] = {
            "completed": True,
            "ranking_by_style_score": benchmark.get("ranking_by_style_score"),
            "comparison": benchmark.get("comparison"),
            "usage_total": benchmark.get("usage_total"),
            "details_path": "benchmark/benchmark.json",
        }
    elif state.get("final_prompt"):
        try:
            benchmark = run_benchmark(
                config=config, selection=selection, test_topics=topics["test"],
                best_prompt=state["final_prompt"]["prompt"], llm=llm, judge_llm=judge_llm,
                store=store, state=state,
            )
            state["benchmark"]["completed"] = True
        except BudgetExhausted as exc:
            state["benchmark"] = {"completed": False, "error": str(exc)}
            state["status"] = "benchmark_budget_exhausted"
            state["limitations"].append("对照实验因预算耗尽未完成。")
    else:
        state["benchmark"] = {"completed": False, "reason": "no_final_prompt"}

    state["llm_summary"] = llm.budget.summary()
    state["ledger_path"] = "ledger.jsonl"
    state["cache_path"] = "cache.jsonl"
    if state.get("status") not in ("benchmark_budget_exhausted",):
        state["status"] = "completed"
    store.update_status(state, state["status"])
    write_reports(state, config, selection, store, benchmark=benchmark)
    store.append_event({"event": "run_finished", "status": state["status"], "usage": state["llm_summary"]})
    return state


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="RPE-GA 中文诗歌逆向提示词实验")
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--mode", choices=["estimate", "mock", "live"], default="estimate")
    parser.add_argument("--run-id", help="运行目录名；续跑时必填")
    parser.add_argument("--resume", action="store_true", help="从 --run-id 对应目录断点续跑")
    parser.add_argument("--authorize-spend", action="store_true",
                        help="明确授权真实付费 API 调用；live 模式必需")
    parser.add_argument("--skip-benchmark", action="store_true", help="跳过 A/B/C 对照实验")
    parser.add_argument("--max-api-calls", type=int, help="覆盖 budget.max_api_calls")
    parser.add_argument("--max-tokens", type=int, help="覆盖 budget.max_total_tokens")
    parser.add_argument("--generations", type=int, help="覆盖 population.generations")
    parser.add_argument("--population-size", type=int, help="覆盖 population.size")
    parser.add_argument("--seed", type=int, help="覆盖 experiment.seed")
    parser.add_argument("--output-root", help="覆盖 experiment.output_root")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        if args.max_api_calls is not None:
            config["budget"]["max_api_calls"] = args.max_api_calls
        if args.max_tokens is not None:
            config["budget"]["max_total_tokens"] = args.max_tokens
        if args.generations is not None:
            config["population"]["generations"] = args.generations
        if args.population_size is not None:
            config["population"]["size"] = args.population_size
        if args.seed is not None:
            config["experiment"]["seed"] = args.seed
        if args.output_root is not None:
            config["experiment"]["output_root"] = args.output_root
        from experiments.reverse_prompt_engineering.config import validate_config
        validate_config(config)

        selection = load_selection(config, PROJECT_ROOT)
        estimate = estimate_experiment(config, selection)
        if args.mode == "estimate":
            _print_estimate(estimate)
            print(json.dumps(estimate, ensure_ascii=False, indent=2))
            return 0
        _print_estimate(estimate)
        if args.mode == "live" and not args.authorize_spend:
            print("拒绝执行：live 模式需要 --authorize-spend 明确授权。未发起真实调用。", file=sys.stderr)
            return 2
        if args.resume and not args.run_id:
            print("错误：--resume 需要同时指定 --run-id。", file=sys.stderr)
            return 1
        state = run_experiment(
            config, args.mode, project_root=PROJECT_ROOT, run_id=args.run_id,
            resume=args.resume, authorized=args.authorize_spend,
            skip_benchmark=args.skip_benchmark,
        )
        print(f"运行目录：{state['run_id']}（{args.mode}）")
        print(f"状态：{state.get('status')}")
        if state.get("final_prompt"):
            print("\n最优 Style Prompt：\n" + state["final_prompt"]["prompt"])
            print(f"\n适应度：{state['final_prompt'].get('fitness')}；报告：report.md")
        if state.get("llm_summary"):
            print(f"API：{state['llm_summary']['calls']} 次；"
                  f"token：{state['llm_summary']['total_tokens']}；"
                  f"缓存命中：{state['llm_summary']['cache_hits']}")
        if state.get("is_mock"):
            print("提示：这是 MOCK 运行，所有作品与分数均为模拟数据，不能作为研究结论。")
        return 0 if state.get("status") == "completed" else 2
    except KeyboardInterrupt:
        print("已中断；重新运行同一 --run-id 并加 --resume 可继续（缓存会复用）。", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, PermissionError, FileNotFoundError, FileExistsError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
