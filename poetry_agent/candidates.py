"""Optional independent candidate runs sharing one wall-clock budget."""
import time
from dataclasses import asdict
from .core import compose
from .aesthetics import compare_bidirectional as compare, failure_code


def compose_candidates(task, client, count=1, max_revisions=2, budget=120,
                       aesthetic=False, revision_scope='local', *, use_examples=False, generation_thinking=None,
                       candidate_tasks=None,example_relations_only=False,comparison_task=None,candidate_evaluator=None):
    if type(count) is not int or not 1 <= count <= 3:
        raise ValueError('候选数须为1—3的整数')
    if not 0 < budget <= 600:
        raise ValueError('时间预算须大于0且不超过600秒')
    tasks=candidate_tasks or [task]*count
    baseline=asdict(task);baseline.pop('extra_requirements')
    if len(tasks)!=count or any({k:v for k,v in asdict(t).items() if k!='extra_requirements'}!=baseline for t in tasks):
        raise ValueError('候选方向不能改变体裁或硬条件')
    if count == 1:
        return compose(tasks[0], client, max_revisions, budget, aesthetic, revision_scope, use_examples=use_examples, generation_thinking=generation_thinking,example_relations_only=example_relations_only)
    started = time.monotonic()
    runs = []
    selections = []
    for index in range(count):
        remaining = budget - (time.monotonic() - started)
        if remaining <= 0:
            break
        # Reserve part of the shared budget for comparison; no added retries.
        allocation = remaining * 0.8 / (count - index)
        try:
            runs.append(compose(tasks[index], client, max_revisions, allocation, aesthetic, revision_scope, use_examples=use_examples, generation_thinking=generation_thinking,example_relations_only=example_relations_only))
        except RuntimeError:
            if not runs:
                raise
            selections.append({'candidate': index + 1, 'error': 'generation_failed'})
            break
    if not runs:
        raise RuntimeError('预算耗尽，未生成候选')
    valid = [(i, r) for i, r in enumerate(runs) if r['poem']]
    evaluations={}
    if candidate_evaluator:
        for index,run in valid:
            try:evaluations[index]=candidate_evaluator(run['poem'])
            except (ValueError,RuntimeError,KeyError,TypeError) as exc:
                evaluations[index]={'confirmed':False,'failure_code':failure_code(exc)}
    def rank(item):
        report=evaluations.get(item[0],{})
        compliance=0 if report.get('confirmed') else 2 if report.get('violations') or report.get('repair_requests') else 1
        return len(item[1]['issues']),compliance
    best = min(valid,key=rank) if valid else (0,runs[0])
    for index, run in valid:
        if index == best[0] or rank((index,run)) != rank(best) or client.mock:
            continue
        remaining = budget - (time.monotonic() - started)
        if remaining <= 0:
            break
        record = {'a_candidate': best[0] + 1, 'b_candidate': index + 1}
        try:
            record.update(compare(best[1]['poem'], run['poem'], comparison_task or asdict(task), client, remaining, relation='independent'))
            if record['assessment']['choice'] == 'b':
                best = (index, run)
        except (ValueError, RuntimeError, KeyError, TypeError) as exc:
            record['failure_code'] = failure_code(exc)
        selections.append(record)
    result = dict(best[1])
    result.update(candidate_runs=runs, candidate_selection=selections,
                  candidate_evaluations=evaluations,
                  selected_candidate=best[0] + 1, requested_candidates=count,
                  elapsed_seconds=round(time.monotonic() - started, 3))
    return result
