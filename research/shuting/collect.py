"""Collect the 舒婷 poems on 中华诗库 for local style study.

The source is the single-page 《舒婷诗选》 at shigeku.com (mirrored by
shiku.org and shitan.org). The page holds 35 poems; each begins at an
``<a name="N">`` anchor and carries a trailing composition date. Texts stay
in the gitignored var/ tree and are not redistributed by this repository.

Usage:
    python research/shuting/collect.py fetch [--force] [--delay 1.0]
    python research/shuting/collect.py build [--holdout-fraction 0.1]
    python research/shuting/collect.py report
"""
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "var" / "shuting" / "raw"
PAGES = RAW / "pages"
FETCH_LOG = RAW / "fetch-log.json"
SELECTION = ROOT / "research" / "shuting" / "selection.json"
MANIFEST = ROOT / "research" / "shuting" / "manifest.json"
CORPUS = ROOT / "var" / "shuting" / "corpus.jsonl"
REPORT = ROOT / "research" / "shuting" / "coverage.md"

SOURCE = "https://www.shigeku.com/shiku/xs/shuting.htm"
USER_AGENT = "VerseForge-style-research/1.0 (local corpus; contact repository owner)"
DATE = re.compile(r"^(?:19|20)\d{2}[\d\s.\-—－~/年月日点时凌晨上午下午晚夜至分]{0,24}$")


# --------------------------------------------------------------------------- util

def decode(raw):
    # Pages declare gb2312 but are served as UTF-8; try UTF-8 first.
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", "replace")


def strip_tags(value):
    return unescape(re.sub(r"<[^>]+>", "", value)).replace("\xa0", " ").replace("\u3000", " ").strip()


def cache_name(url):
    name = url.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
    return re.sub(r"[^0-9A-Za-z._-]", "_", name)


def cached(url):
    return PAGES / (cache_name(url) + ".html")


def fetch_one(url, delay):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN"})
    last = None
    for attempt in range(5):
        if attempt:
            time.sleep(delay * (2 ** attempt))
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                final = response.geturl()
            if "服务器太忙".encode("utf-8") in raw or "服务器太忙".encode("gb18030") in raw:
                raise RuntimeError("site busy")
            if len(raw) < 400:
                raise RuntimeError("short response")
            return raw, final
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404:
                raise RuntimeError("permanent 404")
            print("  retry %d: %s" % (attempt + 1, exc), file=sys.stderr)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last = exc
            print("  retry %d: %s" % (attempt + 1, exc), file=sys.stderr)
    raise RuntimeError("fetch failed: %s (%s)" % (url, last))


