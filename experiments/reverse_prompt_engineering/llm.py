"""Budgeted, cached, JSON-only access to an LLM for the RPE experiment.

The real transport is the project's existing ``DeepSeekClient``.  This module
adds the experiment-specific concerns: a hard call/token ceiling, an on-disk
response cache for resume, an append-only ledger, and JSON repair attempts.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from poetry_agent.client import DeepSeekClient, load_env


class BudgetExhausted(RuntimeError):
    """Raised before a call that would exceed the configured budget."""


class LLMOutputError(RuntimeError):
    """Raised when the model repeatedly returns unusable JSON."""


def is_output_truncation_error(exc: BaseException) -> bool:
    """The project client raises RuntimeError when finish_reason is not stop."""
    text = str(exc)
    return "length" in text or "未正常结束" in text or "输出未采用" in text


def estimate_tokens(text: str, chars_per_token: float = 1.2) -> int:
    """Rough Chinese-token estimate used only for pre-flight budgeting.

    Actual provider usage, when present, always replaces this estimate.
    """
    if not text:
        return 1
    return max(1, int(math.ceil(len(text) / chars_per_token)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class JsonlLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows


class LLMCache:
    """Append-only JSONL cache.  A cache hit costs no API call."""

    def __init__(self, path, enabled=True):
        self.path = Path(path)
        self.enabled = bool(enabled)
        self.entries = {}
        if self.enabled and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = row.get("key")
                if isinstance(key, str) and isinstance(row.get("content"), str):
                    self.entries[key] = row

    @staticmethod
    def make_key(*, model, system, user, max_tokens, thinking, temperature, variant):
        payload = {
            "model": model,
            "system": system,
            "user": user,
            "max_tokens": max_tokens,
            "thinking": thinking,
            "temperature": temperature,
            "variant": variant,
        }
        return hashlib.sha256(_safe_json(payload).encode("utf-8")).hexdigest()

    def get(self, key):
        return self.entries.get(key)

    def put(self, key, *, model, system, user, content, usage, request_settings, purpose):
        if not self.enabled:
            return
        row = {
            "key": key,
            "model": model,
            "system": system,
            "user": user,
            "content": content,
            "usage": usage,
            "request_settings": request_settings,
            "purpose": purpose,
            "created_at": _utc_now(),
        }
        self.entries[key] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


class Budget:
    def __init__(self, max_calls, max_tokens, price_input=None, price_output=None):
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("max_calls 须为正整数")
        if type(max_tokens) is not int or max_tokens < 1:
            raise ValueError("max_tokens 须为正整数")
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.price_input = price_input
        self.price_output = price_output
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_tokens_saved = 0
        self.cache_hits = 0
        self.cost = 0.0
        self.started = time.monotonic()

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

    def check(self, estimated_input_tokens: int, max_output_tokens: int) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExhausted(f"API 调用预算已用尽（{self.max_calls} 次）")
        projected = self.total_tokens + max(1, estimated_input_tokens) + max_output_tokens
        if projected > self.max_tokens:
            raise BudgetExhausted(
                f"Token 预算不足以再发起一次调用（已用 {self.total_tokens}，"
                f"本次最坏估计 {max(1, estimated_input_tokens) + max_output_tokens}，上限 {self.max_tokens}）"
            )

    def record_call(self, input_tokens, output_tokens) -> None:
        input_tokens = max(0, int(input_tokens or 0))
        output_tokens = max(0, int(output_tokens or 0))
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        if self.price_input is not None and self.price_output is not None:
            self.cost += (input_tokens * self.price_input + output_tokens * self.price_output) / 1_000_000

    def record_cache_hit(self, saved_input_tokens, saved_output_tokens) -> None:
        self.cache_hits += 1
        self.cached_tokens_saved += max(0, int(saved_input_tokens or 0)) + max(0, int(saved_output_tokens or 0))

    def summary(self) -> dict:
        return {
            "max_api_calls": self.max_calls,
            "calls": self.calls,
            "max_total_tokens": self.max_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cache_hits": self.cache_hits,
            "cached_tokens_saved_estimate": self.cached_tokens_saved,
            "price_per_million_input": self.price_input,
            "price_per_million_output": self.price_output,
            "estimated_cost": round(self.cost, 6) if self.price_input is not None else None,
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "note": "estimated_cost 仅在配置了价格时计算；缓存命中不计入 API 调用。",
        }


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|JSON)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _balanced_json_candidates(text: str):
    """Yield balanced brace substrings, earliest start first.

    Some models append a second object or repeat a nested object even in JSON
    mode.  Trying each balanced substring is a bounded repair attempt; schema
    validation still decides whether the recovered object is usable.
    """
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:index + 1]
                    break


def parse_json_object(text: str) -> dict:
    body = strip_code_fence(text)
    try:
        value = json.loads(body)
        if isinstance(value, dict):
            return value
    except (TypeError, ValueError):
        pass
    for candidate in _balanced_json_candidates(body):
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("模型输出不是可解析的 JSON 对象")


class LLM:
    def __init__(self, client, budget: Budget, cache: LLMCache, ledger: JsonlLedger,
                 max_parse_retries=1, request_timeout=90, shared_lock=None):
        self.client = client
        self.model = getattr(client, "model", "unknown")
        self.mock = bool(getattr(client, "mock", False))
        self.budget = budget
        self.cache = cache
        self.ledger = ledger
        self.max_parse_retries = int(max_parse_retries)
        self.request_timeout = int(request_timeout)
        self._lock = shared_lock or threading.RLock()
        if not hasattr(self.budget, "_inflight_calls"):
            self.budget._inflight_calls = 0
            self.budget._inflight_tokens = 0

    def _complete_live(self, system, user, *, max_tokens, thinking, temperature):
        transient_markers = ("网络连接失败", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "请求失败，请检查服务状态")
        max_transient = 1 if self.mock else 5
        for attempt in range(max_transient):
            try:
                return self.client.complete(
                    system, user, timeout=self.request_timeout, max_tokens=max_tokens,
                    thinking=thinking, temperature=temperature,
                )
            except (http.client.HTTPException, OSError, TimeoutError):
                if attempt + 1 < max_transient:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise RuntimeError("网络连接失败或响应读取中断") from None
            except RuntimeError as exc:
                msg = str(exc)
                if attempt + 1 < max_transient and any(m in msg for m in transient_markers):
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise

    def call_text(self, *, purpose, system, user, max_tokens, thinking=None,
                  temperature=None, cache_variant=None, use_cache=True):
        key = LLMCache.make_key(
            model=self.model, system=system, user=user, max_tokens=max_tokens,
            thinking=thinking, temperature=temperature, variant=cache_variant,
        )
        with self._lock:
            if use_cache:
                cached = self.cache.get(key)
                if cached:
                    usage = cached.get("usage") or {}
                    in_tok = usage.get("prompt_tokens") or estimate_tokens(system + user)
                    out_tok = usage.get("completion_tokens") or estimate_tokens(cached["content"])
                    self.budget.record_cache_hit(in_tok, out_tok)
                    self.ledger.append({
                        "at": _utc_now(), "purpose": purpose, "model": self.model,
                        "cache_hit": True, "input_tokens": 0, "output_tokens": 0,
                        "total_tokens": 0, "estimated_cost": 0.0,
                        "cache_key": key, "mock": self.mock,
                        "request_settings": cached.get("request_settings"),
                    })
                    return cached["content"], {
                        "usage": usage, "cache_hit": True,
                        "request_settings": cached.get("request_settings") or {},
                        "model": self.model,
                    }

            est_input = estimate_tokens(system) + estimate_tokens(user)
            est_worst = max(1, est_input) + max_tokens
            if self.budget.calls + self.budget._inflight_calls >= self.budget.max_calls:
                raise BudgetExhausted(f"API 调用预算已用尽（{self.budget.max_calls} 次）")
            if self.budget.total_tokens + self.budget._inflight_tokens + est_worst > self.budget.max_tokens:
                raise BudgetExhausted(
                    f"Token 预算不足以再发起一次调用（已用 {self.budget.total_tokens}，"
                    f"本次最坏估计 {est_worst}，上限 {self.budget.max_tokens}）"
                )
            self.budget._inflight_calls += 1
            self.budget._inflight_tokens += est_worst

        try:
            result = self._complete_live(
                system, user, max_tokens=max_tokens, thinking=thinking, temperature=temperature,
            )
        finally:
            with self._lock:
                self.budget._inflight_calls -= 1
                self.budget._inflight_tokens -= est_worst

        content = result.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMOutputError(f"{purpose}：模型返回空正文")
        usage = result.get("usage") or {}
        in_tok = usage.get("prompt_tokens")
        out_tok = usage.get("completion_tokens")
        if in_tok is None:
            in_tok = est_input
        if out_tok is None:
            out_tok = estimate_tokens(content)
        request_settings = result.get("request_settings") or {}
        with self._lock:
            self.budget.record_call(in_tok, out_tok)
            cost = 0.0
            if self.budget.price_input is not None and self.budget.price_output is not None:
                cost = (int(in_tok) * self.budget.price_input + int(out_tok) * self.budget.price_output) / 1_000_000
            self.ledger.append({
                "at": _utc_now(), "purpose": purpose, "model": self.model,
                "cache_hit": False, "input_tokens": int(in_tok), "output_tokens": int(out_tok),
                "total_tokens": int(in_tok) + int(out_tok), "estimated_cost": round(cost, 6),
                "cache_key": key, "mock": self.mock, "request_settings": request_settings,
            })
            if use_cache:
                self.cache.put(
                    key, model=self.model, system=system, user=user, content=content,
                    usage=usage, request_settings=request_settings, purpose=purpose,
                )
        return content, {
            "usage": usage, "cache_hit": False,
            "request_settings": request_settings, "model": self.model,
        }

    def call_json(self, *, purpose, system, user, max_tokens, validator=None,
                  thinking=None, temperature=None, cache_variant=None, use_cache=True):
        """Call and parse JSON, retrying parse/schema failures a bounded number of times.

        The retry feedback is appended to a copy of the user message; the
        original request is never silently mutated.
        """
        current_user = user
        issues = []
        attempts = self.max_parse_retries + 1
        for attempt in range(attempts):
            content, meta = self.call_text(
                purpose=purpose, system=system, user=current_user, max_tokens=max_tokens,
                thinking=thinking, temperature=temperature,
                cache_variant=(cache_variant if attempt == 0 else f"{cache_variant}:retry{attempt}"),
                use_cache=use_cache,
            )
            try:
                data = parse_json_object(content)
                if validator is not None:
                    found = validator(data)
                    if found:
                        raise ValueError("；".join(str(x) for x in found))
                return data, {**meta, "attempt": attempt + 1}
            except (ValueError, KeyError, TypeError) as exc:
                issues = [str(exc)]
                if attempt + 1 >= attempts:
                    break
                try:
                    payload = json.loads(current_user)
                except (TypeError, ValueError):
                    payload = {"original_request": current_user}
                payload["_retry_feedback"] = (
                    "上一次输出无法使用：" + str(exc)[:500] +
                    "。请严格只输出符合 schema 的 JSON，不要添加解释或 markdown。"
                )
                current_user = json.dumps(payload, ensure_ascii=False)
        raise LLMOutputError(f"{purpose}：连续 {attempts} 次未得到可用 JSON（{issues[-1] if issues else '未知错误'}）")


def restore_budget_from_ledger(budget: Budget, ledger_path: Path) -> None:
    """Make resumed limits cumulative across the whole run, not per process."""
    ledger = JsonlLedger(ledger_path)
    for row in ledger.entries():
        if row.get("cache_hit"):
            budget.cache_hits += 1
        else:
            budget.calls += 1
            budget.input_tokens += int(row.get("input_tokens") or 0)
            budget.output_tokens += int(row.get("output_tokens") or 0)
            budget.cost += float(row.get("estimated_cost") or 0.0)


def make_live_llms(config, run_dir: Path, *, project_root: Path):
    """Build generation and judge wrappers sharing one budget/cache/ledger/lock."""
    load_env(project_root / ".env")
    shared_lock = threading.RLock()
    budget = Budget(
        config["budget"]["max_api_calls"],
        config["budget"]["max_total_tokens"],
        config["budget"].get("price_per_million_input"),
        config["budget"].get("price_per_million_output"),
    )
    cache = LLMCache(Path(run_dir) / "cache.jsonl")
    ledger = JsonlLedger(Path(run_dir) / "ledger.jsonl")
    gen_client = DeepSeekClient()
    gen_llm = LLM(gen_client, budget, cache, ledger,
                  max_parse_retries=config["budget"]["max_parse_retries"],
                  request_timeout=config["budget"]["request_timeout"],
                  shared_lock=shared_lock)
    configured_judge = config["evaluation"].get("judge_model") or os.environ.get("DEEPSEEK_JUDGE_MODEL")
    if configured_judge and configured_judge != gen_client.model:
        judge_client = DeepSeekClient(model=configured_judge)
        judge_llm = LLM(judge_client, budget, cache, ledger,
                        max_parse_retries=config["budget"]["max_parse_retries"],
                        request_timeout=config["budget"]["request_timeout"],
                        shared_lock=shared_lock)
        same = False
    else:
        judge_llm = gen_llm
        same = True
    gen_llm.same_model_as_generator = same
    judge_llm.same_model_as_generator = same
    return gen_llm, judge_llm, same
