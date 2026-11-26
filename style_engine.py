"""Analyze an explicitly supplied corpus, one text at a time."""
import argparse
from pathlib import Path

from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.style.corpus import VERSION, digest, load_corpus, write
from poetry_agent.style.features import extract
from poetry_agent.style.reading import observations


def analyze(path, terms=(), focus="", client=None):
    poems, notices = load_corpus(path)
    records = []
    for poem in poems:
        record = extract(poem, terms)
        record.update(observations(record, focus, client))
        records.append({"source_record": poem, "features": record})
    return {"schema_version": VERSION, "input": str(path), "corpus_hash": digest(poems),
            "focus": focus, "terms": list(terms), "notices": notices, "records": records}


def main(argv=None):
    parser = argparse.ArgumentParser(description="逐篇分析显式指定的诗歌文本")
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 TXT 单篇或 JSON/JSONL 多篇")
    parser.add_argument("--output", required=True, type=Path, help="JSON 分析报告")
    parser.add_argument("--term", action="append", default=[], help="逐行定位指定字词，可重复")
    parser.add_argument("--focus", default="", help="交给 DeepSeek 的专项细读问题")
    parser.add_argument("--deepseek", action="store_true", help="将指定正文发至 DeepSeek 做带行号的细读")
    args = parser.parse_args(argv)
    if args.focus and not args.deepseek:
        parser.error("--focus 需要 --deepseek；离线字词定位请用 --term")
    if args.input.resolve() == args.output.resolve() or (args.output.exists() and args.input.exists()
                                                          and args.output.samefile(args.input)):
        parser.error("输出文件不能覆盖输入语料")
    try:
        client = None
        if args.deepseek:
            load_env(Path(__file__).with_name(".env"))
            client = DeepSeekClient()
        report = analyze(args.input, args.term, args.focus, client)
        write(args.output, report)
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"分析失败：{exc}\n")
    print(f"已分析 {len(report['records'])} 篇，报告保存到 {args.output}")


if __name__ == "__main__":
    main()
