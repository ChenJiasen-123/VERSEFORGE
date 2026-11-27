"""Budgeted, resumable classical strategy search. Run as a module."""
import argparse
import hashlib
import json
import copy
from dataclasses import asdict
from pathlib import Path

from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.core import Task,Poem,SYSTEM,CLASSICAL_AESTHETIC,check,_metrical_target_and_report
from poetry_agent.editor import edit_rounds
from poetry_agent.requirement_checks import safe_review
from poetry_agent.studio import run_studio
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger,BudgetExhausted
from .protocol import plan,review
from poetry_agent.qijue_profiles import specification as qijue_spec
from poetry_agent.wujue import specification as wujue_spec
from .selection import bind_run,fingerprint,rank,population_rank,formal

ROOT=Path(__file__).resolve().parent
STRATEGIES=[
 '从一个细微但具体的体验起笔，让动作与景物逐步改变它。不强制转折，不用结尾补写主题。',
 '先寻找说话者和未被看见的另一方；比较直接写与对面落笔哪种更准确，允许选择朴素白描。',
 '寻找景物如何因人的处境改变意味；考察移情或可靠典故是否增加不可替代的关系，无益则不用。']

def save(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)

class Transport:
    def __init__(self,client):self.client=client;self.model=client.model;self.mock=False
    def complete(self,*args,temperature=None,**kwargs):
        # Current transport has no temperature argument; keep service default for every group.
        if temperature is not None:raise ValueError('temperature unsupported by current transport')
        return self.client.complete(*args,**kwargs)

class Adapter:
    mock=False
    def __init__(self,llm,variant):self.llm=llm;self.model=llm.model;self.variant=variant;self.n=0
    def complete(self,system,user,timeout=60,max_tokens=4096,thinking=None):
        self.n+=1
        content,meta=self.llm.call_text(purpose='classical_workflow',system=system,user=user,
            max_tokens=max_tokens,thinking=thinking,cache_variant=f'{self.variant}:{self.n}')
        return {'content':content,**meta}

def execute(topic,strategy,llm,variant):
    topic=dict(topic)
    topic['prompt']+='\n体裁：'+('七言绝句' if topic['genre']=='qijue' else '五言律绝')+'，四句；指定基本谱：'+topic['pattern']+'。'
    client=Adapter(llm,variant)
    if strategy is None:
        return {'workflow':run_studio(topic['prompt'],client=client,independent_editor=True,
            total_max_calls=18,total_budget_seconds=240)}
    planning=plan(topic['prompt'],strategy,llm)
    selected=planning['data']['options'][planning['data']['selected']]
    kwargs={('qijue_pattern' if topic['genre']=='qijue' else 'wujue_pattern'):topic['pattern']}
    task=Task(topic['prompt'],topic['genre'],4,extra_requirements=topic['prompt'],**kwargs)
    payload={'task':asdict(task),'metrical_target':(qijue_spec if topic['genre']=='qijue' else wujue_spec)(topic['pattern']),
        'strategy':strategy,'expression_hypothesis':selected,
        'instruction':'假设服务于写作，不是必须写出的说明。允许修正假设。四句绝句，按指定基本谱，返回title与lines的JSON。'}
    raw=client.complete(SYSTEM+CLASSICAL_AESTHETIC,json.dumps(payload,ensure_ascii=False),
        max_tokens=8192,thinking='enabled')
    poem=asdict(Poem.parse(raw['content']))
    def inspect(p):
        return {'workflow':{'poem':p,'checks':{'hard':check(Poem(**p),task),
            'meter':_metrical_target_and_report(p,task),
            'requirements':safe_review(topic['prompt'],p,[topic['prompt']],client)}},
            'blind':review(topic['prompt'],p,llm)}
    selected_row=inspect(poem);rounds=[]
    for number in range(3):
        if rank(selected_row)[:5]==(0,False,0,False,False):break
        feedback={'task':asdict(task),'draft':selected_row['workflow']['poem'],
            'checks':selected_row['workflow']['checks'],'independent_reading':selected_row['blind']['data'],
            'expression_hypothesis':selected,'strategy':strategy,
            'instruction':'修复题意和明确格律错误，再处理全篇表达缺口。保留有效句间关系，允许修正表达假设；未知读音不是错误，不为过谱自行选音。返回title、lines JSON。'}
        revised=asdict(Poem.parse(client.complete(SYSTEM+CLASSICAL_AESTHETIC,
            json.dumps(feedback,ensure_ascii=False),max_tokens=8192,thinking='enabled')['content']))
        contender=inspect(revised);adopt=rank(contender)<rank(selected_row)
        rounds.append({'round':number+1,'candidate':contender,'adopted':adopt,
            'selection_basis':'ordinal_formal_then_expression_proxy_not_literary_certification'})
        if adopt:selected_row=contender
    result=copy.deepcopy(selected_row)
    result.update({'planning':planning,'initial':poem,'rounds':rounds})
    return result

