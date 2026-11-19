"""Collect explicit local experiment artifacts; never crawl research texts or secrets."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent


def make_record(topic, original, revision, source, source_hash):
    family = hashlib.sha256(topic.strip().encode()).hexdigest()
    payload = {'topic': topic, 'original': original, 'revision': revision}
    identity = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'id': identity, 'family_id': family,
            'partition': 'holdout_candidate' if int(family[:8], 16) % 5 == 0 else 'train_candidate',
            **payload, 'source': source, 'source_sha256': source_hash,
            'origin': 'assistant_diagnostic_and_api_generation',
            'reviewer_kind': 'assistant_or_model', 'human_quality_label': None,
            'approved_for_training': False, 'preference': None,
            'limitations': ['修订不自动优于原稿', '尚未核定训练使用依据及独立质量标签']}


def collect():
    folder = ROOT / 'runs/evaluation-0ec515826ff34205882a52d0ea801820'
    records = []
    for name in ('diagnostic-revision.json', 'diagnostic-conservative-revision.json', 'diagnostic-local-workflow.json'):
        path = folder / name
        data = json.loads(path.read_text(encoding='utf-8'))
        if 'original' in data:
            original, revision = data['original'], data['revision']
        else:
            original, revision = data['history'][0]['poem'], data['poem']
        records.append(make_record('换班后的清晨', original, revision,
                                   str(path.relative_to(ROOT)), hashlib.sha256(path.read_bytes()).hexdigest()))
    for stem in ('0bb992abb57943bfba50d409bf8caa99', 'ad895a55c6fb4bd1a4c8cead3f28b22d'):
        original_path = ROOT / 'runs' / (stem + '.json')
        revision_path = ROOT / 'runs' / (stem + ('-literary-revision.json' if stem.startswith('0bb') else '-revision.json'))
        original = json.loads(original_path.read_text(encoding='utf-8'))
        revision = json.loads(revision_path.read_text(encoding='utf-8'))
        record = make_record(original['task']['topic'], original['poem'], revision['poem'],
                             str(revision_path.relative_to(ROOT)), hashlib.sha256(revision_path.read_bytes()).hexdigest())
        record['original_source'] = str(original_path.relative_to(ROOT))
        record['original_source_sha256'] = hashlib.sha256(original_path.read_bytes()).hexdigest()
        records.append(record)
    return list({r['id']: r for r in records}.values())


if __name__ == '__main__':
    records = collect()
    folder = ROOT / 'training/candidates'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'revisions.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
    summary = {'records': len(records), 'families': len({r['family_id'] for r in records}),
               'approved_training_records': 0, 'training_executed': False,
               'split_rule': 'sha256(normalized_topic) modulo 5; family never crosses partitions',
               'limitations': ['仅5次诊断修改，不代表训练规模', '分区仅为候选，不是可直接开训的数据集']}
    (folder / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))