def fetch_all(delay=1.0, force=False):
    PAGES.mkdir(parents=True, exist_ok=True)
    log = json.loads(FETCH_LOG.read_text(encoding="utf-8")) if FETCH_LOG.exists() else {}
    name = cache_name(SOURCE)
    target = cached(SOURCE)
    if target.exists() and not force:
        print("cached", target)
        return
    print("fetch", SOURCE, file=sys.stderr)
    raw, final = fetch_one(SOURCE, delay)
    target.write_text(decode(raw), encoding="utf-8")
    log[name] = {"url": SOURCE, "snapshot": final, "bytes": len(raw),
                 "sha256": hashlib.sha256(raw).hexdigest(),
                 "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    FETCH_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_cached(url=SOURCE):
    path = cached(url)
    return path.read_text(encoding="utf-8") if path.exists() else None


def source_url(url=SOURCE):
    log = json.loads(FETCH_LOG.read_text(encoding="utf-8")) if FETCH_LOG.exists() else {}
    entry = log.get(cache_name(url), {})
    return entry.get("snapshot") or url, entry.get("fetched_at")


# -------------------------------------------------------------------------- parse

def html_to_text(fragment):
    fragment = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.S | re.I)
    fragment = re.sub(r"\r\n?", "\n", fragment)
    # Each source line ends with "<br />\n  "; that newline is markup, not text.
    fragment = re.sub(r"<br\s*/?>[^\S\r\n]*\r?\n?", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</p\s*>", "\n\n", fragment, flags=re.I)
    fragment = re.sub(r"<p\b[^>]*>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = unescape(fragment).replace("\xa0", " ").replace("\u3000", " ")
    lines, blank = [], 0
    for line in fragment.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        lines.append(line)
    return "\n".join(lines).strip()


def split_date(text):
    """Move a trailing composition date out of the poem body."""
    lines = text.split("\n")
    dates = []
    while lines and (not lines[-1].strip() or DATE.match(lines[-1].strip())):
        line = lines.pop().strip()
        if line:
            dates.insert(0, line)
    return "\n".join(lines).strip(), " ".join(dates) or None


def parse_page(html):
    anchors = list(re.finditer(r'<a name="(\d+)"></a>', html))
    poems = []
    for index, match in enumerate(anchors):
        end = anchors[index + 1].start() if index + 1 < len(anchors) else len(html)
        chunk = html[match.end():end]
        heading = re.search(r"<h2>(.*?)</h2>", chunk, re.S)
        if not heading:
            continue
        raw_title = heading.group(1)
        parts = [strip_tags(part) for part in re.split(r"<br\s*/?>", raw_title)]
        parts = [part for part in parts if part]
        if not parts:
            continue
        title, rest = parts[0], parts[1:]
        has_epigraph = any("题记" in part for part in rest)
        if has_epigraph:
            dedicatory, epigraph = [], rest
        else:
            dedicatory = [part for part in rest if part.startswith("—")]
            epigraph = [part for part in rest if not part.startswith("—")]
        full_title = " ".join([title] + dedicatory)
        body_html = re.split(r"<hr", chunk[heading.end():])[0]
        body = html_to_text(body_html)
        body, date = split_date(body)
        if epigraph:
            body = "\n".join(epigraph + ["", body]).strip()
        poems.append({
            "number": int(match.group(1)),
            "title": full_title,
            "subtitle": " / ".join(epigraph) or None,
            "text": body,
            "date": date,
        })
    return poems


# -------------------------------------------------------------------------- build

def load_selection():
    if not SELECTION.exists():
        return None
    return json.loads(SELECTION.read_text(encoding="utf-8-sig"))


def selection_index(selection):
    table = {}
    if not selection:
        return table
    for item in selection.get("core", []):
        for path in item["paths"]:
            table[str(int(path))] = {"tier": "core", "rank": int(item["id"][1:]),
                           "group": None, "focus": item.get("hypothesis", ""),
                           "features": item.get("features", ""), "title": item["title"]}
    for number, group in enumerate(selection.get("groups", []), 1):
        for work in group["works"]:
            for path in work["paths"]:
                table[str(int(path))] = {"tier": "A", "rank": None,
                               "group": "G%02d %s" % (number, group["label"]),
                               "focus": group.get("focus", ""), "features": "",
                               "title": work["title"]}
    for item in selection.get("long_poems", []):
        for path in item["paths"]:
            table[str(int(path))] = {"tier": item["priority"], "rank": None, "group": "长诗",
                           "focus": item.get("focus", ""), "features": "",
                           "title": item["title"]}
    return table


def build_records(selection):
    html = load_cached()
    if not html:
        raise SystemExit("cache missing; run fetch first")
    table = selection_index(selection)
    snapshot, fetched_at = source_url()
    rows = []
    for poem in parse_page(html):
        key = "%02d" % poem["number"]
        info = table.get(str(poem["number"]), {"tier": "B", "rank": None, "group": "未分组",
                               "focus": "", "features": "", "title": poem["title"]})
        rows.append({
            "poem_id": "shuting-" + key,
            "title": poem["title"],
            "text": poem["text"],
            "source": "中华诗库·舒婷诗选网页（shigeku.com，镜像 shiku.org / shitan.org）",
            "source_url": snapshot,
            "genre": "modern",
            "period": None,
            "metadata": {
                "source_verified": True, "is_translation": False,
                "is_fragment": False, "is_duplicate": False, "misattributed": False,
                "book": "舒婷诗选（网页汇编）", "editor": None,
                "catalog_path": "#" + key,
                "catalog_title": poem["title"],
                "selection_title": info["title"],
                "page_title": poem["title"],
                "tier": info["tier"], "core_rank": info["rank"],
                "group": info["group"], "focus": info["focus"],
                "style_features": info["features"],
                "subtitle": poem["subtitle"],
                "chapter_count": None, "chapters_fetched": None, "chapters_complete": None,
                "composed": poem["date"],
                "fetched_at": fetched_at,
            },
            "copyright": "third_party_copyright",
            "split": None,
        })
    return rows


def apply_split(rows, fraction):
    for row in rows:
        bucket = int(hashlib.sha256(row["poem_id"].encode()).hexdigest()[:8], 16) % 100
        row["split"] = "held_out" if bucket < round(fraction * 100) else "train"


def build(holdout_fraction=0.1):
    rows = [row for row in build_records(load_selection()) if row["text"].strip()]
    seen = {}
    for row in rows:
        body = "".join(c for c in row["text"] if c.isalnum())
        identity = hashlib.sha256(body.encode()).hexdigest()
        if identity in seen:
            row["metadata"]["is_duplicate"] = True
            row["metadata"]["duplicate_of"] = seen[identity]
        else:
            seen[identity] = row["poem_id"]
    apply_split(rows, holdout_fraction)
    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    CORPUS.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    MANIFEST.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection": str(SELECTION.relative_to(ROOT)) if SELECTION.exists() else None,
        "corpus": str(CORPUS.relative_to(ROOT)),
        "count": len(rows), "holdout_fraction": holdout_fraction,
        "rights": "舒婷作品权利归作者及出版方；全文仅存于本地 var/，不随仓库分发。",
        "unavailable": [],
        "records": [{k: row[k] for k in ("poem_id", "title", "period", "split")}
                    | {"tier": row["metadata"]["tier"], "core_rank": row["metadata"]["core_rank"],
                       "group": row["metadata"]["group"], "catalog_path": row["metadata"]["catalog_path"],
                       "composed": row["metadata"]["composed"],
                       "source_url": row["source_url"], "lines": len(row["text"].splitlines())}
                    for row in rows],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", len(rows), "records to", CORPUS)


# ------------------------------------------------------------------------- report

def report():
    from collections import Counter
    rows = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    splits = Counter(str(r["split"]) for r in rows)
    groups = Counter(r["metadata"]["group"] for r in rows)
    core = [r for r in rows if r["metadata"]["tier"] == "core"]
    dated = [r for r in rows if r["metadata"]["composed"]]
    lines = ["# 舒婷语料收集报告", "",
             "生成时间：%s" % datetime.now(timezone.utc).isoformat(timespec="seconds"), "",
             "来源：中华诗库《舒婷诗选》单页（[shigeku.com](%s)）。" % SOURCE,
             "网页共 35 首，逐首按锚点切分，诗末日期另存于 `metadata.composed`。",
             "全文只保存在 gitignored 的 `var/shuting/`，不随仓库分发。",
             "", "## 总数", "",
             "| 项目 | 数量 |", "|---|---|",
             "| 收录条目 | %d |" % len(rows),
             "| 核心篇目 | %d |" % len(core),
             "| 含有创作日期 | %d |" % len(dated),
             "| 训练集 | %d |" % splits.get("train", 0),
             "| 留出集 | %d |" % splits.get("held_out", 0),
             "", "## 核心篇目", "", "| 序号 | 标题 | 行数 | 创作时间 | 锚点 |", "|---|---|---|---|---|"]
    for row in sorted(core, key=lambda r: r["metadata"]["core_rank"]):
        lines.append("| %02d | %s | %d | %s | %s |" % (
            row["metadata"]["core_rank"], row["title"], len(row["text"].splitlines()),
            row["metadata"]["composed"] or "未注明", row["metadata"]["catalog_path"]))
    lines += ["", "## 风格子库", "", "| 子库 | 篇数 |", "|---|---|"]
    for name, count in sorted(((k, v) for k, v in groups.items() if k), key=lambda x: str(x[0])):
        lines.append("| %s | %d |" % (name, count))
    lines += ["", "## 已知缺口", "",
              "中华诗库的《舒婷诗选》只收 35 首，未收《致橡树》《双桅船》《会唱歌的鸢尾花》",
              "等代表作；本目录因此不能代表舒婷创作全貌。补足需另找可核对的来源，",
              "在 `selection.json` 中新增条目后重跑 build。",
              "", "## 说明", "",
              "- 标题、正文与日期取自网页，未与纸本逐字校勘；异文应以《舒婷的诗》等印本复核。",
              "- 组诗或含题记的篇目，题记保留在正文之前，标题与副题记入 `metadata.subtitle`。",
              "- 作品权利归舒婷及出版方；本仓库不分发全文。"]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", REPORT)


def main(argv=None):
    parser = argparse.ArgumentParser(description="收集中华诗库《舒婷诗选》研究语料")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="下载单页全文")
    fetch.add_argument("--force", action="store_true")
    fetch.add_argument("--delay", type=float, default=1.0)
    build_cmd = sub.add_parser("build", help="解析缓存并生成 JSONL 语料")
    build_cmd.add_argument("--holdout-fraction", type=float, default=0.1)
    sub.add_parser("report", help="生成覆盖报告")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch_all(args.delay, args.force)
    elif args.command == "build":
        build(args.holdout_fraction)
    else:
        report()


if __name__ == "__main__":
    main()
