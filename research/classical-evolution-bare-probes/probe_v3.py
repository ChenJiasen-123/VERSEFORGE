"""Fixed-poem development diagnostic with no topic, source card, plan or target verdict."""
import argparse, concurrent.futures, hashlib, json, sys
from pathlib import Path
from experiments.classical_evolution.store import RunStore, RecordedClient
from poetry_agent.client import DeepSeekClient, load_env

ROOT=Path(__file__).resolve().parent
CASES=[('classical-evolution-raw-pilot-08','pilot-02-r1'),
       ('classical-evolution-raw-held-01','held-04-r2'),
       ('classical-evolution-raw-pilot-08','pilot-03-r1'),
       ('classical-evolution-raw-pilot-06','pilot-04-r1'),
       ('classical-evolution-raw-pilot-08','pilot-01-r1')]
SYSTEM='''只读给定的一首古诗，检查语句是否能自行成立；你没有题目、创作构思或作者解释，不替作者推测想完成什么任务。
逐句填写reading，辨认词语的实际搭配、动作与对象。允许省略、换主语、比喻、典语和非线性，不以日常白话顺畅为唯一标准，也不要求每句复述身份。
若能从诗中读出合理关系，应如实保留。若一个词或词组必须靠额外编造事实、改变字义才能接通，要指出具体缺口，不能列出多种猜想后就判已通。
只评句法语义，不查是否合题、是否准确用典，不评创意高低，不强迫加故事或解释留白。
返回JSON {"status":"clear|uncertain|broken","reading":[{"passage_id":"p1","meaning":"此句可读出的实际关系，或具体缺口"}],"issues":[{"passage_id":"p1","importance":"central|local","problem":"具体词语关系问题"}],"reason":"整体判断依据"}。
reading逐句覆盖所有给定编号，issues无问题可为空；central只指影响主要语意的缺口。不要把示意枚举原样返回。'''

def validate(value,passages):
    if value.get('status') not in ('clear','uncertain','broken'):raise ValueError('invalid diction status')
    rows=value.get('reading');issues=value.get('issues')
    if not isinstance(rows,list) or len(rows)!=len(passages) or {x.get('passage_id') for x in rows}!=set(passages):raise ValueError('incomplete line readings')
    if any(not isinstance(x.get('meaning'),str) or not x['meaning'].strip() for x in rows):raise ValueError('missing actual reading')
    if not isinstance(issues,list) or any(x.get('passage_id') not in passages or x.get('importance') not in ('central','local') or not isinstance(x.get('problem'),str) or not x['problem'].strip() for x in issues):raise ValueError('invalid diction evidence')
    if not isinstance(value.get('reason'),str) or not value['reason'].strip():raise ValueError('missing reason')
    return value

def main():
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--thinking',choices=['disabled','enabled'],default='disabled')
    p.add_argument('--max-tokens',type=int,choices=[4000,8192],default=4000)
    p.add_argument('--indices',type=int,nargs='+',choices=range(len(CASES)),default=list(range(len(CASES))));a=p.parse_args()
    cases=[]
    if len(set(a.indices))!=len(a.indices):raise ValueError('duplicate case index')
    for index in a.indices:
        run,key=CASES[index]
        result=json.loads((ROOT/'runs'/run/'jobs'/(key+'-raw_classical_evolution')/'result.json').read_text(encoding='utf-8'))
        cases.append({'origin':run+'/'+key,'poem':result['poem']})
    store=RunStore(a.out,{'role':'development bare-poem diction probe; no new held-out data',
        'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'system':SYSTEM,'cases':cases,'model':'deepseek-reasoner','thinking':a.thinking,'max_tokens':a.max_tokens})
    load_env(ROOT.parent/'poetry-agent'/'.env')
    def run(item):
        i,c=item;local=RunStore(a.out/f'case-{i:02d}',{'study':store.binding_hash,'case':i})
        done=local.load('result.json')
        if done:return done
        api=RecordedClient(DeepSeekClient(model='deepseek-reasoner'),local,max_calls=2,seconds=120)
        passages={f'p{n}':line for n,line in enumerate(c['poem']['lines'],1)}
        review=api.json('bare-reading',SYSTEM,{'title':c['poem']['title'],'passages':passages},lambda v:validate(v,passages),thinking=a.thinking,max_tokens=a.max_tokens)
        result={**c,'review':review,'budget':api.summary()};local.save('result.json',result);print('finished',i,review['status'],flush=True);return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(run,enumerate(cases)))
    store.save('summary.json',{'rows':rows,'warning':'Fixed exposed development poems; model diction opinions do not certify literature or user preference.'})

if __name__=='__main__':main()
