"""Compare original text probes in both orders; record evidence, never scores."""
import argparse
import json
from pathlib import Path
from poetry_agent.aesthetics import compare, failure_code
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.text_structure import compare_lineation


def run(probes, client, *, control=False):
    records = []
    for item in probes:
        a, b = item['a'], item['b']
        if not compare_lineation(a['lines'], b['lines'])['applicable']:
            raise ValueError('分行实验必须保持字词标点完全一致')
        record = {'id': item['id'], 'task': item['task'], 'a': a, 'b': b, 'orders': []}
        for reverse in (False, True):
            row = {'reversed': reverse}
            try:
                row['review'] = compare(b if reverse else a, a if reverse else b,
                                        item['task'], client, 60, lineation_control=control)
                choice = row['review']['assessment']['choice']
                row['original_choice'] = ({'a': 'b', 'b': 'a', 'tie': 'tie'}[choice]
                                          if reverse else choice)
            except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                row['failure_code'] = failure_code(exc)
            record['orders'].append(row)
        choices = [row.get('original_choice') for row in record['orders']]
        record['order_consistent'] = None if None in choices else choices[0] == choices[1]
        records.append(record)
    return {'protocol': 'lineation-order-probe-0.1', 'records': records,
            'fixture_origin': 'assistant_original_exercise_not_author_corpus',
            'quality_verified': False, 'experimental_lineation_control': control,
            'limitations': ['换序一致不等于判断正确；样本不能代表所有现代诗',
                            '只作纸面分行比较，未生成或评价朗读']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--control', action='store_true', help='启用实验性共有文字效果对照提示')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('输出已存在，请指定新的记录路径')
    root = Path(__file__).resolve().parent
    load_env(root / '.env')
    probes = json.loads((root / 'examples/lineation-probes.json').read_text(encoding='utf-8'))
    result = run(probes, DeepSeekClient(), control=args.control)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
