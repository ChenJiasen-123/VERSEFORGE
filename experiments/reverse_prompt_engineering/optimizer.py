"""RPE-GA optimizer: initialization, evaluation, targeted mutation, semantic
crossover, similarity-niched (μ+λ) selection, and progressive elite confirmation.

All selection is strictly on prompt-level generation performance, never by
editing generated poems.
"""
from __future__ import annotations

import hashlib
import statistics
from datetime import datetime, timezone

from .analyzer import analyze_candidate
from .evaluator import aggregate_evaluations, evaluate_candidate, selection_objective
from .initializer import initialize_population
from .llm import BudgetExhausted, LLMOutputError, is_output_truncation_error
from .metrics import prompt_similarity
from .mutator import crossover_candidates, mutate_candidate


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
    def _new_candidate(self, record, *, generation, index, kind, parent=None, extra_parents=None):
        prompt = record.get("prompt", "")
        cid = f"g{generation:02d}-{kind}{index:02d}-{_short_hash(prompt)}"
        if extra_parents:
            parent_ids = [p["id"] for p in extra_parents]
            parent_id = "+".join(parent_ids)
        else:
            parent_ids = [parent["id"]] if parent else []
            parent_id = parent["id"] if parent else None
        candidate = {
            "id": cid,
            "prompt": prompt,
            "generation": generation,
            "origin": record.get("origin") or ("initializer" if parent is None and not extra_parents else "mutation"),
            "parent_id": parent_id,
            "parent_ids": parent_ids,
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
        if parent is not None or extra_parents:
            candidate["mutation"] = {
                "strategy": record.get("strategy", ""),
                "changes": record.get("changes", []),
                "preserved": record.get("preserved", []),
                "resolved_conflicts": record.get("resolved_conflicts", []),
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
            "failed_evaluations", "eligible_count", "eligible_rate", "eligible_style",
            "prompt_length_chars", "prompt_length_penalty",
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

    def _extend_evaluation_to_reps(self, candidate, target_reps: int) -> int:
        """Ensure candidate has at least ``target_reps`` repetitions per optimization topic."""
        if target_reps <= 0 or not candidate.get("evaluation"):
            return 0
        old_evaluations = candidate["evaluation"].get("evaluations", [])
        topic_count = len(self.topics["optimization"])
        if topic_count <= 0:
            return 0
        current_reps = len(old_evaluations) // topic_count
        needed = target_reps - current_reps
        if needed <= 0:
            return 0
        max_rep = max((row.get("repetition", -1) for row in old_evaluations), default=-1)
        extra = evaluate_candidate(
            self.llm, self.config, candidate, self.topics["optimization"], self.selection,
            judge_llm=self.judge_llm, repetitions=needed,
            repetition_offset=max_rep + 1, kind="references",
        )
        merged = old_evaluations + extra.get("evaluations", [])
        evaluation = aggregate_evaluations(candidate, merged, self.config)
        self._apply_evaluation(candidate, evaluation)
        self.store.write_json(f"evaluations/{candidate['id']}.json", evaluation)
        return len(extra.get("evaluations", []))

    def _confirm_leaders_in_run(self, state, candidates=None):
        """Confirm top-k elites during evolution so 1-sample flukes cannot freeze progress."""
        in_run_k = min(int(self.config["population"].get("in_run_confirm_top_k", 0)), self.size)
        confirm_reps = int(self.config["evaluation"].get("confirmation_repetitions", 0))
        if in_run_k <= 0 or confirm_reps <= 0 or self.llm is None:
            return candidates
        target_reps = int(self.config["generation"]["repetitions"]) + confirm_reps
        target_pool = state["population"] if candidates is None else candidates
        ranked = [c for c in self._rank(target_pool) if c.get("fitness") is not None][:in_run_k]
        changed = False
        for candidate in ranked:
            before = candidate.get("fitness")
            added = self._extend_evaluation_to_reps(candidate, target_reps)
            if added > 0:
                changed = True
                self.store.append_event({
                    "event": "in_run_elite_confirmed",
                    "candidate_id": candidate["id"],
                    "added_evaluations": added,
                    "fitness_before": before,
                    "fitness_after": candidate.get("fitness"),
                    "eligible_rate": candidate.get("eligible_rate"),
                    "eligible_style": candidate.get("eligible_style"),
                })
                self.store.save_state(state)
        if changed:
            ranked_all = self._rank(target_pool)
            if candidates is None:
                state["population"] = ranked_all
                self.store.save_state(state)
            return ranked_all
        return target_pool

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
        if not state.get("population"):
            state["population"] = candidates
            state["generation"] = 0
            self._confirm_leaders_in_run(state)
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
            *selection_objective(candidate),
            float(fitness) if fitness is not None else 0.0,
            float(candidate.get("literary_quality_score") or 0.0),
            -float(candidate.get("score_std") or 0.0),
            -_stable_tiebreak(candidate["id"]),
        )

    def _rank(self, candidates):
        return sorted(candidates, key=self.rank_key, reverse=True)

    def _select_survivors(self, pool):
        """Top-m selection with exact deduplication and prompt-similarity niching."""
        ranked = self._rank(pool)
        max_sim = float(self.config["population"].get("survivor_max_similarity", 0.88))
        survivors, seen = [], set()
        # Pass 1: distinct, similarity-niched candidates so near-clones don't crowd out diversity.
        for candidate in ranked:
            key = candidate.get("prompt", "")
            if not key or key in seen:
                continue
            if survivors and any(prompt_similarity(key, s.get("prompt", "")) >= max_sim for s in survivors):
                continue
            seen.add(key)
            survivors.append(candidate)
            if len(survivors) >= self.size:
                break
        # Pass 2: fill remaining slots with any non-identical prompt texts by rank.
        if len(survivors) < self.size:
            for candidate in ranked:
                key = candidate.get("prompt", "")
                if key in seen:
                    continue
                seen.add(key)
                survivors.append(candidate)
                if len(survivors) >= self.size:
                    break
        # Pass 3: fallback if pool has fewer distinct prompts than self.size.
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
        max_sim = float(self.config["population"].get("survivor_max_similarity", 0.88))
        rows = []
        for rank, candidate in enumerate(ranked, 1):
            if candidate["id"] in survivor_ids:
                reason = "selected_by_rank"
            elif candidate.get("fitness") is None:
                reason = "not_evaluated_or_invalid_prompt"
            elif candidate.get("prompt") in {c.get("prompt") for c in survivors if c["id"] != candidate["id"]}:
                reason = "duplicate_prompt_of_another_survivor"
            elif any(prompt_similarity(candidate.get("prompt", ""), s.get("prompt", "")) >= max_sim for s in survivors):
                reason = "near_duplicate_niched_out"
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
                "eligible_rate": candidate.get("eligible_rate"),
                "eligible_style": candidate.get("eligible_style"),
                "evaluation_count": candidate.get("evaluation_count"),
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

    def _crossover_pairs(self, parents, count: int):
        ranked = [p for p in self._rank(parents) if p.get("valid") and p.get("fitness") is not None]
        if len(ranked) < 2 or count <= 0:
            return []
        pairs = []
        for i in range(len(ranked)):
            for j in range(i + 1, len(ranked)):
                if prompt_similarity(ranked[i].get("prompt", ""), ranked[j].get("prompt", "")) < 0.92:
                    pairs.append((ranked[i], ranked[j]))
                if len(pairs) >= count:
                    return pairs
        while len(pairs) < count and len(ranked) >= 2:
            pairs.append((ranked[0], ranked[min(len(ranked) - 1, len(pairs) + 1)]))
        return pairs[:count]

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

        done_mutation_parents = {
            child.get("parent_id") for child in children if child.get("origin") == "mutation"
        }
        for index, parent in enumerate(parents):
            if parent["id"] in done_mutation_parents:
                continue
            analysis = analyze_candidate(
                self.llm, self.config, parent, parent.get("evaluation") or {}, self.selection,
            )
            parent["analysis"] = analysis
            self.store.write_json(f"analyses/{parent['id']}.json", analysis)
            self.store.append_event({
                "event": "difference_analysis", "candidate_id": parent["id"],
                "fallback": bool(analysis.get("fallback")),
            })
            try:
                mutated = mutate_candidate(
                    self.llm, self.config, parent, analysis, self.selection,
                    round_id=f"g{generation:02d}", strategy_index=generation + index,
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
            self._record_child_artifacts(state, generation, child)

        # Semantic crossover between distinct elite parents
        crossover_count = int(self.config["population"].get("crossover_count", 0))
        pairs = self._crossover_pairs(parents, crossover_count)
        done_crossovers = {
            child.get("parent_id") for child in children if child.get("origin") == "crossover"
        }
        for pair_idx, (pa, pb) in enumerate(pairs):
            pair_key = f"{pa['id']}+{pb['id']}"
            if pair_key in done_crossovers:
                continue
            try:
                crossed = crossover_candidates(
                    self.llm, self.config, pa, pb, self.selection,
                    round_id=f"g{generation:02d}", pair_index=pair_idx,
                )
            except LLMOutputError as exc:
                crossed = {
                    "prompt": "",
                    "valid": False,
                    "validation": {"ok": False, "errors": [str(exc)], "warnings": [], "metrics": {}},
                    "changes": [], "preserved": [], "summary": "", "attempts": [],
                    "model": getattr(self.llm, "model", None), "mock": bool(getattr(self.llm, "mock", False)),
                }
            except RuntimeError as exc:
                if not is_output_truncation_error(exc):
                    raise
                crossed = {
                    "prompt": "",
                    "valid": False,
                    "validation": {"ok": False, "errors": [f"重组输出被截断：{exc}"], "warnings": [], "metrics": {}},
                    "changes": [], "preserved": [], "summary": "", "attempts": [],
                    "model": getattr(self.llm, "model", None), "mock": bool(getattr(self.llm, "mock", False)),
                }
            child = self._new_candidate(
                {**crossed, "origin": "crossover"}, generation=generation, index=pair_idx,
                kind="x", extra_parents=[pa, pb],
            )
            if child["valid"]:
                self._evaluate(child)
            else:
                self.store.append_event({
                    "event": "crossover_invalid", "candidate_id": child["id"],
                    "parent_id": child["parent_id"],
                    "errors": (child.get("validation") or {}).get("errors"),
                })
            children.append(child)
            self._record_child_artifacts(state, generation, child)

        pool = parents + children
        survivors = self._select_survivors(pool)
        # Confirm top elites BEFORE committing generation state so resume is atomic
        survivors = self._confirm_leaders_in_run(state, candidates=survivors)
        state["population"] = survivors
        state["generation"] = generation
        state["pending_generation"] = None
        summary = self._selection_summary(generation, pool, survivors)
        summary["parents"] = [p["id"] for p in parents]
        summary["children"] = [c["id"] for c in children]
        state.setdefault("generations", []).append(summary)
        self.store.write_json(f"population/gen_{generation:03d}.json", {
            "generation": generation,
            "parents": parents,
            "children": children,
            "survivors": survivors,
            "summary": summary,
        })
        return summary

    def _record_child_artifacts(self, state, generation, child):
        state.setdefault("all_children", []).append({
            "generation": generation,
            "id": child["id"],
            "origin": child.get("origin"),
            "parent_id": child.get("parent_id"),
            "valid": child["valid"],
            "fitness": child.get("fitness"),
            "eligible": child.get("eligible"),
            "eligible_rate": child.get("eligible_rate"),
            "eligible_style": child.get("eligible_style"),
            "changes": (child.get("mutation") or {}).get("changes", []),
            "summary": (child.get("mutation") or {}).get("summary", ""),
            "prompt": child["prompt"],
        })
        self.store.write_json(f"mutations/{child['id']}.json", {
            "child_id": child["id"],
            "origin": child.get("origin"),
            "parent_id": child.get("parent_id"),
            "prompt": child["prompt"],
            "valid": child["valid"],
            "validation": child.get("validation"),
            "mutation": child.get("mutation"),
        })
        self.store.save_state(state)
        self.store.append_event({
            "event": "child_evaluated", "candidate_id": child["id"],
            "origin": child.get("origin"), "parent_id": child.get("parent_id"),
            "valid": child["valid"], "fitness": child.get("fitness"),
            "eligible_rate": child.get("eligible_rate"),
            "eligible_style": child.get("eligible_style"),
        })

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
            "best_eligible_rate": best.get("eligible_rate") if best else None,
            "best_eligible_style": best.get("eligible_style") if best else None,
            "population": ranked,
            "generation_summary": state.get("generations", [{}])[-1],
            "fitness_history": state.get("fitness_history", []),
            "note": f"每 {interval} 代保存一次的快照；完整逐代文件仍在 population/gen_*.json。",
        }
        self.store.write_json(f"checkpoints/gen_{generation:03d}/snapshot.json", snapshot)
        if best:
            self.store.write_text(f"checkpoints/gen_{generation:03d}/best_prompt.txt", best.get("prompt", "") + "\n")
            rows = [
                f"# Generation {generation:03d} checkpoint",
                "",
                "| rank | candidate | eligible_rate | eligible_style | fitness | evals |",
                "|---|---|---:|---:|---:|---:|",
            ]
            for rank, candidate in enumerate(ranked, 1):
                rows.append(
                    f"| {rank} | {candidate['id']} | {candidate.get('eligible_rate')} | "
                    f"{candidate.get('eligible_style')} | {candidate.get('fitness')} | "
                    f"{candidate.get('evaluation_count')} |"
                )
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
        target_reps = int(self.config["generation"]["repetitions"]) + int(reps)
        confirmation = state.get("confirmation")
        if not confirmation:
            shortlist = [c["id"] for c in self._rank(state["population"]) if c.get("fitness") is not None][:top_k]
            confirmation = {"completed": False, "top_k": top_k, "repetitions": reps,
                            "target_repetitions": target_reps, "shortlist": shortlist, "rows": []}
            state["confirmation"] = confirmation
            self.store.save_state(state)
        candidates = {c["id"]: c for c in state["population"]}
        confirmations = confirmation["rows"]
        done = {row["candidate_id"] for row in confirmations if row["completed"]}
        for candidate_id in confirmation["shortlist"]:
            if candidate_id in done:
                continue
            candidate = candidates[candidate_id]
            fitness_before = candidate.get("fitness")
            added = self._extend_evaluation_to_reps(candidate, target_reps)
            confirmations.append({
                "candidate_id": candidate["id"], "completed": True,
                "added_evaluations": added,
                "fitness_before": fitness_before, "fitness_after": candidate.get("fitness"),
                "eligible_rate": candidate.get("eligible_rate"),
                "eligible_style": candidate.get("eligible_style"),
                "evaluation_count": candidate.get("evaluation_count"),
            })
            self.store.append_event({
                "event": "confirmation_evaluated", "candidate_id": candidate["id"],
                "added_evaluations": added, "fitness": candidate.get("fitness"),
                "eligible_rate": candidate.get("eligible_rate"),
                "eligible_style": candidate.get("eligible_style"),
            })
            self.store.save_state(state)
        confirmation["completed"] = True
        state["population"] = self._rank(state["population"])
        self.store.save_state(state)
        return state["confirmation"]

    def _finalize(self, state):
        ranked = self._rank(state["population"])
        evaluated = [c for c in ranked if c.get("fitness") is not None]
        confirmation = state.get("confirmation")
        if confirmation and "shortlist" in confirmation:
            if not confirmation["completed"]:
                raise RuntimeError("候选确认重评尚未完成")
            evaluated = [c for c in evaluated if c["id"] in confirmation["shortlist"]]
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
            "deterministic_style_score": best.get("deterministic_style_score"),
            "judge_style_score": best.get("judge_style_score"),
            "literary_quality_score": best.get("literary_quality_score"),
            "topic_adherence": best.get("topic_adherence"),
            "originality": best.get("originality"),
            "eligible_rate": best.get("eligible_rate"),
            "eligible_style": best.get("eligible_style"),
            "score_std": best.get("score_std"),
            "evaluation_count": best.get("evaluation_count"),
            "prompt_length_chars": best.get("prompt_length_chars"),
            "prompt_length_penalty": best.get("prompt_length_penalty"),
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
                "适应度包含 LLM 评审，即使切换同家族不同模型仍可能存在评测偏好。",
                "有限语料与测试题目；审美结论仍需结合人工盲评抽查。",
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
            best_objective = (tuple(last_history["best_objective"]) if last_history else
                              selection_objective(self._rank(state["population"])[0]))
            stale = int(last_history.get("stale_generations", 0)) if last_history else 0
            while state["generation"] < max_generations and not state.get("early_stopped"):
                generation = state["generation"] + 1
                summary = self._run_generation(state, generation)
                leader = self._rank(state["population"])[0]
                current = selection_objective(leader)
                if (current[0] > best_objective[0] or
                        (current[0] == best_objective[0] and current[1] > best_objective[1] + min_improvement)):
                    best_objective = current
                    stale = 0
                else:
                    stale += 1
                state.setdefault("fitness_history", []).append({
                    "generation": generation,
                    "best": leader.get("fitness"),
                    "leader_id": leader["id"],
                    "eligible_rate": current[0],
                    "eligible_style": leader.get("eligible_style"),
                    "mean": summary["statistics"]["mean"],
                    "std": summary["statistics"]["std"],
                    "best_objective": list(best_objective),
                    "stale_generations": stale,
                })
                if patience and stale >= patience:
                    state["early_stopped"] = {
                        "generation": generation, "patience": patience,
                        "min_improvement": min_improvement,
                        "reason": "连续多代合格率和合格作品风格分均未改善至阈值",
                    }
                    self.store.append_event({"event": "early_stop", **state["early_stopped"]})
                self._write_checkpoint(state, generation)
                self.store.save_state(state)
                self.store.append_event({
                    "event": "generation_complete", "generation": generation,
                    "leader": leader["id"], "eligible_rate": current[0],
                    "eligible_style": leader.get("eligible_style"), "survivors": summary["survivor_ids"],
                })
            self._confirm_top(state)
            self._finalize(state)
            state["status"] = "optimization_completed"
            self.store.update_status(state, "optimization_completed")
            return state
        except BudgetExhausted as exc:
            state["budget_exhausted"] = {"message": str(exc), "at": utc_now()}
            self.store.update_status(state, "budget_exhausted")
            self.store.append_event({"event": "budget_exhausted", "message": str(exc)})
            return state
