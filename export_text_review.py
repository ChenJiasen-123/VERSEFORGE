"""Render existing anonymous text pairs without model calls or inferred ratings."""
import argparse
import hashlib
import json
from pathlib import Path


def export(source, destination):
    raw = source.read_bytes()
    pairs = json.loads(raw)
    paragraphs = ['# 现代诗文本评阅稿',
                  '这里只比较纸面文本，不需要试听。每组同题，A/B沿用匿名样本顺序，不展示生成方法、成本或模型自评。此前看过部分作品可能影响匿名性，因此不宣称严格盲评。',
                  '先读题意与两首全诗，再看字词复现、句法长短、分行如何参与意义。短、长、押韵、口语或直接抒情本身都不是加减分项。允许难分优劣或无法判断。',
                  '反馈建议：组号；偏好A/B/难分优劣/无法判断；最影响判断的原句；它的具体作用；另一稿值得保留的部分。只记真实反馈，不据空表或模型自评生成标签。']
    key = {'source_sha256': hashlib.sha256(raw).hexdigest(), 'pairs': []}
    for pair in pairs:
        samples = pair['samples']
        if len(samples) != 2:
            raise ValueError('Each review pair must contain exactly two samples')
        task = pair['task']
        paragraphs.extend([f"## 第{pair['pair']}组：{task['topic']}",
                           f"题目要求：{task.get('extra_requirements', '')}",
                           f"正文最多{task['max_lines']}行；必用词：{'、'.join(task['required_words']) or '无'}；禁用词：{'、'.join(task['forbidden_words']) or '无'}。"])
        entry = {'pair': pair['pair'], 'samples': {}}
        for label, sample in zip(('A', 'B'), samples):
            poem = sample['poem']
            paragraphs.extend([f"### {label} · {poem['title']}",
                               '  \n'.join(poem['lines'])])
            entry['samples'][label] = sample['sample_id']
        paragraphs.append('评阅：偏好＿＿；关键原句＿＿；理由＿＿；另一稿值得保留之处＿＿。')
        key['pairs'].append(entry)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'review.md').write_text('\n\n'.join(paragraphs) + '\n', encoding='utf-8')
    (destination / 'sample-key.json').write_text(json.dumps(key, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return len(pairs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print('Exported text pairs:', export(args.source, args.output))
