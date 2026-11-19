"""Explicit assistant curation for synthetic local-revision experiments, not gold labels."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
DECISIONS = {
    'diagnostic-revision.json': (False, '扩写并引入夜班卡发热等未展开感知，暂不作目标稿'),
    'diagnostic-conservative-revision.json': (False, '安全帽在臂弯却听见里面呼吸，感知位置不清；不作目标稿'),
    'diagnostic-local-workflow.json': (True, '仅用作合成局部修订实验：去掉替全体消除疲惫的断言，维持四行；不认证灯意象独特'),
    '0bb992abb57943bfba50d409bf8caa99-literary-revision.json': (True, '仅用作合成单字修订实验：归舟改归人，明确掩窗主体并保留前三句；不认证整诗艺术高度'),
    'ad895a55c6fb4bd1a4c8cead3f28b22d-revision.json': (False, '认取与雪未央搭配生硬，失去等待者，不作目标稿'),
}


if __name__ == '__main__':
    rows = [json.loads(line) for line in (ROOT / 'training/candidates/revisions.jsonl').read_text(encoding='utf-8').splitlines()]
    for row in rows:
        name = row['source'].replace('\\', '/').split('/')[-1]
        approved, basis = DECISIONS[name]
        row.update(approved_for_training=approved, approval_basis=basis, reviewer_kind='assistant',
                   experiment_scope='synthetic_local_revision_only_not_literary_gold',
                   revision_instruction=('保留前三句逐字不变，只明确末句掩窗的动作主体，保持七字和原韵。' if name.startswith('0bb')
                                         else '维持原稿四行，去掉替所有人消除疲惫的断言，改为个人感知，不替全体作保证。'))
    output = ROOT / 'training/curated'
    output.mkdir(exist_ok=True)
    (output / 'revisions.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows), encoding='utf-8')
    print(json.dumps({'assistant_accepted': sum(r['approved_for_training'] for r in rows),
                      'human_gold_labels': 0, 'training_executed': False}))
