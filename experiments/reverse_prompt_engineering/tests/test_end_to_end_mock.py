import json
import tempfile
import unittest
from pathlib import Path

from experiments.reverse_prompt_engineering.config import load_config
from experiments.reverse_prompt_engineering.run import run_experiment


ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


def small_config(tmp, *, max_calls=300, max_tokens=800000):
    cfg = load_config(CONFIG)
    cfg["experiment"]["output_root"] = str(Path(tmp) / "runs")
    cfg["population"]["size"] = 2
    cfg["population"]["generations"] = 1
    cfg["population"]["checkpoint_every"] = 1
    cfg["evaluation"]["confirmation_top_k"] = 1
    cfg["evaluation"]["confirmation_repetitions"] = 1
    cfg["benchmark"]["repetitions"] = 1
    cfg["budget"]["max_api_calls"] = max_calls
    cfg["budget"]["max_total_tokens"] = max_tokens
    return cfg


class EndToEndMockTests(unittest.TestCase):
    def test_full_mock_pipeline_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = small_config(tmp)
            state = run_experiment(
                cfg, "mock", project_root=ROOT, run_id="e2e", authorized=False,
            )
            self.assertEqual(state["status"], "completed")
            self.assertTrue(state["is_mock"])
            self.assertEqual(state["generation"], 1)
            self.assertEqual(len(state["population"]), 2)
            self.assertEqual(len({c["prompt"] for c in state["population"]}), len(state["population"]))
            self.assertIsNotNone(state.get("final_prompt"))
            best = state["final_prompt"]
            self.assertIn(best["candidate_id"], {c["id"] for c in state["population"]})
            self.assertTrue(best["is_mock"])
            run_dir = Path(cfg["experiment"]["output_root"]) / "e2e"
            for name in (
                "state.json", "run.json", "report.md", "initial_population.json",
                "final_population.json", "final_prompt.json", "final_prompt.txt",
                "benchmark/benchmark.json", "benchmark/benchmark.md",
                "ledger.jsonl", "cache.jsonl", "events.jsonl", "population/gen_001.json",
                "checkpoints/gen_001/snapshot.json", "checkpoints/gen_001/best_prompt.txt",
                "checkpoints/gen_001/leaderboard.md",
            ):
                self.assertTrue((run_dir / name).exists(), name)
            self.assertIn("MOCK", (run_dir / "report.md").read_text(encoding="utf-8"))
            benchmark = json.loads((run_dir / "benchmark" / "benchmark.json").read_text(encoding="utf-8"))
            self.assertEqual(set(benchmark["groups"]), {"A", "B", "C"})
            self.assertEqual(
                {t["id"] for t in benchmark["test_topics"]},
                {t["id"] for t in cfg["topics"]["test"]},
            )
            self.assertFalse(benchmark["fairness"]["judge_sees_prompt_or_group"])
            self.assertFalse(benchmark["fairness"]["prompts_mutated_after_test"])

            # Generation and judge isolation, inspected from the on-disk cache.
            rows = [json.loads(line) for line in (run_dir / "cache.jsonl").read_text(encoding="utf-8").splitlines() if line]
            generation_rows = [r for r in rows if r.get("purpose") == "rpe_generate_poem"]
            self.assertTrue(generation_rows)
            for row in generation_rows:
                payload = json.loads(row["user"])
                self.assertNotIn("reference_poems", payload)
                self.assertNotIn("reference_poems", row["user"])
                allowed = {"kind", "style_prompt", "topic", "genre", "max_lines", "requirements", "output_schema", "_retry_feedback"}
                self.assertTrue(set(payload) <= allowed, set(payload) - allowed)
                # Baseline A intentionally uses the poet name; all optimized/baseline-B
                # prompts must not contain the name.
                if cfg["corpus"]["target_name"] not in payload["style_prompt"]:
                    self.assertNotIn(cfg["corpus"]["target_name"], payload["style_prompt"])
                    corpus = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["corpus"]
                    for ref in corpus["references"]:
                        self.assertNotIn(ref["text"], payload["style_prompt"])
            judge_rows = [r for r in rows if r.get("purpose") == "rpe_judge_poem"]
            self.assertTrue(judge_rows)
            for row in judge_rows:
                payload = json.loads(row["user"])
                self.assertNotIn("style_prompt", payload)
                self.assertNotIn("candidate_prompt", payload)
                self.assertNotIn("candidate_id", payload)
                self.assertNotIn("parent_id", payload)
                self.assertNotIn("generation", payload)
                self.assertIn("reference_poems", payload)
                self.assertIn("generated_poem", payload)

    def test_budget_exhaustion_then_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = small_config(tmp, max_calls=2, max_tokens=500000)
            first = run_experiment(cfg, "mock", project_root=ROOT, run_id="resume", authorized=False)
            self.assertEqual(first["status"], "budget_exhausted")
            self.assertIsNone(first.get("final_prompt"))
            run_dir = Path(cfg["experiment"]["output_root"]) / "resume"
            self.assertTrue((run_dir / "state.json").exists())

            cfg2 = small_config(tmp, max_calls=300, max_tokens=800000)
            second = run_experiment(cfg2, "mock", project_root=ROOT, run_id="resume", resume=True, authorized=False)
            self.assertEqual(second["status"], "completed")
            self.assertIsNotNone(second.get("final_prompt"))
            # Budget was restored from the ledger, so it is cumulative.
            self.assertGreaterEqual(second["llm_summary"]["calls"], 2)

    def test_live_without_authorization_is_refused_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = small_config(tmp)
            with self.assertRaises(PermissionError):
                run_experiment(cfg, "live", project_root=ROOT, run_id="noauth", authorized=False)


if __name__ == "__main__":
    unittest.main()
