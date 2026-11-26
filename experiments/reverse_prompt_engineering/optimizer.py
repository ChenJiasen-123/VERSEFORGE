"""RPE-GA optimizer: initialization, evaluation, mutation, (μ+λ) selection.

No crossover is performed.  Exactly one child is produced per parent.  All
selection is on prompt fitness, never on edited poems.
"""
from __future__ import annotations

import hashlib
import statistics
from datetime import datetime, timezone

from .analyzer import analyze_candidate
from .evaluator import aggregate_evaluations, evaluate_candidate
from .initializer import initialize_population
from .llm import BudgetExhausted, LLMOutputError, is_output_truncation_error
from .mutator import mutate_candidate


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _stable_tiebreak(candidate_id: str) -> int:
    return int(hashlib.sha1(candidate_id.encode("utf-8")).hexdigest()[:12], 16)


class Optimizer:
    def __init__(self, *, config, selection, topics, llm, store, judge_llm=None):
        self.config = config
        self.selection = selection
        self.topics = topics
        self.llm = llm
        self.judge_llm = judge_llm or llm
        self.store = store
        self.size = config["population"]["size"]

    # -- candidate records --------------------------------------------
    def _new_candidate(self, record, *, generation, index, kind, parent=None):
        prompt = record.get("prompt", "")
        cid = f"g{generation:02d}-{kind}{index:02d}-{_short_hash(prompt)}"
        candidate = {
            "id": cid,
            "prompt": prompt,
            "generation": generation,
            "origin": record.get("origin") or ("initializer" if parent is None else "mutation"),
            "parent_id": parent["id"] if parent else None,
            "source_index": index,
            "created_at": utc_now(),
            "valid": bool(record.get("valid")),
            "validation": record.get("validation"),
            "design_notes": record.get("design_notes", ""),
            "covered_dimensions": record.get("covered_dimensions", []),
            "focus": record.get("focus", ""),
            "attempts": record.get("attempts", []),
            "model": record.get("model"),
            "mock": bool(record.get("mock")),
            "evaluation": None,
            "fitness": None,
            "eligible": False,
            "analysis": None,
            "mutation": None,
        }
        if parent is not None:
            candidate["mutation"] = {
                "changes": record.get("changes", []),
                "preserved": record.get("preserved", []),
                "summary": record.get("summary", ""),
                "valid": record.get("valid"),
                "validation": record.get("validation"),
            }
        return candidate

    def _apply_evaluation(self, candidate, evaluation):
        candidate["evaluation"] = evaluation
        for key in (
            "fitness", "eligible", "style_score", "deterministic_style_score",
            "judge_style_score", "literary_quality_score", "topic_adherence",
            "originality", "form_ok_rate", "copy_rate", "score_std",
            "mean_rouge1_f1", "evaluation_count", "successful_evaluations",
            "failed_evaluations",
        ):
            candidate[key] = evaluation.get(key)

    def _evaluate(self, candidate, *, repetitions=None, repetition_offset=0, kind="references"):
        evaluation = evaluate_candidate(
            self.llm, self.config, candidate, self.topics["optimization"], self.selection,
            judge_llm=self.judge_llm, repetitions=repetitions,
            repetition_offset=repetition_offset, kind=kind,
        )
        self._apply_evaluation(candidate, evaluation)
        self.store.write_json(f"evaluations/{candidate['id']}.json", evaluation)
        return evaluation

    # -- initialization ----------------------------------------------
    def _ensure_initial_population(self, state):
        init = state.setdefault("initialization", {"expected": self.size, "candidates": []})
        candidates = init.setdefault("candidates", [])
        if not candidates:
            generated = initialize_population(self.llm, self.config, self.selection)
            for index, record in enumerate(generated):
                candidate = self._new_candidate(record, generation=0, index=index, kind="i")
                candidates.append(candidate)
                self.store.append_event({
                    "event": "initial_candidate_created", "candidate_id": candidate["id"],
                    "valid": candidate["valid"], "origin": candidate["origin"],
                })
                self.store.save_state(state)
            self.store.write_json("initial_population.json", {
                "candidates": candidates,
                "note": "初始种群；fitness 在随后评估中填入。",
            })
        for candidate in candidates:
            if candidate.get("evaluation") is None and candidate.get("valid"):
                self._evaluate(candidate)
                self.store.append_event({
                    "event": "initial_candidate_evaluated", "candidate_id": candidate["id"],
                    "fitness": candidate.get("fitness"), "eligible": candidate.get("eligible"),
                })
                self.store.save_state(state)
        valid_evaluated = [c for c in candidates if c.get("evaluation") is not None]
        if not valid_evaluated:
            raise RuntimeError("初始种群没有产生任何可评估的候选 Prompt；请检查模型输出或提示词规则")
        # Resume safety: only install the initial population on a fresh run.
        # A mid-evolution resume must never overwrite the evolved population or
        # reset the generation counter back to 0.
        if not state.get("population"):
            state["population"] = candidates
            state["generation"] = 0
        self.store.write_json("initial_population.json", {
            "candidates": candidates,
            "valid_evaluated": len(valid_evaluated),
            "note": "初始种群及评估结果。",
        })
        self.store.save_state(state)

    # -- ranking and selection ---------------------------------------
    @staticmethod
    def rank_key(candidate):
        fitness = candidate.get("fitness")
        return (
            1 if fitness is not None else 0,
            1 if candidate.get("eligible") else 0,
            float(fitness) if fitness is not None else 0.0,
            float(candidate.get("literary_quality_score") or 0.0),
            -float(candidate.get("score_std") or 0.0),
            -_stable_tiebreak(candidate["id"]),
        )

    def _rank(self, candidates):
        return sorted(candidates, key=self.rank_key, reverse=True)

    def _select_survivors(self, pool):
        """Top-m selection with prompt-level deduplication.

        The paper selects solely by score.  In a real LLM run, mutation can
        return an unchanged prompt; keeping two identical prompts wastes the
        fixed population budget.  We therefore prefer distinct prompt texts
        first, then fill any remaining slots from the ranked pool.  This is a
        diversity safeguard, not crossover.
        """
        ranked = self._rank(pool)
        survivors, seen = [], set()
        for candidate in ranked:
            key = candidate.get("prompt", "")
            if key in seen:
                continue
            seen.add(key)
            survivors.append(candidate)
            if len(survivors) >= self.size:
                break
        if len(survivors) < self.size:
            for candidate in ranked:
                if candidate not in survivors:
                    survivors.append(candidate)
                if len(survivors) >= self.size:
                    break
        return survivors

    def _selection_summary(self, generation, pool, survivors):
        survivor_ids = {c["id"] for c in survivors}
        ranked = self._rank(pool)
        rows = []
        for rank, candidate in enumerate(ranked, 1):
            if candidate["id"] in survivor_ids:
                reason = "selected_by_rank"
            elif candidate.get("fitness") is None:
                reason = "not_evaluated_or_invalid_prompt"
            elif candidate.get("prompt") in {c.get("prompt") for c in survivors if c["id"] != candidate["id"]}:
                reason = "duplicate_prompt_of_another_survivor"
            elif not candidate.get("eligible"):
                reason = "ineligible_constraints"
            else:
                reason = "lower_fitness_than_survivors"
            rows.append({
                "rank": rank,
                "candidate_id": candidate["id"],
                "parent_id": candidate.get("parent_id"),
                "origin": candidate.get("origin"),
                "fitness": candidate.get("fitness"),
                "eligible": candidate.get("eligible"),
                "style_score": candidate.get("style_score"),
                "literary_quality_score": candidate.get("literary_quality_score"),
                "score_std": candidate.get("score_std"),
                "selected": candidate["id"] in survivor_ids,
                "reason": reason,
            })
        fitnesses = [c["fitness"] for c in pool if c.get("fitness") is not None]
        return {
            "generation": generation,
            "parents": [c["id"] for c in pool if c.get("generation", 0) < generation],
            "pool_size": len(pool),
            "survivor_ids": [c["id"] for c in survivors],
            "ranking": rows,
            "statistics": {
                "count": len(fitnesses),
                "best": round(max(fitnesses), 4) if fitnesses else None,
                "mean": round(statistics.mean(fitnesses), 4) if fitnesses else None,
                "median": round(statistics.median(fitnesses), 4) if fitnesses else None,
                "std": round(statistics.pstdev(fitnesses), 4) if len(fitnesses) > 1 else 0.0,
            },
            "created_at": utc_now(),
        }

    # -- one generation ----------------------------------------------
    def _run_generation(self, state, generation):
        pending = state.get("pending_generation")
        if pending and pending.get("generation") == generation:
            parents = state["population"]
            children = pending.setdefault("children", [])
        else:
            parents = state["population"]
            children = []
            state["pending_generation"] = {
                "generation": generation,
                "parent_ids": [p["id"] for p in parents],
                "children": children,
            }
            self.store.save_state(state)
        done_parents = {child.get("parent_id") for child in children}
        for index, parent in enumerate(parents):
            if parent["id"] in done_parents:
                continue
            analysis = analyze_candidate(self.llm, self.config, parent, parent.get("evaluation") or {}, self.selection)
            parent["analysis"] = analysis
            self.store.write_json(f"analyses/{parent['id']}.json", analysis)
            self.store.append_event({
                "event": "difference_analysis", "candidate_id": parent["id"],
                "fallback": bool(analysis.get("fallback")),
            })
            try:
                mutated = mutate_candidate(
                    self.llm, self.config, parent, analysis, self.selection, round_id=f"g{generation:02d}",
                )
            except LLMOutputError as exc:
                mutated = {
                    "prompt": parent.get("prompt", ""),
                    "valid": False,
                    "validation": {"ok": False, "errors": [str(exc)], "warnings": [], "metrics": {}},
                    "changes": [], "preserved": [], "summary": "", "attempts": [],
                    "model": getattr(self.llm, "model", None), "mock": bool(getattr(self.llm, "mock", False)),
                }
            except RuntimeError as exc:
                if not is_output_truncation_error(exc):
                    raise
                mutated = {
                    "prompt": parent.get("prompt", ""),
                    "valid": False,
                    "validation": {"ok": False, "errors": [f"变异输出被截断：{exc}"], "warnings": [], "metrics": {}},
                    "changes": [], "preserved": [], "summary": "", "attempts": [],
                    "model": getattr(self.llm, "model", None), "mock": bool(getattr(self.llm, "mock", False)),
                }
            child = self._new_candidate(
                {**mutated, "origin": "mutation"}, generation=generation, index=index,
                kind="m", parent=parent,
            )
            child["analysis_id"] = parent["id"]
            if child["valid"]:
                self._evaluate(child)
            else:
                self.store.append_event({
                    "event": "mutation_invalid", "candidate_id": child["id"],
                    "parent_id": parent["id"],
                    "errors": (child.get("validation") or {}).get("errors"),
                })
            children.append(child)
            state.setdefault("all_children", []).append({
                "generation": generation,
                "id": child["id"],
                "parent_id": parent["id"],
                "valid": child["valid"],
                "fitness": child.get("fitness"),
                "eligible": child.get("eligible"),
                "changes": (child.get("mutation") or {}).get("changes", []),
                "summary": (child.get("mutation") or {}).get("summary", ""),
                "prompt": child["prompt"],
            })
            self.store.write_json(f"mutations/{child['id']}.json", {
                "child_id": child["id"], "parent_id": parent["id"],
                "prompt": child["prompt"], "valid": child["valid"],
                "validation": child.get("validation"), "mutation": child.get("mutation"),
            })
            self.store.save_state(state)
            self.store.append_event({
                "event": "child_evaluated", "candidate_id": child["id"],
                "parent_id": parent["id"], "valid": child["valid"],
                "fitness": child.get("fitness"),
            })

        pool = parents + children
        survivors = self._select_survivors(pool)
        summary = self._selection_summary(generation, pool, survivors)
        summary["parents"] = [p["id"] for p in parents]
        summary["children"] = [c["id"] for c in children]
        state["population"] = survivors
        state["generation"] = generation
        state["pending_generation"] = None
        state.setdefault("generations", []).append(summary)
        self.store.write_json(f"population/gen_{generation:03d}.json", {
            "generation": generation,
            "parents": parents,
            "children": children,
            "survivors": survivors,
            "summary": summary,
        })
        self.store.save_state(state)
        self.store.append_event({
            "event": "generation_complete", "generation": generation,
            "best": summary["statistics"]["best"], "survivors": summary["survivor_ids"],
        })
        return summary

    def _write_checkpoint(self, state, generation):
        interval = self.config["population"].get("checkpoint_every", 0)
        if not interval or generation % interval != 0:
            return
        ranked = self._rank(state["population"])
        best = ranked[0] if ranked else None
        snapshot = {
            "generation": generation,
            "created_at": utc_now(),
            "best_candidate_id": best["id"] if best else None,
            "best_fitness": best.get("fitness") if best else None,
            "population": ranked,
            "generation_summary": state.get("generations", [{}])[-1],
            "fitness_history": state.get("fitness_history", []),
            "note": f"每 {interval} 代保存一次的快照；完整逐代文件仍在 population/gen_*.json。",
        }
        self.store.write_json(f"checkpoints/gen_{generation:03d}/snapshot.json", snapshot)
        if best:
            self.store.write_text(f"checkpoints/gen_{generation:03d}/best_prompt.txt", best.get("prompt", "") + "\n")
            rows = ["# Generation %03d checkpoint" % generation, "", "| rank | candidate | fitness | eligible |", "|---|---|---:|---|"]
            for rank, candidate in enumerate(ranked, 1):
                rows.append(f"| {rank} | {candidate['id']} | {candidate.get('fitness')} | {candidate.get('eligible')} |")
            rows.append("")
            self.store.write_text(f"checkpoints/gen_{generation:03d}/leaderboard.md", "\n".join(rows))
        self.store.append_event({"event": "checkpoint", "generation": generation, "best": best.get("fitness") if best else None})

    # -- confirmation and finalization --------------------------------
    def _confirm_top(self, state):
        ev = self.config["evaluation"]
        top_k = min(ev.get("confirmation_top_k", 0), self.size)
        reps = ev.get("confirmation_repetitions", 0)
        if top_k <= 0 or reps <= 0:
            return None
        ranked = self._rank(state["population"])[:top_k]
        confirmations = []
        for candidate in ranked:
            if candidate.get("evaluation") is None:
                continue
            old_evaluations = candidate["evaluation"].get("evaluations", [])
            max_rep = max((row.get("repetition", -1) for row in old_evaluations), default=-1)
            fitness_before = candidate.get("fitness")
            try:
                extra = evaluate_candidate(
                    self.llm, self.config, candidate, self.topics["optimization"], self.selection,
                    judge_llm=self.judge_llm, repetitions=reps,
                    repetition_offset=max_rep + 1, kind="references",
                )
            except BudgetExhausted as exc:
                confirmations.append({"candidate_id": candidate["id"], "completed": False, "error": str(exc)})
                state["confirmation"] = {
                    "completed": False, "top_k": top_k, "repetitions": reps,
                    "rows": confirmations, "note": "确认评估时预算耗尽；保留原适应度。",
                }
                self.store.save_state(state)
                return state["confirmation"]
            merged = old_evaluations + extra.get("evaluations", [])
            evaluation = aggregate_evaluations(candidate, merged, self.config)
            self._apply_evaluation(candidate, evaluation)
            self.store.write_json(f"evaluations/{candidate['id']}.json", evaluation)
            confirmations.append({
                "candidate_id": candidate["id"], "completed": True,
                "added_evaluations": len(extra.get("evaluations", [])),
                "fitness_before": fitness_before, "fitness_after": candidate.get("fitness"),
                "evaluation_count": candidate.get("evaluation_count"),
            })
            self.store.append_event({
                "event": "confirmation_evaluated", "candidate_id": candidate["id"],
                "fitness": candidate.get("fitness"),
            })
            self.store.save_state(state)
        state["confirmation"] = {
            "completed": True, "top_k": top_k, "repetitions": reps,
            "rows": confirmations,
            "note": "仅对最终种群的高分候选追加生成样本，以降低单次随机生成造成的误判。",
        }
        self.store.save_state(state)
        return state["confirmation"]

    def _finalize(self, state):
        ranked = self._rank(state["population"])
        evaluated = [c for c in ranked if c.get("fitness") is not None]
        if not evaluated:
            raise RuntimeError("最终种群没有可评估的候选")
        best = evaluated[0]
        state["best_candidate_id"] = best["id"]
        state["final_population_ids"] = [c["id"] for c in ranked]
        state["best_fitness"] = best["fitness"]
        state["final_prompt"] = {
            "prompt": best["prompt"],
            "candidate_id": best["id"],
            "fitness": best["fitness"],
            "eligible": best.get("eligible"),
            "style_score": best.get("style_score"),
            "literary_quality_score": best.get("literary_quality_score"),
            "topic_adherence": best.get("topic_adherence"),
            "originality": best.get("originality"),
            "score_std": best.get("score_std"),
            "evaluation_count": best.get("evaluation_count"),
            "generation": best.get("generation"),
            "parent_id": best.get("parent_id"),
            "origin": best.get("origin"),
            "rubric_version": self.config["evaluation"]["rubric_version"],
            "judge_model": getattr(self.judge_llm, "model", None),
            "same_model_as_generator": bool(getattr(self.judge_llm, "same_model_as_generator", True)),
            "is_mock": bool(getattr(self.llm, "mock", False)),
            "run_id": state["run_id"],
            "created_at": utc_now(),
            "limitations": [
                "这是通过生成实验搜索到的风格控制 Prompt，不是诗人原始创作指令。",
                "适应度包含 LLM 评审，存在主观性与同模型自评偏差。",
                "小样本、单模型、有限轮次；不能据此声称普遍有效。",
            ] + (["MOCK 运行：Prompt 与分数均为模拟数据，不是研究结论。"] if state.get("is_mock") else []),
        }
        self.store.write_json("final_prompt.json", state["final_prompt"])
        self.store.write_text("final_prompt.txt", best["prompt"] + "\n")
        self.store.write_json("final_population.json", {
            "candidates": ranked,
            "best_candidate_id": best["id"],
        })
        self.store.save_state(state)
        return best

    # -- main loop ----------------------------------------------------
    def run(self, state):
        try:
            self._ensure_initial_population(state)
            max_generations = self.config["population"]["generations"]
            patience = self.config["population"].get("patience", 0)
            min_improvement = self.config["population"].get("min_improvement", 0.0)
            history = state.get("fitness_history", [])
            last_history = history[-1] if history else None
            best_so_far = (
                last_history.get("best_so_far") if last_history else
                max((c["fitness"] for c in state["population"] if c.get("fitness") is not None), default=None)
            )
            stale = int(last_history.get("stale_generations", 0)) if last_history else 0
            while state["generation"] < max_generations:
                generation = state["generation"] + 1
                summary = self._run_generation(state, generation)
                current = summary["statistics"]["best"]
                if current is not None:
                    if best_so_far is None or current > best_so_far + min_improvement:
                        best_so_far = current
                        stale = 0
                    else:
                        stale += 1
                state.setdefault("fitness_history", []).append({
                    "generation": generation,
                    "best": current,
                    "mean": summary["statistics"]["mean"],
                    "std": summary["statistics"]["std"],
                    "best_so_far": best_so_far,
                    "stale_generations": stale,
                })
                self._write_checkpoint(state, generation)
                self.store.save_state(state)
                if patience and stale >= patience:
                    state["early_stopped"] = {
                        "generation": generation, "patience": patience,
                        "min_improvement": min_improvement,
                        "reason": "连续多代最优适应度没有超过阈值",
                    }
                    self.store.append_event({"event": "early_stop", **state["early_stopped"]})
                    break
            self._confirm_top(state)
            best = self._finalize(state)
            state["status"] = "optimization_completed"
            self.store.update_status(state, "optimization_completed")
            return state
        except BudgetExhausted as exc:
            state["budget_exhausted"] = {"message": str(exc), "at": utc_now()}
            self.store.update_status(state, "budget_exhausted")
            self.store.append_event({"event": "budget_exhausted", "message": str(exc)})
            return state


