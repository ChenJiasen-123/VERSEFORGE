"""Collect the 《海子诗全编》 texts named in selection.json for local style study.

The catalog snapshot in var/haizi/raw/catalog.html points at eywedu.com, which is
offline; the same pages are fetched from Internet Archive snapshots. Downloaded
texts stay in the gitignored var/ tree. They are the property of the author,
editor and publisher and are not redistributed by this repository.

Usage:
    python research/haizi/collect.py fetch [--force] [--delay 1.0] [--limit N]
    python research/haizi/collect.py build [--holdout-fraction 0.1]
    python research/haizi/collect.py report
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
RAW = ROOT / "var" / "haizi" / "raw"
PAGES = RAW / "pages"
FETCH_LOG = RAW / "fetch-log.json"
CATALOG = RAW / "catalog.html"
SELECTION = ROOT / "research" / "haizi" / "selection.json"
MANIFEST = ROOT / "research" / "haizi" / "manifest.json"
CORPUS = ROOT / "var" / "haizi" / "corpus.jsonl"
REPORT = ROOT / "research" / "haizi" / "coverage.md"

WAYBACK = "https://web.archive.org/web/2015id_/http://www.eywedu.com:80/haizi/"
SHITAN = "https://www.shitan.org/shiku/xs/haizi/"
USER_AGENT = "VerseForge-style-research/1.0 (local corpus; contact repository owner)"


# --------------------------------------------------------------------------- plan

def catalog_titles():
    html = CATALOG.read_text(encoding="utf-8-sig")
    titles = {}
    for href, title in re.findall(r"<a href='(/[^']*)'>(.*?)</a>", html, re.S):
        if not re.match(r"^/0[1-4]/", href):
            continue
        text = re.sub(r"<[^>]+>", "", title)
        text = unescape(text).replace("　", " ").strip()
        titles[href.lstrip("/")] = text
    return titles


def selection_entries():
    sel = json.loads(SELECTION.read_text(encoding="utf-8-sig"))
    entries = []
    for item in sel["core"]:
        entries.append({
            "work_id": "core-%02d" % int(item["id"][1:]),
            "title": item["title"], "tier": "core", "rank": int(item["id"][1:]),
            "group": None, "focus": item.get("hypothesis", ""),
            "features": item.get("features", ""), "paths": item["paths"],
        })
    for number, group in enumerate(sel["groups"], 1):
        for index, work in enumerate(group["works"], 1):
            entries.append({
                "work_id": "g%02d-%02d" % (number, index),
                "title": work["title"], "tier": "A", "rank": None,
                "group": "G%02d %s" % (number, group["label"]),
                "focus": group["focus"], "features": "", "paths": work["paths"],
            })
    for item in sel["long_poems"]:
        entries.append({
            "work_id": "long-%s-%s" % (item["priority"].lower(), _slug(item["title"])),
            "title": item["title"], "tier": item["priority"], "rank": None,
            "group": "长诗", "focus": item.get("focus", ""),
            "features": "", "paths": item["paths"],
        })
    return entries


def _slug(text):
    return re.sub(r"[^0-9a-z]+", "-", text.lower()).strip("-") or "work"


def path_to_id(path, titles):
    if path.startswith("http"):
        return "shitan-" + path.rsplit("/", 1)[-1].replace(".htm", "")
    return "haizi-" + path.replace("/", "-")


def plan():
    titles = catalog_titles()
    rows = []
    for entry in selection_entries():
        for path in entry["paths"]:
            rows.append({
                "poem_id": path_to_id(path, titles),
                "work_id": entry["work_id"], "title": entry["title"],
                "catalog_title": titles.get(path.lstrip("/")),
                "tier": entry["tier"], "rank": entry["rank"], "group": entry["group"],
                "focus": entry["focus"], "features": entry["features"],
                "path": path, "source": "shitan" if path.startswith("http") else "eywedu",
            })
    return rows


# -------------------------------------------------------------------------- fetch

def page_url(rel):
    return WAYBACK + rel + ".htm"


def fetch_one(url, delay):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN"})
    last = None
    for attempt in range(5):
        if attempt:
            time.sleep(delay * (2 ** attempt))
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
                final = response.geturl()
            if b"Temporarily Offline" in raw or (b"<title>Wayback Machine</title>" in raw and b"eywedu" not in raw):
                raise RuntimeError("archive returned an outage page")
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


def decode(raw):
    for encoding in ("gb18030", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", "replace")


def cache_name(url):
    name = url.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
    return re.sub(r"[^0-9A-Za-z._-]", "_", name)


def cached(name):
    return PAGES / (name + ".html")


def fetch_all(delay=1.0, force=False, limit=None):
    PAGES.mkdir(parents=True, exist_ok=True)
    log = json.loads(FETCH_LOG.read_text(encoding="utf-8")) if FETCH_LOG.exists() else {}
    queue = []
    for row in plan():
        if row["source"] == "shitan":
            queue.append((row["poem_id"], row["path"]))
        else:
            queue.append((row["poem_id"], page_url(row["path"])))
    # Long works need their chapter pages; discover them from the index page.
    done = 0
    while queue:
        poem_id, url = queue.pop(0)
        name = cache_name(url)
        target = cached(name)
        if not force and log.get(name, {}).get("error") == "permanent 404":
            continue
        if target.exists() and not force:
            html = target.read_text(encoding="utf-8")
        else:
            print("fetch", url, file=sys.stderr)
            try:
                raw, final = fetch_one(url, delay)
            except RuntimeError as exc:
                # Some pages were never crawled; record the hole and keep going.
                print("FAILED", url, exc, file=sys.stderr)
                log[name] = {"url": url, "error": str(exc),
                             "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                FETCH_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                time.sleep(delay)
                continue
            html = decode(raw)
            target.write_text(html, encoding="utf-8")
            log[name] = {"url": url, "snapshot": final, "bytes": len(raw),
                         "sha256": hashlib.sha256(raw).hexdigest(),
                         "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            FETCH_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            time.sleep(delay)
        done += 1
        if limit and done >= limit:
            print("stopping at --limit", limit, file=sys.stderr)
            return
        for href, text in chapter_links(html):
            if href.startswith("http"):
                child = href
            else:
                child = url.rsplit("/", 1)[0] + "/" + href
            if child not in [u for _, u in queue]:
                queue.append((poem_id + "-chapter-" + re.sub(r"\W", "", href), child))


# -------------------------------------------------------------------------- parse

TITLE_BLOCK = re.compile(r'class="style3"[^>]*>(.*?)</(?:div|span)>', re.S)
SECTION = re.compile(r'<div align="right">\s*〖(.*?)〗')
DATE = re.compile(r"^(?:19|20)\d{2}[\d\s.\-—－~/年月日点时凌晨上午下午晚夜至分]{0,24}$")
NAV = {"上一页", "下一页", "回目录", "封面", "阅读", "海子诗集"}


def strip_tags(value):
    return unescape(re.sub(r"<[^>]+>", "", value)).replace("　", " ").strip()


def div_bounds(html, position):
    start = html.rfind("<div", 0, position)
    if start == -1:
        return None
    depth = 0
    for match in re.finditer(r"<div\b[^>]*>|</div\s*>", html[start:], re.I):
        if match.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                return start, start + match.end()
        else:
            depth += 1
    return None


def enclosing_div(html, position):
    bounds = div_bounds(html, position)
    return html[bounds[0]:bounds[1]] if bounds else None


def title_of(html):
    match = TITLE_BLOCK.search(html)
    if not match:
        return None
    # Take the whole centered title div so that subtitles survive, but keep
    # each span/strong block separate rather than welding them together.
    raw = enclosing_div(html, match.start()) or match.group(1)
    parts = []
    for block in re.split(r"</(?:span|strong|div)>|<br\s*/?>", raw):
        block = re.sub(r"\s*\n\s*", "", strip_tags(block))
        block = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", block)
        block = re.sub(r"\s*\*\s*", "", block).strip()
        if block:
            parts.append(block)
    return " ".join(parts).strip() or None


def section_of(html):
    match = SECTION.search(html)
    return strip_tags(match.group(1)) if match else None


def content_segment(html):
    """Everything between the title table and the prev/next navigation table."""
    title = TITLE_BLOCK.search(html)
    if title:
        bounds = div_bounds(html, title.start())
        segment = html[bounds[1]:] if bounds else html[title.end():]
    else:
        # Chapter pages title themselves with style10 or have no heading at
        # all; both cases must skip the sidebar and breadcrumb table.
        sub = re.search(r'class="style10"[^>]*>', html)
        if sub:
            bounds = div_bounds(html, sub.start())
            segment = html[bounds[1]:] if bounds else html[sub.end():]
        else:
            start = html.find("<blockquote")
            segment = html[start:] if start != -1 else html
    for marker in ('<p align="right">', "上一页", "回目录"):
        index = segment.find(marker)
        if index != -1:
            table = segment.rfind("<table", 0, index)
            return segment[:table] if table != -1 else segment[:index]
    return segment


def html_to_text(fragment):
    fragment = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.S | re.I)
    # Source newlines are HTML whitespace; keeping them would double every <br>.
    fragment = re.sub(r"\s*\n\s*", " ", fragment)
    fragment = re.sub(r"<span[^>]*class=\"style8\"[^>]*>(.*?)</span>",
                      lambda match: "\n【%s】\n" % strip_tags(match.group(1)), fragment, flags=re.S)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</p\s*>", "\n\n", fragment, flags=re.I)
    fragment = re.sub(r"<p\b[^>]*>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = unescape(fragment)
    fragment = fragment.replace("\xa0", " ").replace("　", " ")
    lines, blank = [], 0
    for line in fragment.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        lines.append(line)
    return "\n".join(lines).strip()


def chapter_links(html):
    if not TITLE_BLOCK.search(html):
        return []  # shitan.org pages have no chapter structure
    fragment = content_segment(html)
    links = []
    for href, text in re.findall(r'<a href="([^"]+)"[^>]*>(.*?)</a>', fragment, re.S):
        label = strip_tags(text).replace("¤", "").strip()
        if not href.endswith(".htm") or label in NAV or not label or "&lt;" in text:
            continue
        links.append((href, label))
    return links


def split_date(text):
    """Move a trailing composition date out of the poem body."""
    lines = text.split("\n")
    dates = []
    while lines and (not lines[-1].strip() or DATE.match(lines[-1].strip())):
        line = lines.pop().strip()
        if line:
            dates.insert(0, line)
    return "\n".join(lines).strip(), " ".join(dates) or None


def shitan_page(html):
    title = re.search(r"<h1>(.*?)</h1>", html, re.S)
    body = re.search(r"<pre>(.*?)</pre>", html, re.S)
    if not title or not body:
        raise ValueError("unrecognised shitan page")
    text = unescape(re.sub(r"<[^>]+>", "", body.group(1))).replace("\xa0", " ")
    lines = [line.rstrip() for line in text.split("\n")]
    kept, blank = [], 0
    for line in lines:
        if not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        kept.append(line)
    return {"title": strip_tags(title.group(1)), "section": "", "text": "\n".join(kept).strip(),
            "date": None, "chapters": []}


def parse_page(html):
    if not TITLE_BLOCK.search(html) and "<pre>" in html:
        return shitan_page(html)
    title = title_of(html) or ""
    section = section_of(html) or ""
    body = html_to_text(content_segment(html))
    body, date = split_date(body)
    return {"title": title, "section": section, "text": body, "date": date,
            "chapters": chapter_links(html)}


def load_cached(url):
    path = cached(cache_name(url))
    return path.read_text(encoding="utf-8") if path.exists() else None


# -------------------------------------------------------------------------- build

def source_url(url):
    log = json.loads(FETCH_LOG.read_text(encoding="utf-8")) if FETCH_LOG.exists() else {}
    entry = log.get(cache_name(url), {})
    return entry.get("snapshot") or url, entry.get("fetched_at")


def build_records():
    rows = []
    for item in plan():
        url = item["path"] if item["source"] == "shitan" else page_url(item["path"])
        html = load_cached(url)
        if html is None:
            print("MISSING cached page:", url, file=sys.stderr)
            continue
        parsed = parse_page(html)
        if parsed["title"] and item["title"] not in parsed["title"] and parsed["title"] not in item["title"]:
            print("title mismatch:", item["poem_id"], item["title"], "vs", parsed["title"], file=sys.stderr)
        chapters = parsed["chapters"]
        body, front, complete = parsed["text"], None, None
        if chapters:
            front = parsed["text"]
            parts, fetched = [], 0
            for href, label in chapters:
                child = href if href.startswith("http") else url.rsplit("/", 1)[0] + "/" + href
                child_html = load_cached(child)
                if child_html is None:
                    print("MISSING chapter:", child, file=sys.stderr)
                    continue
                chapter = parse_page(child_html)
                parts.append("【%s】\n\n%s" % (label, chapter["text"]))
                fetched += 1
            body = "\n\n".join(parts)
            complete = fetched == len(chapters)
        snapshot, fetched_at = source_url(url)
        record = {
            "poem_id": item["poem_id"],
            "title": parsed["title"] or item["title"],
            "selection_title": item["title"],
            "text": body,
            "source": "海子诗全编（西川编，上海三联书店1997）网页版，Internet Archive 快照" if item["source"] == "eywedu" else "中华诗库·海子诗集网页",
            "source_url": snapshot,
            "genre": "modern",
            "period": parsed["section"] or None,
            "metadata": {
                "source_verified": True, "is_translation": False,
                "is_fragment": any(w in (item["catalog_title"] or "") for w in ("残稿", "断片", "片段"))
                              or (bool(chapters) and not complete),
                "is_duplicate": False, "misattributed": False,
                "book": "海子诗全编", "editor": "西川",
                "catalog_path": "/" + item["path"],
                "catalog_title": item["catalog_title"],
                "selection_title": item["title"],
                "page_title": parsed["title"],
                "tier": item["tier"], "core_rank": item["rank"],
                "group": item["group"], "focus": item["focus"],
                "style_features": item["features"],
                "composed": parsed["date"],
                "chapter_count": len(chapters) or None,
                "chapters_fetched": sum(1 for part in parts if part) if chapters else None,
                "chapters_complete": complete,
                "front_matter": front,
                "fetched_at": fetched_at,
            },
            "copyright": "third_party_copyright",
            "split": None,
        }
        rows.append(record)
    return rows


def apply_split(rows, fraction):
    for row in rows:
        bucket = int(hashlib.sha256(row["poem_id"].encode()).hexdigest()[:8], 16) % 100
        row["split"] = "held_out" if bucket < round(fraction * 100) else "train"


def build(holdout_fraction=0.1):
    rows = build_records()
    rows = [row for row in rows if row["text"].strip()]
    for row in rows:
        row.pop("selection_title", None)  # recorded in metadata; keep the row schema narrow
        if row["metadata"].get("front_matter"):
            row["metadata"]["front_matter"] = row["metadata"]["front_matter"][:4000]
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
    present = {row["metadata"]["catalog_path"].lstrip("/") for row in rows}
    unavailable = []
    for item in selection_entries():
        missing = [path for path in item["paths"] if not path.startswith("http") and path.lstrip("/") not in present]
        if missing:
            unavailable.append({"work_id": item["work_id"], "title": item["title"],
                                "tier": item["tier"], "paths": missing})
    MANIFEST.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection": str(SELECTION.relative_to(ROOT)),
        "corpus": str(CORPUS.relative_to(ROOT)),
        "count": len(rows), "holdout_fraction": holdout_fraction,
        "rights": "海子作品及《海子诗全编》编选内容的权利归海子、西川及出版方；全文仅存于本地 var/，不随仓库分发。",
        "unavailable": unavailable,
        "records": [{k: row[k] for k in ("poem_id", "title", "period", "split")}
                    | {"tier": row["metadata"]["tier"], "core_rank": row["metadata"]["core_rank"],
                       "group": row["metadata"]["group"], "catalog_path": row["metadata"]["catalog_path"],
                       "chapter_count": row["metadata"]["chapter_count"],
                       "chapters_fetched": row["metadata"]["chapters_fetched"],
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
    longs = [r for r in rows if r["metadata"]["group"] == "长诗"]
    core = [r for r in rows if r["metadata"]["tier"] == "core"]
    a_tier = [r for r in rows if r["metadata"]["tier"] == "A" and r["metadata"]["group"] != "长诗"]
    lines = ["# 海子语料收集报告", "",
             "生成时间：%s" % datetime.now(timezone.utc).isoformat(timespec="seconds"), "",
             "来源：`research/haizi/selection.json` 指定的《海子诗全编》目录；正文取自 Internet Archive 的",
             "`www.eywedu.com/haizi/` 快照（多数为 2015—2016 年）。少量条目以中华诗库",
             "（shitan.org）网页补足。全文只保存在 gitignored 的 `var/haizi/`，不随仓库分发。",
             "",
             "## 总数", "",
             "| 项目 | 数量 |", "|---|---|",
             "| 收录条目 | %d |" % len(rows),
             "| 核心 30 首选录 | %d / %d |" % (len({r["metadata"]["core_rank"] for r in core}), 30),
             "| A 级子库选录 | %d |" % len(a_tier),
             "| 长诗（tier=S/A） | %d |" % len(longs),
             "| 训练集 | %d |" % splits.get("train", 0),
             "| 留出集 | %d |" % splits.get("held_out", 0),
             "", "## 核心 30 首核对", "",
             "| 序号 | 标题 | 篇名（网页） | 行数 | 目录路径 |", "|---|---|---|---|---|"]
    for row in sorted(core, key=lambda r: r["metadata"]["core_rank"]):
        lines.append("| %02d | %s | %s | %d | %s |" % (
            row["metadata"]["core_rank"], row["metadata"]["selection_title"] or row["title"],
            row["title"], len(row["text"].splitlines()), row["metadata"]["catalog_path"]))
    lines += ["", "## 十个风格子库", "", "| 子库 | 篇数 |", "|---|---|"]
    for name, count in sorted(((k, v) for k, v in groups.items() if k and k != "长诗"), key=lambda x: x[0]):
        lines.append("| %s | %d |" % (name, count))
    lines += ["", "## 长诗覆盖", "", "| 作品 | 优先级 | 已取章节 | 正文行数 |", "|---|---|---|---|"]
    for row in sorted(longs, key=lambda r: r["metadata"]["tier"]):
        meta = row["metadata"]
        coverage = "%s / %s" % (meta["chapters_fetched"], meta["chapter_count"]) if meta["chapter_count"] else "整篇"
        lines.append("| %s | %s | %s | %d |" % (row["title"], meta["tier"], coverage, len(row["text"].splitlines())))
    if manifest["unavailable"]:
        lines += ["", "### 未能取回的长诗", "",
                  "以下长诗在 Internet Archive 中只有目录页，章节页未被归档，本仓库未收录正文：", ""]
        for item in manifest["unavailable"]:
            lines.append("- %s（%s，%s）" % (item["title"], item["tier"], "、".join(item["paths"])))
    lines += ["", "## 说明", "",
              "- 长诗按目录页章节逐页取回后拼接，章题以【】标出。",
              "- 同名作品按目录路径分条，保留多个版本。",
              "- 作品权利归海子、西川及出版方；本仓库不分发全文。",
              "- `source_verified` 表示页面与目录条目已核对；未与纸本逐字校勘。",
              "- 标题以网页为准，`catalog_title` 保留目录写法；两者不一致时以纸本复核。"]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", REPORT)


def main(argv=None):
    parser = argparse.ArgumentParser(description="收集《海子诗全编》研究语料")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="下载目录指定的页面")
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
