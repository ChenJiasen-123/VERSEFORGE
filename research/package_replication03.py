"""Package existing, locked experiment records; never generate or rescore poems."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/classical-evolution-replication-03'


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    packet = read(RUN/'blind-packet.json')
    reviews = {r['blind_id']: r for r in read(RUN/'assistant-blind-review.json')['readings']}
    mapping = {r['blind_id']: r for r in read(RUN/'blind-mapping-private.json')}
    sources = read(RUN/'assistant-source-audit.json')
    if isinstance(sources, dict):
        sources = sources.get('audits', sources.get('readings', sources.get('checks', [])))
    sources = {r['job']: r for r in sources}
    rows, operators, generations = [], collections.Counter(), collections.Counter()
    text = ['古诗演化0.9｜完整24首复测作品', '',
            '原题、全文及已锁定的助手盲读意见。未替换弱稿，未作人工改诗。',
            '全部24首仍有读音待核项，不认证全谱合律；阅读判断不等于用户或专家认可。',
            '本次复用曾出现账户故障的12题，每题独立两次；不是新增未见题。', '']
    for index, item in enumerate(packet, 1):
        blind = item['id']; job = mapping[blind]['job']; folder = RUN/'jobs'/job
        result = read(folder/'result.json'); state = read(folder/'kernel/state.json')
        review = reviews[blind]; selected = result['selected']
        assert item['poem'] == result['poem']
        operators.update(x['operator'] for x in state['archive'])
        generations[selected['generation']] += 1
        row = {'job': job, 'blind_id': blind, 'title': item['poem']['title'],
               'completed_generations': result['completed_generations'],
               'recorded_drafts': len(state['archive']), 'selected_id': selected['id'],
               'selected_generation': selected['generation'],
               'postcheck_attempt_count': len(result['postcheck_attempts']),
               'worth_keeping': review['worth_keeping'],
               'task_fit': review['task_fit_non_allusion']}
        rows.append(row)
        text.extend([f'{index:02d}｜《{item["poem"]["title"]}》', '题目：'+item['topic'], '',
                     *item['poem']['lines'], '',
                     f'盲读分：{review["score"]}/4；值得保留：{review["worth_keeping"]}；题意：{review["task_fit_non_allusion"]}',
                     '读到的体验：'+review['actual_experience'], '主要问题：'+review['main_problem'],
                     f'选稿：第{selected["generation"]}代 {selected["id"]}；记录候选{len(state["archive"])}份。'])
        if job in sources:
            audit = sources[job]
            text.extend(['用典核查：'+audit['reason'], '典源关系：'+audit['relation']])
        text.extend(['记录：'+str(folder.relative_to(ROOT)), '', '—'*32, ''])
    stats = {'runs': len(rows), 'completed_two_generations': sum(r['completed_generations']==2 for r in rows),
             'recorded_drafts': sum(r['recorded_drafts'] for r in rows), 'operators': dict(operators),
             'selected_generation_counts': dict(generations),
             'jobs_with_multiple_final_attempts': sum(r['postcheck_attempt_count']>1 for r in rows),
             'limitations': ['记录候选不含未能结构化保存的生成尝试；失败调用保留在调用账本。',
                            '选择较晚一代不是文学改善的证明；有初稿最终胜出。'], 'rows': rows}
    save(RUN/'lineage-statistics.json', stats)
    (ROOT/'research/古诗演化复测完整作品24首.txt').write_text('\n'.join(text), encoding='utf-8')
    print(json.dumps({k:v for k,v in stats.items() if k!='rows'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
