"""Character n-gram style similarity and corpus attribution (offline, no API).

Reports which corpus a text sits nearest to and which neighbours are closest.
It is surface overlap, not a quality score.

    # 归属：这段文字更像哪个语料
    python style_similarity.py --corpus 海子=var/haizi/corpus.jsonl \
        --corpus 北岛=var/beidao/corpus.jsonl --text "你的手，像一月的雪"

    # 批量：每行一篇
    python style_similarity.py --corpus ... --file query.txt --output var/attribution.json

    # 与 scikit-learn 口径核对（需另装 sklearn；只用于开发核对）
    python style_similarity.py --corpus ... --parity
"""
import argparse
import json
import sys
from pathlib import Path

from poetry_agent.style.similarity import VERSION, Index


def load_corpus(spec):
    label, _, path = spec.partition("=")
    if not label or not path:
        raise ValueError("--corpus 需要 '名称=路径.jsonl' 形式")
    texts, ids = [], []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        body = record.get("text", "").strip()
        if not body:
            continue
        texts.append(body)
        ids.append(record.get("poem_id") or f"{label}-{number:03d}")
    if not texts:
        raise ValueError(f"{path} 没有可用正文")
    return label, texts, ids


def build(paths):
    texts, labels, ids = [], [], []
    for spec in paths:
        label, corpus_texts, corpus_ids = load_corpus(spec)
        texts += corpus_texts
        labels += [label] * len(corpus_texts)
        ids += corpus_ids
    return Index(texts, labels), ids, texts, labels


def attribute(index, ids, texts, labels, queries, k):
    rows = []
    for query in queries:
        result = index.classify(query, k=k)
        neighbours = [{"poem_id": ids[row["index"]], "label": row["label"], "score": row["score"]}
                      for row in result["neighbours"]]
        rows.append({"query": query[:120], "label": result["label"], "confidence": result["confidence"],
                     "centroid": result["centroid"], "neighbours": neighbours})
    return rows


def parity(index, texts, labels, k=1):
    """与 scikit-learn 的 TF-IDF 余弦同口径对照（都用全库拟合、排除自身）。"""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        print("未安装 scikit-learn，跳过对照。")
        return None
    from poetry_agent.style.stylometry import han_only

    bodies = [han_only(text) for text in texts]
    matrix = TfidfVectorizer(analyzer="char", ngram_range=(1, 2), sublinear_tf=True,
                             min_df=1, norm="l2").fit_transform(bodies)
    sklearn_sim = (matrix @ matrix.T).toarray()

    ours, theirs, deltas = 0, 0, []
    for i in range(len(texts)):
        # 本项目实现：库已含全文，排除自身后取最近邻
        scores = index.similarity(texts[i])
        order = [j for j in sorted(range(len(scores)), key=lambda j: -scores[j]) if j != i]
        ours += labels[order[0]] == labels[i]
        row = [(sklearn_sim[i][j], j) for j in range(len(texts)) if j != i]
        theirs += labels[max(row)[1]] == labels[i]
        for j in range(i + 1, len(texts)):
            deltas.append(abs(scores[j] - sklearn_sim[i][j]))
    import statistics

    return {"texts": len(texts), "ours_accuracy": ours / len(texts), "sklearn_accuracy": theirs / len(texts),
            "mean_abs_cosine_delta": statistics.mean(deltas),
            "max_abs_cosine_delta": max(deltas)}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="字符 n-gram 风格相似度与语料归属，离线运行")
    parser.add_argument("--corpus", action="append", required=True, help="'名称=语料.jsonl'，可重复")
    parser.add_argument("--text", action="append", default=[], help="待判定文本，可重复")
    parser.add_argument("--file", type=Path, help="待判定文本文件，每行一篇")
    parser.add_argument("--k", type=int, default=7, help="近邻投票的邻居数，默认 7")
    parser.add_argument("--output", type=Path, help="JSON 输出路径（默认打印到标准输出）")
    parser.add_argument("--parity", action="store_true", help="与 scikit-learn 口径核对")
    args = parser.parse_args()

    try:
        index, ids, texts, labels = build(args.corpus)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"读取语料未完成：{error}")
        return 1
    report = {"schema_version": VERSION, "corpus_size": len(texts),
              "corpora": {label: labels.count(label) for label in dict.fromkeys(labels)}}
    if args.parity:
        report["parity"] = parity(index, texts, labels)

    queries = list(args.text)
    if args.file:
        try:
            queries += [line.strip() for line in args.file.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError as error:
            print(f"待判定文本读取失败：{error}")
            return 1
    if queries:
        report["results"] = attribute(index, ids, texts, labels, queries, args.k)
    if not queries and not args.parity:
        parser.error("需要 --text/--file 或 --parity")

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        try:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(payload + "\n")
        except OSError as error:
            print(f"输出未写入（已有文件不覆盖）：{error}")
            return 1
        print(f"已写入 {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
