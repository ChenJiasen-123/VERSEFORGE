"""Reference-corpus selection and anonymized prompt blocks.

Reuses ``poetry_agent.style.corpus.load_corpus`` for UTF-8 parsing, duplicate
notices, normalization and provenance validation.  Selection is deterministic.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from poetry_agent.style.corpus import digest, load_corpus
from .metrics import reference_diversity


TIER_ORDER = {"core": 0, "A": 1, "S": 2}


def _is_excluded(row, exclude_flags) -> bool:
    metadata = row.get("metadata") or {}
    return any(bool(metadata.get(flag)) for flag in exclude_flags)


def _sort_key(row):
    metadata = row.get("metadata") or {}
    tier = metadata.get("tier")
    rank = metadata.get("core_rank")
    return (
        TIER_ORDER.get(tier, 9),
        rank if isinstance(rank, int) else 9999,
        str(row["poem_id"]),
    )


def _public_poem(row):
    text = row["text"]
    return {
        "poem_id": row["poem_id"],
        "title": row.get("title"),
        "text": text,
        "source": row.get("source"),
        "source_url": row.get("source_url"),
        "genre": row.get("genre"),
        "period": row.get("period"),
        "split": row.get("split"),
        "copyright": row.get("copyright"),
        "metadata": row.get("metadata") or {},
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "han_length": len(re.sub(r"[^\u3400-\u9fff]", "", text)),
    }


def _select(rows, *, split, explicit_ids, count, id_prefix, exclude_flags, max_chars, label,
            target_name=None, target_aliases=None, exclude_name=False):
    by_id = {row["poem_id"]: row for row in rows}
    names = [n for n in ([target_name] + list(target_aliases or [])) if n]
    if explicit_ids:
        selected = []
        notices = []
        for poem_id in explicit_ids:
            if poem_id not in by_id:
                raise ValueError(f"{label}：找不到 poem_id {poem_id}")
            row = by_id[poem_id]
            if row.get("split") != split:
                raise ValueError(f"{label}：{poem_id} 的 split 不是 {split}")
            if _is_excluded(row, exclude_flags):
                raise ValueError(f"{label}：{poem_id} 被排除标记命中")
            if max_chars and len(row["text"]) > max_chars:
                notices.append({"poem_id": poem_id, "warning": f"正文超过 max_chars={max_chars}，按原文保留未截断"})
            if exclude_name and any(name in row["text"] for name in names):
                raise ValueError(f"{label}：{poem_id} 正文含诗人姓名；请改用其他作品，或显式关闭 exclude_target_name_in_auto_selection")
            selected.append(row)
        return selected, notices
    candidates = []
    for row in rows:
        if row.get("split") != split:
            continue
        if id_prefix and not str(row["poem_id"]).startswith(id_prefix):
            continue
        if _is_excluded(row, exclude_flags):
            continue
        if max_chars and len(row["text"]) > max_chars:
            continue
        if exclude_name and any(name in row["text"] for name in names):
            continue
        candidates.append(row)
    candidates.sort(key=_sort_key)
    if len(candidates) < count:
        raise ValueError(f"{label}：符合条件的诗只有 {len(candidates)} 篇，少于所需 {count} 篇")
    return candidates[:count], []


def load_selection(config: dict, project_root: Path) -> dict:
    corpus_cfg = config["corpus"]
    path = Path(corpus_cfg["path"])
    if not path.is_absolute():
        path = project_root / path
    if not path.exists():
        raise FileNotFoundError(f"找不到参考语料：{path}")
    rows, source_notices = load_corpus(path)
    references, ref_notices = _select(
        rows, split=corpus_cfg["reference_split"],
        explicit_ids=corpus_cfg.get("reference_poem_ids") or [],
        count=corpus_cfg["reference_count"],
        id_prefix=corpus_cfg.get("id_prefix"), exclude_flags=corpus_cfg["exclude_flags"],
        max_chars=corpus_cfg.get("max_reference_chars"), label="参考集",
        target_name=corpus_cfg.get("target_name"), target_aliases=corpus_cfg.get("target_aliases"),
        exclude_name=corpus_cfg.get("exclude_target_name_in_auto_selection", True),
    )
    held_out, held_notices = _select(
        rows, split=corpus_cfg["held_out_split"],
        explicit_ids=corpus_cfg.get("held_out_poem_ids") or [],
        count=corpus_cfg["held_out_count"],
        id_prefix=corpus_cfg.get("id_prefix"), exclude_flags=corpus_cfg["exclude_flags"],
        max_chars=corpus_cfg.get("max_held_out_chars"), label="留出集",
        target_name=corpus_cfg.get("target_name"), target_aliases=corpus_cfg.get("target_aliases"),
        exclude_name=corpus_cfg.get("exclude_target_name_in_auto_selection", True),
    )
    ref_ids = {row["poem_id"] for row in references}
    held_ids = {row["poem_id"] for row in held_out}
    overlap = ref_ids & held_ids
    if overlap:
        raise ValueError(f"参考集与留出集重叠：{sorted(overlap)}")
    ref_hashes = {hashlib.sha256(row["text"].encode("utf-8")).hexdigest() for row in references}
    held_hashes = {hashlib.sha256(row["text"].encode("utf-8")).hexdigest() for row in held_out}
    if ref_hashes & held_hashes:
        raise ValueError("参考集与留出集存在正文完全相同的诗")

    public_refs = [_public_poem(row) for row in references]
    public_held = [_public_poem(row) for row in held_out]
    return {
        "source_path": str(path),
        "corpus_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "corpus_manifest_hash": digest([_public_poem(row) for row in rows]),
        "source_notices": source_notices,
        "selection_notices": ref_notices + held_notices,
        "selection_rule": {
            "reference": "split=reference_split; id_prefix; exclude_flags; max_reference_chars; sort by tier/core_rank/poem_id; take reference_count",
            "held_out": "same rule on held_out_split; never used during optimization",
            "explicit_ids": bool(corpus_cfg.get("reference_poem_ids") or corpus_cfg.get("held_out_poem_ids")),
        },
        "references": public_refs,
        "held_out": public_held,
        "reference_diversity": reference_diversity([p["text"] for p in public_refs]),
        "target_name": corpus_cfg["target_name"],
        "target_aliases": corpus_cfg.get("target_aliases") or [],
    }


def anonymous_references(references: list[dict], include_title=False) -> list[dict]:
    """The only representation sent to initialization/analysis/judging.

    The poet name, source URL, notebook id and split are deliberately omitted.
    """
    rows = []
    for index, poem in enumerate(references, 1):
        row = {"label": f"参考作品{index}", "text": poem["text"]}
        if include_title and poem.get("title"):
            row["title"] = poem["title"]
        rows.append(row)
    return rows


def reference_texts(selection: dict, kind="references") -> list[str]:
    return [poem["text"] for poem in selection[kind]]


def _han_normalize(text: str) -> str:
    return re.sub(r"[^\u3400-\u9fff]", "", text)


def reference_ngrams(references: list[dict], n: int) -> set[str]:
    grams = set()
    for poem in references:
        body = _han_normalize(poem["text"])
        for i in range(max(0, len(body) - n + 1)):
            grams.add(body[i:i + n])
    return grams


def reference_lines(references: list[dict], min_chars=4) -> list[str]:
    result = []
    for poem in references:
        for line in poem["text"].splitlines():
            body = _han_normalize(line)
            if len(body) >= min_chars:
                result.append(body)
    return result


def reference_payload(selection: dict, kind="references") -> dict:
    return {
        "reference_poems": anonymous_references(selection[kind]),
        "reference_count": len(selection[kind]),
    }
