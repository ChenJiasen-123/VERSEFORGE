"""Collect the 北岛 poems listed on 中华诗库 for local style study.

The source is the indexed 《北岛诗集》 at shigeku.com, which mirrors the same
database as shiku.org and shitan.org. Texts stay in the gitignored var/ tree;
they are the property of the author and publishers and are not redistributed
by this repository.

Usage:
    python research/beidao/collect.py fetch [--force] [--delay 1.0] [--limit N]
    python research/beidao/collect.py build [--holdout-fraction 0.1]
    python research/beidao/collect.py report
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
RAW = ROOT / "var" / "beidao" / "raw"
PAGES = RAW / "pages"
FETCH_LOG = RAW / "fetch-log.json"
SELECTION = ROOT / "research" / "beidao" / "selection.json"
MANIFEST = ROOT / "research" / "beidao" / "manifest.json"
CORPUS = ROOT / "var" / "beidao" / "corpus.jsonl"
REPORT = ROOT / "research" / "beidao" / "coverage.md"
CATALOG = PAGES / "beidao_index.html"

SOURCE = "https://www.shigeku.com/shiku/xs/beidao/"
INDEX_URL = SOURCE + "index.htm"
USER_AGENT = "VerseForge-style-research/1.0 (local corpus; contact repository owner)"
NAV = {"上一页", "下一页", "回目录", "封面", "阅读", "北岛诗集"}


# --------------------------------------------------------------------------- plan

def decode(raw):
    # Pages declare gb2312 but are served as UTF-8; try UTF-8 first.
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", "replace")


def strip_tags(value):
    return unescape(re.sub(r"<[^>]+>", "", value)).replace("\u3000", " ").strip()


def catalog():
    """Return [{'path','title','section'}] in index order.

    Section headings sit between anchors in the <pre> block, for example
    ``一、（1972-1986）``. Poems that follow inherit the latest heading.
    """
    html = CATALOG.read_text(encoding="utf-8")
    block = re.search(r"<pre>(.*?)</pre>", html, re.S)
    segment = block.group(1) if block else html
    rows, section = [], None
    token = re.compile(
        r"<a name=\"[^\"]*\"></a>|"
        r"<a href=\"(\d{3})\.htm\">(.*?)</a>|"
        r"([\u4e00-\u9fa5]+、（[^）]*）|[\u4e00-\u9fa5]+、)",
        re.S,
    )
    for match in token.finditer(segment):
        if match.group(1):
            path = match.group(1)
            if path == "000":  # 诗人简介, not a poem
                continue
            rows.append({"path": path, "title": strip_tags(match.group(2)), "section": section})
        elif match.group(3):
            section = strip_tags(match.group(3))
    return rows


def poem_url(path):
    return SOURCE + path + ".htm"


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


def fetch_all(delay=1.0, force=False, limit=None):
    PAGES.mkdir(parents=True, exist_ok=True)
    log = json.loads(FETCH_LOG.read_text(encoding="utf-8")) if FETCH_LOG.exists() else {}
    if not CATALOG.exists() or force:
        print("fetch", INDEX_URL, file=sys.stderr)
        raw, final = fetch_one(INDEX_URL, delay)
        CATALOG.write_text(decode(raw), encoding="utf-8")
        log[cache_name(INDEX_URL)] = {"url": INDEX_URL, "snapshot": final, "bytes": len(raw),
                                      "sha256": hashlib.sha256(raw).hexdigest(),
                                      "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        FETCH_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        time.sleep(delay)
    queue = [(row["path"], poem_url(row["path"])) for row in catalog()]
    done = 0
    for path, url in queue:
        name = cache_name(url)
        target = cached(url)
        if not force and log.get(name, {}).get("error") == "permanent 404":
            continue
        if target.exists() and not force:
            done += 1
            continue
        print("fetch", url, file=sys.stderr)
        try:
            raw, final = fetch_one(url, delay)
        except RuntimeError as exc:
            print("FAILED", url, exc, file=sys.stderr)
            log[name] = {"url": url, "error": str(exc),
                         "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            FETCH_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            time.sleep(delay)
            continue
        target.write_text(decode(raw), encoding="utf-8")
        log[name] = {"url": url, "snapshot": final, "bytes": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest(),
                     "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        FETCH_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        done += 1
        if limit and done >= limit:
            print("stopping at --limit", limit, file=sys.stderr)
            return
        time.sleep(delay)


# -------------------------------------------------------------------------- parse

def html_to_text(fragment):
    fragment = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.S | re.I)
    fragment = re.sub(r"\r\n?", "\n", fragment)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</p\s*>", "\n\n", fragment, flags=re.I)
    fragment = re.sub(r"<p\b[^>]*>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = unescape(fragment).replace("\xa0", " ").replace("\u3000", " ")
    lines, blank = [], 0
    for line in fragment.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).rstrip()
        if not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        lines.append(line)
    return "\n".join(lines).strip()


def parse_page(html):
    title = re.search(r"<h1>(.*?)</h1>", html, re.S)
    section = re.search(r'<p align="center">（<a href="index\.htm#[^"]*">(.*?)</a>）', html, re.S)
    body = re.search(r"<pre>(.*?)</pre>", html, re.S)
    if not body:
        raise ValueError("no <pre> body")
    return {
        "title": strip_tags(title.group(1)) if title else "",
        "section": strip_tags(section.group(1)).split("::")[-1] if section else "",
        "text": html_to_text(body.group(1)),
    }


def load_cached(url):
    path = cached(url)
    return path.read_text(encoding="utf-8") if path.exists() else None


def source_url(url):
    log = json.loads(FETCH_LOG.read_text(encoding="utf-8")) if FETCH_LOG.exists() else {}
    entry = log.get(cache_name(url), {})
    return entry.get("snapshot") or url, entry.get("fetched_at")


# -------------------------------------------------------------------------- build

def load_selection():
    if not SELECTION.exists():
        return None
    return json.loads(SELECTION.read_text(encoding="utf-8-sig"))


def selection_index(selection):
    """Map catalog path -> (tier, rank, group, focus, features, title)."""
    table = {}
    if not selection:
        return table
    for item in selection.get("core", []):
        for path in item["paths"]:
            table[path] = {"tier": "core", "rank": int(item["id"][1:]),
                           "group": None, "focus": item.get("hypothesis", ""),
                           "features": item.get("features", ""), "title": item["title"]}
    for number, group in enumerate(selection.get("groups", []), 1):
        for work in group["works"]:
            for path in work["paths"]:
                table[path] = {"tier": "A", "rank": None,
                               "group": "G%02d %s" % (number, group["label"]),
                               "focus": group.get("focus", ""), "features": "",
                               "title": work["title"]}
    for item in selection.get("long_poems", []):
        for path in item["paths"]:
            table[path] = {"tier": item["priority"], "rank": None, "group": "长诗",
                           "focus": item.get("focus", ""), "features": "",
                           "title": item["title"]}
    return table


def build_records(selection):
    table = selection_index(selection)
    rows = []
    for item in catalog():
        url = poem_url(item["path"])
        html = load_cached(url)
        if html is None:
            print("MISSING cached page:", url, file=sys.stderr)
            continue
        parsed = parse_page(html)
        info = table.get(item["path"], {"tier": "B", "rank": None, "group": "未分组",
                                        "focus": "", "features": "", "title": item["title"]})
        if parsed["title"] and info["title"] not in parsed["title"] and parsed["title"] not in info["title"]:
            print("title mismatch:", item["path"], info["title"], "vs", parsed["title"], file=sys.stderr)
        snapshot, fetched_at = source_url(url)
        rows.append({
            "poem_id": "beidao-" + item["path"],
            "title": parsed["title"] or info["title"],
            "text": parsed["text"],
            "source": "中华诗库·北岛诗集网页（shigeku.com，镜像 shiku.org / shitan.org）",
            "source_url": snapshot,
            "genre": "modern",
            "period": parsed["section"] or None,
            "metadata": {
                "source_verified": True, "is_translation": False,
                "is_fragment": any(w in (item["title"] or "") for w in ("残稿", "断片", "片段")),
                "is_duplicate": False, "misattributed": False,
                "book": "北岛诗集（网页汇编）", "editor": None,
                "catalog_path": "/" + item["path"],
                "catalog_title": item["title"],
                "selection_title": info["title"],
                "page_title": parsed["title"],
                "tier": info["tier"], "core_rank": info["rank"],
                "group": info["group"], "focus": info["focus"],
                "style_features": info["features"],
                "chapter_count": None, "chapters_fetched": None, "chapters_complete": None,
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
    selection = load_selection()
    rows = [row for row in build_records(selection) if row["text"].strip()]
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
    index = {row["metadata"]["catalog_path"].lstrip("/"): row for row in rows}
    unavailable = [{"path": item["path"], "title": item["title"]}
                   for item in catalog() if item["path"] not in index]
    MANIFEST.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection": str(SELECTION.relative_to(ROOT)) if SELECTION.exists() else None,
        "corpus": str(CORPUS.relative_to(ROOT)),
        "count": len(rows), "holdout_fraction": holdout_fraction,
        "rights": "北岛作品权利归作者及出版方；全文仅存于本地 var/，不随仓库分发。",
        "unavailable": unavailable,
        "records": [{k: row[k] for k in ("poem_id", "title", "period", "split")}
                    | {"tier": row["metadata"]["tier"], "core_rank": row["metadata"]["core_rank"],
                       "group": row["metadata"]["group"], "catalog_path": row["metadata"]["catalog_path"],
                       "source_url": row["source_url"], "lines": len(row["text"].splitlines())}
                    for row in rows],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", len(rows), "records to", CORPUS)


# ------------------------------------------------------------------------- report

def report():
    from collections import Counter
    rows = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tiers = Counter(r["metadata"]["tier"] for r in rows)
    splits = Counter(str(r["split"]) for r in rows)
    groups = Counter(r["metadata"]["group"] for r in rows)
    periods = Counter(str(r["period"]) for r in rows)
    core = [r for r in rows if r["metadata"]["tier"] == "core"]
    lines = ["# 北岛语料收集报告", "",
             "生成时间：%s" % datetime.now(timezone.utc).isoformat(timespec="seconds"), "",
             "来源：中华诗库《北岛诗集》目录（[shigeku.com](%s)），按网页分节编号逐篇取回。" % SOURCE,
             "全文只保存在 gitignored 的 `var/beidao/`，不随仓库分发。",
             "", "## 总数", "",
             "| 项目 | 数量 |", "|---|---|",
             "| 收录条目 | %d |" % len(rows),
             "| 核心 %d 首选录 | %d / %d |" % (len(core), len(core), len(core)),
             "| 训练集 | %d |" % splits.get("train", 0),
             "| 留出集 | %d |" % splits.get("held_out", 0),
             "| 未取回 | %d |" % len(manifest["unavailable"]),
             "", "## 分节", "", "| 编次 | 篇数 |", "|---|---|"]
    for name, count in sorted(periods.items()):
        lines.append("| %s | %d |" % (name, count))
    lines += ["", "## 核心篇目", "", "| 序号 | 标题 | 行数 | 目录路径 |", "|---|---|---|---|"]
    for row in sorted(core, key=lambda r: r["metadata"]["core_rank"]):
        lines.append("| %02d | %s | %d | %s |" % (
            row["metadata"]["core_rank"], row["title"],
            len(row["text"].splitlines()), row["metadata"]["catalog_path"]))
    lines += ["", "## 风格子库", "", "| 子库 | 篇数 |", "|---|---|"]
    for name, count in sorted(((k, v) for k, v in groups.items() if k and k != "长诗"), key=lambda x: str(x[0])):
        lines.append("| %s | %d |" % (name, count))
    longs = [r for r in rows if r["metadata"]["group"] == "长诗"]
    if longs:
        lines += ["", "## 长诗", "", "| 作品 | 优先级 | 行数 |", "|---|---|---|"]
        for row in longs:
            lines.append("| %s | %s | %d |" % (row["title"], row["metadata"]["tier"], len(row["text"].splitlines())))
    if manifest["unavailable"]:
        lines += ["", "### 未取回条目", ""]
        for item in manifest["unavailable"]:
            lines.append("- %s（%s）" % (item["title"], item["path"]))
    lines += ["", "## 说明", "",
              "- 标题、分节与正文取自网页，未与纸本逐字校勘；异文应以《北岛诗选》等印本复核。",
              "- 同名诗作按目录编号分条保留。",
              "- `tier=B` 为未进入核心或风格子库的其余篇目，组别记为「未分组」，仍纳入语料。",
              "- 作品权利归北岛及出版方；本仓库不分发全文。"]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", REPORT)


def main(argv=None):
    parser = argparse.ArgumentParser(description="收集中华诗库《北岛诗集》研究语料")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="下载目录与各篇页面")
    fetch.add_argument("--force", action="store_true")
    fetch.add_argument("--delay", type=float, default=1.0)
    fetch.add_argument("--limit", type=int)
    build_cmd = sub.add_parser("build", help="解析缓存并生成 JSONL 语料")
    build_cmd.add_argument("--holdout-fraction", type=float, default=0.1)
    sub.add_parser("report", help="生成覆盖报告")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch_all(args.delay, args.force, args.limit)
    elif args.command == "build":
        build(args.holdout_fraction)
    else:
        report()


if __name__ == "__main__":
    main()
