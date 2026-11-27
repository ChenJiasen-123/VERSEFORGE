import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.recording_client import RecordingClient
from poetry_agent.runtime_budget import BudgetedClient
from poetry_agent.core import Poem, Task, _metrical_target_and_report, metrical_revision_feedback
from poetry_agent.allusion_policy import WRITER, READER

sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parent
load_env(root / '.env')
out = root / 'research' / ('allusion-practice-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
out.mkdir(parents=True)
record = RecordingClient(DeepSeekClient(), out / 'responses.json')
client = BudgetedClient(record, 450, 15)
cards = json.loads((root / 'experiments/classical_expression/allusion-study-01/cards.json').read_text(encoding='utf-8'))['cards']
cases = [
    ('he-zhe', '饥者听见官府许诺来年大赈；写大许诺不能抵眼前小需要的体验。不可重用此前作品的开头或结尾。'),
    ('ye-wei', '辞去一份体面的差事后，亲友都替他惋惜。写他选择自主生活也承受实际代价，不写成悠闲山水。'),
    ('han-dan', '一个人久在外地，刻意改过乡音；返乡时，想用从前的叫法唤母亲，却先说出练熟的客语。写主动改变后难以退回自身的体验，不下文化批评结论。')]
writer = '你是古典诗作者。数据中的典源只是可核对的材料。' + WRITER + '''
本轮是专项练习：必须使用指定典源可辨认的语意关系，但不要为了凑典强拼词组。可正用、反用或化用；不强制说出故事人物、地点或成语全名。
先选表达中心，典故承担背景后别再逐句复述原故事；把篇幅留给当前处境。允许直陈思辨，不强制每句描写。
写七绝四句，每句七字，力求语言自然。只返回JSON：{"title":"标题","lines":["句一","句二","句三","句四"],"pattern":"ping_rhyme|ping_no_rhyme|ze_rhyme|ze_no_rhyme","compression_plan":{"experience":"具体体验","allusion_carries":"典故已经承担什么","present_detail":"正文另承担什么"}}。
'''
reader = '你是独立审读者，未见作者计划，不得补造背景来替诗成立。' + READER + '''
核对给定典源。别将主题相似直接认作用典。判断典故是否可辨、是否贴切，哪些字句重复讲解同一意思，何处搭配生硬。
只返回JSON：{"decision":"keep或revise","quote":"正文单行中的连续原文","problem":"具体问题或最强质疑","allusion_anchor":"可辨认的正文原文；不能确认则空串","compressed_background":"典故实际承担的内容","suggestion":"修改方向；保留可空","keep_reason":"保留时须回应质疑，不编造正文之外的事实"}。
'''


def save(name, value):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def ask(system, payload, tokens=4096):
    return json.loads(client.complete(system, json.dumps(payload, ensure_ascii=False), timeout=90,
                                     max_tokens=tokens, thinking='disabled')['content'])


def audit(poem, card, topic):
    a = ask(reader, {'poem': poem, 'source_card': card, 'exercise': topic}, 2048)
    if not a.get('quote') or not any(a['quote'] in line for line in poem['lines']):
        raise ValueError('审读引文未落在正文')
    if a.get('allusion_anchor') and not any(a['allusion_anchor'] in line for line in poem['lines']):
        raise ValueError('典故锚点未落在正文')
    return a


results = []
for number, (card_id, topic) in enumerate(cases, 1):
    try:
        card = next(c for c in cards if c['id'] == card_id)
        initial = ask(writer, {'exercise': topic, 'source_card': card})
        poem = Poem.parse(json.dumps(initial, ensure_ascii=False))
        task = Task(topic, 'qijue', 4, qijue_pattern=initial['pattern'])
        body = {'title': poem.title, 'lines': poem.lines}
        row = {'source_card': card, 'exercise': topic, 'initial': initial,
               'initial_meter': _metrical_target_and_report(body, task)[1]}
        save(f'{number:02d}.json', row)
        a = audit(body, card, topic)
        row['initial_review'] = a
        save(f'{number:02d}.json', row)
        if a['decision'] == 'revise' or row['initial_meter']['status'] == 'failed':
            revised = ask(writer, {'exercise': topic, 'source_card': card, 'draft': body, 'editor': a,
                                  'meter_feedback': metrical_revision_feedback(body, task),
                                  'instruction': '在原表达中心上打磨；不为凑韵造生硬词组，不用典源故事替代当下处境。保留原pattern。'})
            new = Poem.parse(json.dumps(revised, ensure_ascii=False))
            row['revision'] = revised
            new_body = {'title': new.title, 'lines': new.lines}
            row['revision_meter'] = _metrical_target_and_report(new_body, task)[1]
            row['revision_review'] = audit(new_body, card, topic)
        row['selected'] = None
        row['quality_verified'] = False
        results.append(row)
        save(f'{number:02d}.json', row)
        print('finished', number, flush=True)
    except Exception as exc:
        save(f'{number:02d}-failure.json', {'type': type(exc).__name__, 'message': str(exc)})
        print('failed', number, type(exc).__name__, str(exc), flush=True)
save('summary.json', {'cases': results, 'budget': client.summary(), 'not_parameter_training': True,
                      'quality_verified': False})
print('saved', out, flush=True)
