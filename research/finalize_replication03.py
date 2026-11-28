"""Evidence-bound delivery metadata for completed classical experiment."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'runs/classical-evolution-replication-03'


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def write(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    cases = []
    definitions = [
        ('09-r2', 'g00-i1', 'g01-x0',
         '交叉稿使末句从“才松握更长”的动作冲突变成“无言握更长”；但答使掩饰伤情的答语更清楚。母亲身份由题目提供，不能仅凭暗字证明失明。第二代只换只道或迎门，未见必然增益。',
         '初选父稿被裸读复核拒绝，改选第一代既存交叉稿；不是现场人为改诗。'),
        ('10-r1', 'g00-i0', 'g01-m1',
         '父稿“足试水之涯”对象与动作生硬；子稿“笑踏软泥街”让赤脚提鞋的动作收在轻快体验中，雨满阶也比行来雨满街更直接承接开门。第二代加入同君和缩脚，情境更繁却没有显见改善。',
         '表达重建有局部改善，不证明所有变异或整个算法平均优越。'),
        ('03-r2', 'g01-m1', 'g02-m0',
         '从客至变我至，只改变观察位置；许诺者与求援者转换反而更难读。焉、延仍像填韵，未解决承接问题。盲读评分1，不值得只作局部修改。',
         '前两次裸读未完成，第三稿通过模型；实际阅读仍判弱。回退提高可交付率不保证质量。'),
        ('08-r1', 'g01-m0', 'g02-m1',
         '子稿把扶正领改作温手正，但末句收灯证照掩重门依旧缺少自然句法。裸读拒绝这一稿，最终采用g02-m0的“方留证照掩重门”；它较可读，但余温仍偏泛，盲读只给2。',
         '拒绝坏稿和选到更好的候选是两件事；此例记录了实际拒绝及回退。'),
        ('11-r1', 'g00-i1', 'g01-m1',
         '父稿涸鲋、斗升以贫困小水引入接漏，水由救急变成负担，是有识别线索的反用；转义绕，不能解释为原典赞扬辞高厦。子稿涸鲋吾辞厦补吾，仍没有使这层转义更自然，最终保留初稿。',
         '典源支持不等于艺术自然；不得编造园中旱情、雨水救鱼或补写原典没有的辞厦故事。'),
    ]
    for suffix, parent_id, child_id, reading, limitation in definitions:
        job = next(p for p in (RUN/'jobs').iterdir() if suffix in p.name)
        state = load(job/'kernel/state.json'); result = load(job/'result.json')
        archive = {p['id']:p for p in state['archive']}
        parent, child = archive[parent_id], archive[child_id]
        assert parent_id in child['parent_ids']
        cases.append({'job':job.name, 'parent_id':parent_id, 'child_id':child_id,
                      'operator':child['operator'], 'parent_poem':parent['poem'],
                      'child_poem':child['poem'], 'selected_id':result['selected']['id'],
                      'actual_reading':reading, 'limitation':limitation})
    write(ROOT/'research/classical-evolution-replication-lineage-review-03.json',
          {'reviewer':'assistant; post-reveal qualitative reading, not a causal or blinded improvement test', 'cases':cases})
    reports = [load(ROOT/'runs'/name/'descriptive-report.json') for name in
               ['classical-evolution-combined-02','classical-evolution-fresh-held-02','classical-evolution-replication-03']]
    arms = [arm for report in reports for arm in report['by_arm'].values()]
    summary = {'unique_main_runs':sum(r['expected_runs'] for r in reports),
               'selected_outputs':sum(a['selected_outputs'] for a in arms),
               'assistant_worth_selected':sum(a['assistant_blind_worth_selected_output'] for a in arms),
               'calls':sum(a['calls'] for a in arms), 'known_tokens':sum(a['known_tokens'] for a in arms),
               'usage_unknown_calls':sum(a['usage_unknown_calls'] for a in arms),
               'scope':'96 original four-arm runs +24 failed fresh runs +24 exact-protocol replications; development/probes/pairwise comparisons excluded; not 144 runs of current version',
               'latest':reports[-1], 'lineage':load(RUN/'lineage-statistics.json')}
    write(ROOT/'research/classical-evolution-final-summary.json', summary)
    freeze = load(ROOT/'runs/classical-evolution-replication-freeze-03.json')
    checks = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha
              for name,sha in freeze['files'].items()}
    assert all(checks.values())
    write(ROOT/'research/classical-evolution-final-freeze-check.json', {'files':checks,'all_unchanged':True})
    print(json.dumps({k:v for k,v in summary.items() if k not in ['latest','lineage']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
