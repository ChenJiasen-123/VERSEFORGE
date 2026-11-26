"""Run-directory state, artifacts and append-only event log."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from poetry_agent.style.corpus import write as atomic_write
from .config import config_digest, public_config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_run_id(config: dict, mode: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{config['experiment']['name']}-{mode}-{uuid4().hex[:6]}"


class ExperimentStore:
    def __init__(self, run_dir, *, config, selection, topics, mode, resume=False):
        self.path = Path(run_dir)
        self.path.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.mode = mode
        self.is_mock = mode == "mock"
        self.state_path = self.path / "state.json"
        self.run_path = self.path / "run.json"
        self.events_path = self.path / "events.jsonl"
        self.selection = selection
        self.topics = topics
        self.resumed = bool(resume and self.state_path.exists())
        if self.run_path.exists() and not self.resumed:
            raise FileExistsError(f"运行目录已存在：{self.path}；请使用 --resume 或换一个 --run-id")
        if not self.resumed:
            meta = {
                "run_id": self.path.name,
                "mode": mode,
                "is_mock": self.is_mock,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "status": "initialized",
                "config": public_config(config),
                "config_sha256": config_digest(config),
                "corpus": selection,
                "topics": topics,
                "warning": (
                    "MOCK RUN：所有作品、评分、差异分析和适应度均为规则生成的模拟数据，"
                    "不得作为真实模型行为或研究结论引用。"
                    if self.is_mock else
                    "LIVE RUN：实际 API 调用。评价器与生成器可能同模型，存在自评偏差。"
                ),
                "method": "RPE-GA adapted to Chinese poetry; see METHOD_ADAPTATION.md",
            }
            atomic_write(self.run_path, meta)
        self.meta = json.loads(self.run_path.read_text(encoding="utf-8"))

    # -- state ---------------------------------------------------------
    def new_state(self) -> dict:
        return {
            "schema_version": "rpe-ga-zh-v1",
            "run_id": self.path.name,
            "mode": self.mode,
            "is_mock": self.is_mock,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "status": "initialized",
            "config_hash": config_digest(self.config),
            "generation": 0,
            "initialization": {"expected": self.config["population"]["size"], "candidates": []},
            "population": [],
            "pending_generation": None,
            "generations": [],
            "best_candidate_id": None,
            "confirmation": None,
            "benchmark": None,
            "llm_summary": None,
            "limitations": [],
        }

    def load_state(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def has_state(self) -> bool:
        return self.state_path.exists()

    def save_state(self, state: dict) -> None:
        state["updated_at"] = utc_now()
        atomic_write(self.state_path, state)

    def update_status(self, state: dict, status: str, **extra) -> None:
        state["status"] = status
        state.update(extra)
        self.save_state(state)
        self.meta["status"] = status
        self.meta["updated_at"] = utc_now()
        atomic_write(self.run_path, self.meta)

    # -- artifacts -----------------------------------------------------
    def write_json(self, name: str, value) -> Path:
        path = self.path / name
        atomic_write(path, value)
        return path

    def write_text(self, name: str, value: str) -> Path:
        path = self.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def append_event(self, event: dict) -> None:
        event = {"at": utc_now(), **event}
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
