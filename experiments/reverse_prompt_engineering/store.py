"""Run-directory state, artifacts, append-only event log, and real-time EAReport sync."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from poetry_agent.style.corpus import write as atomic_write
from .config import config_digest, public_config


LIVE_START = "<!-- LIVE_STATUS_START -->"
LIVE_END = "<!-- LIVE_STATUS_END -->"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_run_id(config: dict, mode: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{config['experiment']['name']}-{mode}-{uuid4().hex[:6]}"


def _fmt(v, digits=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def _render_live_block(run_dir: Path, state: dict) -> str:
    ledger = run_dir / "ledger.jsonl"
    calls = tokens = hits = 0
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("cache_hit"):
                hits += 1
            else:
                calls += 1
                tokens += int(row.get("total_tokens") or 0)
    pending = state.get("pending_generation")
    init_cands = (state.get("initialization") or {}).get("candidates", [])
    init_eval_done = sum(1 for c in init_cands if c.get("evaluation") is not None)
    if pending:
        stage = f"第 {pending.get('generation')} 代演化中（已完成子代 {len(pending.get('children', []))} 个）"
    elif state.get("status") == "running" and not state.get("population"):
        stage = f"Phase 1 初始化与首轮评估中（已生成候选 {len(init_cands)} 个，已评 {init_eval_done} 个）"
    else:
        stage = f"已完成至第 {state.get('generation', 0)} 代（状态：`{state.get('status')}`）"

    lines = [
        LIVE_START,
        f"- **更新时间（UTC）**：`{utc_now()}`",
        f"- **当前活跃运行**：`{state.get('run_id')}`（生成模型 `{state.get('generation_model') or 'deepseek-flash'}` / 评审模型 `{state.get('judge_model') or 'deepseek-chat'}`）",
        f"- **实时阶段**：{stage}",
        f"- **本轮实时累计调用**：`{calls}` 次真实调用 / `{tokens:,}` tokens（缓存命中 `{hits}` 次）",
        "",
    ]
    history = state.get("fitness_history") or []
    if history:
        lines.extend([
            "#### 实时逐代演化轨迹",
            "",
            "| 代 | 领先候选 | 合格率 | 合格风格分 | 综合适应度 | 池均值 | 连续未提升 |",
            "|---:|---|---:|---:|---:|---:|---:|",
        ])
        for h in history:
            lines.append(
                f"| {h.get('generation')} | `{h.get('leader_id', '—')}` | {_fmt(h.get('eligible_rate'))} | "
                f"{_fmt(h.get('eligible_style'))} | {_fmt(h.get('best'))} | {_fmt(h.get('mean'))} | {h.get('stale_generations')} |"
            )
        lines.append("")

    pop = state.get("population") or [c for c in init_cands if c.get("evaluation") is not None]
    if pop:
        from .optimizer import Optimizer
        ranked = sorted(pop, key=Optimizer.rank_key, reverse=True)
        lines.extend([
            "#### 当前实时种群排行榜",
            "",
            "| 排名 | 候选 ID | 来源 | 合格率 | 合格风格分 | 适应度 | 评估篇数 | 字数 |",
            "|---:|---|---|---:|---:|---:|---:|---:|",
        ])
        for idx, c in enumerate(ranked[:6], 1):
            lines.append(
                f"| {idx} | `{c.get('id')}` | `{c.get('origin')}` | {_fmt(c.get('eligible_rate'))} | "
                f"{_fmt(c.get('eligible_style'))} | {_fmt(c.get('fitness'))} | "
                f"{c.get('evaluation_count') or 0} | {len(c.get('prompt') or '')} |"
            )
        lines.append("")
        top = ranked[0]
        if top.get("prompt"):
            lines.extend([
                f"#### 当前领先 Style Prompt（`{top.get('id')}`，{len(top['prompt'])} 字）",
                "",
                "```text",
                top["prompt"].strip(),
                "```",
                "",
            ])

    bench = state.get("benchmark")
    if isinstance(bench, dict) and bench.get("completed") and bench.get("qualified_comparison"):
        qc = bench["qualified_comparison"]
        ranks_str = " > ".join(" = ".join(tier) for tier in qc.get("ranks", []))
        pairs = qc.get("paired_C_minus_baseline", {})
        lines.extend([
            "#### 独立留出集 A/B/C 盲测结果摘要",
            "",
            f"- **合格率与合格风格分总序**：**{ranks_str}**",
            f"- **同题配对 C vs A**：`{pairs.get('A', {}).get('wins')}/{pairs.get('A', {}).get('ties')}/{pairs.get('A', {}).get('losses')}`（均差 `{_fmt(pairs.get('A', {}).get('mean_style_delta'))}`）",
            f"- **同题配对 C vs B**：`{pairs.get('B', {}).get('wins')}/{pairs.get('B', {}).get('ties')}/{pairs.get('B', {}).get('losses')}`（均差 `{_fmt(pairs.get('B', {}).get('mean_style_delta'))}`）",
            "",
        ])
    lines.append(LIVE_END)
    return "\n".join(lines)


def _write_run_progress(run_dir: Path, block: str) -> Path:
    """Persist one run's live report beside its state, without editing shared report content."""
    run_dir = Path(run_dir)
    path = run_dir / "live_progress.md"
    title = f"# 实时进度：{run_dir.name}"
    content = f"{title}\n\n> 本文件只记录此运行目录的进度。\n\n{block}\n"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    return path


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
                    "LIVE RUN：实际 API 调用。"
                ),
                "method": "RPE-GA v3 adapted to Chinese poetry; see EAReport.md",
            }
            atomic_write(self.run_path, meta)
        self.meta = json.loads(self.run_path.read_text(encoding="utf-8"))

    # -- state ---------------------------------------------------------
    def new_state(self) -> dict:
        return {
            "schema_version": "rpe-ga-zh-v2",
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

    def _sync_ea_report(self, state: dict) -> None:
        if self.is_mock:
            return
        try:
            _write_run_progress(self.path, _render_live_block(self.path, state))
        except OSError:
            pass

    def save_state(self, state: dict) -> None:
        state["updated_at"] = utc_now()
        atomic_write(self.state_path, state)
        self._sync_ea_report(state)

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