def evaluate(topic,strategy,llm,path):
    if path.exists():return json.loads(path.read_text(encoding='utf8'))
    row=execute(topic,strategy,llm,path.stem)
    poem=row['workflow']['poem']
    if 'blind' not in row:row['blind']=review(topic['prompt'],poem,llm)
    # Keep ordinal evidence separate from metrical state; unknown is never a pass.
    b=row['blind']['data'];row['expression_proxy']=int(b['decision']=='keep' and not b['gap'].strip())
    row['literary_quality_verified']=False
    save(path,row);return row

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    parser.add_argument('--run-id',default='pilot-01');parser.add_argument('--full',action='store_true')
    args=parser.parse_args()
    topics=json.loads((ROOT/'topics.json').read_text(encoding='utf8'))
    spec=json.loads((ROOT/'preregistration.json').read_text(encoding='utf8'))
    assert hashlib.sha256((ROOT/'topics.json').read_bytes()).hexdigest()==spec['topics_sha256']
    if not args.live:
        print(json.dumps({'mode':'estimate','pilot':'3 strategies x first optimization topic',
            'full':'3 initial strategies + 3 generations x3 children, each on6 optimization topics; 18 held-out poems',
            'calls_ceiling':1800,'tokens_ceiling':8000000,'price_unknown':True}));return
    out=ROOT/'runs'/args.run_id;out.mkdir(parents=True,exist_ok=True)
    bind_run(out/'binding.json',{'source_sha256':fingerprint(sorted(ROOT.glob('*.py'))),
        'topics_sha256':spec['topics_sha256'],'knowledge_sha256':fingerprint([ROOT/'knowledge.json']),
        'full':args.full,'protocol':'expression-0.3'})
    load_env(ROOT.parents[1]/'.env');load_env(ROOT.parents[2]/'poetry-agent'/'.env')
    budget=Budget(1800,8000000);restore_budget_from_ledger(budget,out/'ledger.jsonl')
    llm=LLM(Transport(DeepSeekClient()),budget,LLMCache(out/'cache.jsonl'),JsonlLedger(out/'ledger.jsonl'),max_parse_retries=0)
    training=[t for t in topics if t['split']=='optimization'];testing=[t for t in topics if t['split']=='held_out']
    knowledge=json.loads((ROOT/'knowledge.json').read_text(encoding='utf8'))
    strategies=[s+'\n可选诗法知识：'+json.dumps(knowledge['principles'],ensure_ascii=False) for s in STRATEGIES]
    population=[{'id':f'g0-{i}','strategy':s,'parent':None} for i,s in enumerate(strategies)]
    state=out/'population.json'
    start=0
    if state.exists():
        saved=json.loads(state.read_text(encoding='utf8'));population=saved['population'];start=saved['generation']+1
    generations=range(start,4 if args.full else 1)
    for generation in generations:
        pending=out/f'pending-{generation}.json'
        if pending.exists():candidates=json.loads(pending.read_text(encoding='utf8'))
        elif generation:
            children=[]
            for i,parent in enumerate(population):
                data,_=llm.call_json(purpose='mutate_strategy',system='改进古典诗创作策略。根据训练作品的盲读缺口调整方法，不规定固定主题、意象或情绪，不抄成句。只返回JSON：{"strategy":"完整可独立执行的策略"}。',
                    user=json.dumps(parent,ensure_ascii=False),max_tokens=1800,thinking='disabled',cache_variant=f'g{generation}-{i}')
                if not isinstance(data.get('strategy'),str) or not data['strategy'].strip():raise ValueError('empty strategy')
                children.append({'id':f'g{generation}-{i}','strategy':data['strategy'],'parent':parent['id']})
            candidates=population+children
        else:candidates=population
        if not pending.exists():save(pending,candidates)
        for candidate in candidates:
            evidence=[]
            for topic in (training if args.full else training[:1]):
                print(candidate['id']+' '+topic['id'],flush=True)
                try:
                    row=evaluate(topic,candidate['strategy'],llm,out/(candidate['id']+'-'+topic['id']+'.json'))
                except BudgetExhausted:
                    save(out/'summary.json',{'status':'budget_exhausted','budget':budget.summary()});raise
                except (ValueError,RuntimeError,KeyError,TypeError) as exc:
                    failure={'topic':topic['id'],'failure_type':type(exc).__name__,
                        'rank':[100,1,2,1,1,100],'proxy':0,'blind':{'gap':'本次未完成，不视为审美判断'}}
                    save(out/(candidate['id']+'-'+topic['id']+'-failure.json'),failure)
                    evidence.append(failure);continue
                evidence.append({'topic':topic['id'],'blind':row['blind']['data'],'proxy':row['expression_proxy'],
                    'rank':rank(row),'formal':formal(row),'poem':row['workflow']['poem']})
            candidate['evidence']=evidence;candidate['proxy']=sum(r['proxy'] for r in evidence)
        population=sorted(candidates,key=lambda c:(population_rank(c),c['id']))[:3]
        save(out/f'generation-{generation}.json',{'candidates':candidates,'selected':population})
        save(state,{'population':population,'generation':generation,'budget':budget.summary()})
    if args.full:
        # Freeze strategies before opening held-out evaluation.
        winner=population[0]['strategy'];save(out/'frozen-strategies.json',{'A':None,'B':strategies[0],'C':winner})
        for group,strategy in [('A',None),('B',strategies[0]),('C',winner)]:
            for topic in testing:evaluate(topic,strategy,llm,out/(group+'-'+topic['id']+'.json'))
    save(out/'summary.json',{'status':'completed_full' if args.full else 'completed_pilot','budget':budget.summary(),
        'quality_verified':False,'formal_acceptance_verified':False})

if __name__=='__main__':main()
