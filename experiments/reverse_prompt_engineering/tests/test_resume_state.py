import unittest
from pathlib import Path

from experiments.reverse_prompt_engineering.config import load_config
from experiments.reverse_prompt_engineering.corpus import load_selection
from experiments.reverse_prompt_engineering.optimizer import Optimizer


ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


class _DummyStore:
    def __init__(self):
        self.saved = None
        self.json = {}

    def save_state(self, state):
        self.saved = state

    def write_json(self, name, value):
        self.json[name] = value

    def append_event(self, event):
        pass


class ResumeStateTests(unittest.TestCase):
    def test_midevolution_resume_does_not_reset_population(self):
        cfg = load_config(CONFIG)
        sel = load_selection(cfg, ROOT)
        store = _DummyStore()
        optimizer = Optimizer(
            config=cfg, selection=sel, topics=cfg["topics"], llm=None, store=store,
        )
        evaluated = {
            "id": "g00-i00", "valid": True, "evaluation": {"fitness": 10.0},
            "fitness": 10.0, "eligible": True,
        }
        evolved = {"id": "g03-m00", "prompt": "evolved", "fitness": 99.0, "generation": 3}
        state = {
            "initialization": {"expected": 1, "candidates": [evaluated]},
            "population": [evolved],
            "generation": 3,
        }
        optimizer._ensure_initial_population(state)
        self.assertEqual(state["population"], [evolved])
        self.assertEqual(state["generation"], 3)


if __name__ == "__main__":
    unittest.main()
