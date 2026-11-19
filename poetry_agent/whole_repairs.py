"""One attributed whole-poem proposal; never automatically adopt it."""
import json
from dataclasses import asdict
from .core import Poem, check, SYSTEM, CLASSICAL_AESTHETIC, metrical_revision_feedback, _metrical_target_and_report
from .context_review import body_hash
from .meter_changes import compare_meter


def propose_whole_repair(poem, task, client, *, note='', budget=90, thinking='enabled', max_tokens=8192):
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not 0 < budget <= 600:
        raise ValueError('修订预算须大于0且不超过600秒')
    if not isinstance(note, str) or len(note) > 4000:
        raise ValueError('编辑意见须为不超过4000字的文本')
    if thinking not in ('enabled', 'disabled') or type(max_tokens) is not int or max_tokens not in (4096, 8192, 16384):
        raise ValueError('修订请求设置无效')
    original = Poem.parse(json.dumps(poem, ensure_ascii=False))
    pair = _metrical_target_and_report(asdict(original), task)
    if pair is None:
        raise ValueError('整稿格律修订须指定受支持的古诗词基本谱')
    payload = {'task': asdict(task), 'revision': {'draft': asdict(original),
        'issues': check(original, task), 'metrical_feedback': metrical_revision_feedback(asdict(original), task),
        'editor_note': note}}
    payload['ci_target' if task.genre == 'ci' else 'metrical_target'] = pair[0]
    response = client.complete(SYSTEM + CLASSICAL_AESTHETIC,
        json.dumps(payload, ensure_ascii=False), timeout=budget, max_tokens=max_tokens, thinking=thinking)
    revised = Poem.parse(response['content'])
    current = _metrical_target_and_report(asdict(revised), task)[1]
    return {'protocol': 'whole-repair-0.1', 'status': 'proposal_checked', 'task': asdict(task),
        'original': asdict(original), 'poem': asdict(revised), 'request': payload,
        'original_body_sha256': body_hash(original.lines), 'body_sha256': body_hash(revised.lines),
        'original_target_check': pair[1], 'target_check': current,
        'issues': check(revised, task),
        'metrical_transition': compare_meter(original.lines, revised.lines, pair[1], current),
        'automatically_adopted': False, 'literary_quality_verified': False,
        'parallelism_status': 'unknown' if task.genre in ('wulv', 'qilv') else 'not_required_by_this_tool',
        'api_calls': 1, 'model': getattr(client, 'model', None), 'usage': response.get('usage', {}),
        'request_settings': {'thinking': thinking, 'max_tokens': max_tokens, 'budget': budget},
        'limitations': ['unknown不是错误；不按谱自选音，正文改变后须另行语境复核',
                        'proposal_checked只表示完成检查，是否通过须看target_check；不自动覆盖原稿']}
