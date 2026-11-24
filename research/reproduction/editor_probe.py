import json
from pathlib import Path
from poetry_agent.client import load_env,DeepSeekClient
from poetry_agent.aesthetics import review,failure_code

load_env('.env');client=DeepSeekClient()
base=Path('runs/sample-submission-20261120')
out=Path('research/editor-probe-02');out.mkdir(parents=True,exist_ok=True)
task={'genre':'modern','topic':'写给十年后的自己，但那时AI已替你回信；不超过30行，包含实际寄语和系统片段，两者不得互相解释。'}
cases=[('unfinished',json.loads((base/'question-11.json').read_text(encoding='utf-8'))['poem']),
       ('prompt-leakage',json.loads((base/'question-11-fresh.json').read_text(encoding='utf-8'))),
       ('returned-letter',json.loads(Path('tests/fixtures/returned-letter.json').read_text(encoding='utf-8'))['poem']),
       ('supported-time-crossing',{'title':'门背后','lines':['今晚，她又踮起脚，','被我轻轻按回去。','铅笔贴着头顶划过，','比去年高了一截。','等她睡了，我给十年后的自己写：','“搬家时，别擦掉厨房门背后那几道线。”','信设好日期，留在发件箱。','十年后，它到达的那一分钟，','你正在新家拆一盏灯。','替你管理信箱的AI回道：','“好。','——本条回复由助手代拟，无需回复。”','我收到那个“好”时，','她在隔壁翻了个身。','你把灯罩放到地上，','从一串钥匙里，','找出还没交还的那一把。']})]
for name,poem in cases:
    record={'case':name,'poem':poem,'task':task,'model':client.model,'independent_context':True}
    class Recorder:
        def complete(self,system,user,**kwargs):
            response=client.complete(system,user,**kwargs)
            record.setdefault('responses',[]).append({'system':system,'user':json.loads(user),'response':response})
            return response
    try: record['review']=review(poem,task,Recorder(),60)
    except (ValueError,RuntimeError,KeyError,TypeError) as exc: record['failure_code']=failure_code(exc)
    (out/f'{name}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,record.get('failure_code') or record['review']['assessment']['decision'],flush=True)
