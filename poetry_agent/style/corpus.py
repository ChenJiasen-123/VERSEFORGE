"""Read only explicitly supplied poetry and preserve original text and provenance."""
import hashlib
import json
import os
import tempfile
import unicodedata
from pathlib import Path

VERSION = "1.0"


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        name = temp.name
    try:
        Path(name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def clean(rows):
    """Retain user-defined grouping and splits. Report duplicate copies explicitly."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("语料须为非空 JSON 数组或 JSONL")
    poems, notices = [], []
    seen_ids, bodies = set(), {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("语料记录须为对象")
        for key in ("poem_id", "text"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"语料缺少有效的 {key}")
        pid = row["poem_id"]
        if pid in seen_ids:
            raise ValueError(f"重复 poem_id：{pid}")
        seen_ids.add(pid)
        genre = row.get("genre")
        if genre == "modern_poetry":
            genre = "modern"
        meta = row.get("metadata")
        if meta is None:
            meta = {}
        if not isinstance(meta, dict) or any(type(meta[k]) is not bool for k in ("source_verified", "is_translation") if k in meta):
            raise ValueError(f"{pid} 的来源核验与翻译状态应为布尔值")
        for key in ("is_fragment", "is_duplicate", "misattributed"):
            if type(meta.get(key, False)) is not bool:
                raise ValueError(f"{pid} 的 {key} 须为布尔值")
        reasons = [k for k in ("is_fragment", "is_duplicate", "misattributed") if meta.get(k)]
        if reasons:
            notices.append({"poem_id": pid, "flags": reasons})
        normalized = unicodedata.normalize("NFC", row["text"].replace("\r\n", "\n").replace("\r", "\n"))
        body = "".join(c for c in normalized if c.isalnum())
        if not body:
            raise ValueError(f"{pid} 正文没有文字")
        identity = digest(body)
        if row.get("split") not in (None, "train", "held_out"):
            raise ValueError(f"{pid} 的 split 无效")
        if identity in bodies:
            other = bodies[identity]
            notices.append({"poem_id": pid, "flags": ["same_alphanumeric_body"], "other": other["poem_id"]})
        for key in ("period", "topic"):
            if row.get(key) is not None and not isinstance(row[key], str):
                raise ValueError(f"{pid} 的 {key} 须为字符串")
        poem = {**row, "metadata": meta, "genre": genre, "normalized_text": normalized, "body_hash": identity,
                "copyright": row.get("copyright", "unknown"), "split": row.get("split")}
        bodies.setdefault(identity, poem)
        poems.append(poem)
    return poems, notices


def load_corpus(path):
    path = Path(path)
    if path.suffix.lower() == ".txt":
        with path.open(encoding="utf-8-sig", newline="") as f:
            original = f.read()
        rows = [{"poem_id": path.stem, "source": str(path), "text": original}]
    elif path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    elif path.suffix.lower() == ".json":
        rows = read(path)
    else:
        raise ValueError("支持 UTF-8 的 .txt、.json、.jsonl 文件")
    return clean(rows)
