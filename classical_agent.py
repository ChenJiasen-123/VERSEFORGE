"""Raw contest-prompt entry: automatic constraints, source selection, evolution and independent recheck.
The existing frozen core remains untouched. Global call/time limits cover every stage.
"""
import argparse,copy,hashlib,json,re,sys
from dataclasses import asdict
from pathlib import Path
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.core import SYSTEM
from poetry_agent.studio import interpret_modular
from poetry_agent.requirement_checks import safe_review
from experiments.classical_evolution.engine import ClassicalEvolution,DEFAULT_CONFIG,known_checks
from experiments.classical_evolution.protocol import validate_reviews
from experiments.classical_evolution.store import RunStore,RecordedClient,code_digest,digest
ROOT=Path(__file__).resolve().parent
VERSION='raw-classical-agent-0.2'

class NamedClient:
    def __init__(self,api,prefix,suffix=''):self.api,self.prefix,self.suffix=api,prefix,suffix;self.n=0;self.model=api.model;self.mock=api.mock
    def complete(self,system,user,**kw):
        self.n+=1
        return self.api.call(f'{self.prefix}-{self.n:02d}',system+self.suffix,json.loads(user),
            thinking=kw.get('thinking') or 'disabled',max_tokens=min(kw.get('max_tokens',8192),16384))

class KernelClient:
    def __init__(self,api,poetics=''):self.api=api;self.poetics=poetics;self.action=None;self.model=api.model;self.mock=api.mock
    def complete(self,system,user,**kw):
        if self.action is None:raise ValueError('missing kernel action identity')
        if self.action.startswith(('initial-plans','reviewed-plans','write-')):
            system=self.poetics+'\n'+system
        r=self.api.call('kernel-'+self.action,system,json.loads(user),thinking=kw.get('thinking') or 'disabled',max_tokens=kw.get('max_tokens',8192))
        return {**r,'response_metadata':r.get('provider',{})}

class PreservingEvolution(ClassicalEvolution):
    def _read(self,action,pool):
        prior={p['id']:(copy.deepcopy(p.get('review')),p.get('review_body_sha256')) for p in pool}
        result=super()._read(action,pool);restored=[]
        requirements={f'r{i+1}':r for i,r in enumerate(self.topic['requirements'])}
        for p in result:
            old,old_hash=prior[p['id']]
            if p.get('review') is not None:
                p['review_body_sha256']=digest(p['poem'])
                p.pop('review_fallback',None)
            if p.get('review') is None and old and old_hash==digest(p['poem']):
                try:validate_reviews({'reviews':[old]},[p],requirements,self.sources)
                except (ValueError,KeyError,TypeError):continue
                p['review']=old
                p['review_fallback']={'action':action,'basis':'previous validated review of identical body, topic and sources','latest_review_complete':False}
                restored.append(p['id'])
        if restored:self.store.event('validated_prior_reviews_preserved',action=action,candidate_ids=restored)
        return result

def interpret_raw(prompt,hint,api,prefix):
    error=''
    for attempt in range(2):
        try:
            return interpret_modular(prompt,hint,'仅提取原题硬要求，不将所选基本谱写成题目额外要求。',None,
                NamedClient(api,f'{prefix}-{attempt}',suffix=('\n上次结构校验失败：'+error+'。仅修正字段结构与合法枚举，不添加原题要求。') if attempt else ''),expansion_mode='none')
        except (ValueError,KeyError,TypeError) as exc:
            error=str(exc)[:120]
            if attempt:raise

SOURCE_SELECTOR='''根据原题与已核典源的语意关系选择至多三个有帮助的典源，允许一个也不选。
不得把主题相似就当作贴合。原题明确要求用典时标allusion_required=true，并引用实际要求的连续原文；不必、可以不是强制。
只用给定source_id，不编造出处。原题不适合已有典源时返回空数组，不硬贴。
返回JSON {"source_ids":["给定id"],"allusion_required":false,"requirement_quote":"原题连续引文或空","reason":"关系依据或没有适用材料的原因"}。'''

def select_sources(prompt,library,api):
    def validate(v):
        ids=v.get('source_ids')
        if not isinstance(ids,list) or len(ids)>3 or len(ids)!=len(set(ids)) or any(i not in library for i in ids):raise ValueError('invalid source selection')
        if type(v.get('allusion_required')) is not bool or not isinstance(v.get('reason'),str) or not v['reason'].strip():raise ValueError('invalid source selection rationale')
        q=v.get('requirement_quote')
        if not isinstance(q,str) or (q and q not in prompt):raise ValueError('source requirement quote not in prompt')
        explicit=False
        for match in re.finditer(r'(?:必须|务必|至少[^，。；\n]{0,12}|(?<!不)须)[^，。；\n]{0,12}(?:用典|典故)',prompt):
            context=prompt[max(0,match.start()-4):match.end()]
            if not re.search(r'不必|无需|不要求|不强制|避免|不得|禁止',context):explicit=True
        if explicit and not v['allusion_required']:raise ValueError('explicit allusion requirement omitted')
        if v['allusion_required']:
            if not q or re.search(r'不必|无需|不强制|不要求|可以|可选',q):raise ValueError('optional allusion misread as required')
            if not re.search(r'(?:请|须|必须|务必|至少|需要|要求|运用|使用|含).{0,20}(?:用典|典故)|用典专项|用典练习',q):raise ValueError('allusion requirement not evidenced')
        return v
    selected=api.json('source-selection',SOURCE_SELECTOR,{'original_prompt':prompt,'verified_sources':library},validate,max_tokens=3000)
    return selected,{i:library[i] for i in selected['source_ids']}

def run_raw(prompt,directory,client,*,hint='qijue',library=None,config=None,progress=lambda _:None):
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>10000:raise ValueError('原题须为1—10000字文本')
    library=library if library is not None else json.loads((ROOT/'experiments/classical_evolution/sources.json').read_text(encoding='utf-8'))
    config={**DEFAULT_CONFIG,**(config or {})}
    knowledge=json.loads((ROOT/'experiments/classical_expression/knowledge.json').read_text(encoding='utf-8'))
    poetics='\n'.join(SYSTEM.strip().splitlines()[:3]+knowledge['principles'])
    binding={'protocol':VERSION,'entry_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'code_sha256':code_digest(),'prompt':prompt,'hint':hint,'source_library':library,'config':config,
        'poetics_knowledge':knowledge,'model':client.model,'mode':'mock' if getattr(client,'mock',False) else 'live'}
    store=RunStore(directory,binding);done=store.load('result.json')
    if done:return done
    api=RecordedClient(client,store,seconds=config['seconds'],max_calls=config['max_calls'],generation_tokens=config['generation_tokens'],progress=progress)
    try:
        progress('审题')
        brief,task=interpret_raw(prompt,hint,api,'initial-parse')
        store.save('initial-brief.json',brief)
        if task is None or task.genre=='modern':
            result={'status':'unsupported','poem':None,'message':'此入口负责已支持谱体的古典诗词。','budget':api.summary(),'protocol':VERSION}
            store.save('result.json',result);return result
        choice,sources=select_sources(prompt,library,api);store.save('source-selection.json',choice)
        topic={'id':'raw-'+digest(prompt)[:12],'prompt':prompt,'requirements':brief['requirements'] or [prompt],
            'task':asdict(task),'source_ids':choice['source_ids'],'allusion_required':choice['allusion_required']}
        store.save('effective-topic.json',topic)
        if topic['allusion_required'] and not sources:
            result={'status':'needs_review','poem':None,'message':'已核典源库没有找到适用材料，未强行拼贴。','budget':api.summary(),'protocol':VERSION,'effective_topic':topic}
            store.save('result.json',result);return result
        proxy=KernelClient(api,poetics)
        def stage(action):proxy.action=action;progress('演化：'+action)
        kernel=PreservingEvolution(topic,sources,proxy,Path(directory)/'kernel',
            config={**config,'entry_source_sha256':binding['entry_source_sha256'],'poetics_knowledge_sha256':digest(knowledge)},progress=stage)
        r=kernel.run();result={**r,'protocol':VERSION,'effective_topic':topic,'kernel_protocol':r['protocol']}
        result['kernel_budget']=r['budget'];result['budget']=api.summary()
        if r.get('selected'):
            progress('独立复核原题')
            second,_=interpret_raw(prompt,hint,api,'independent-parse')
            store.save('independent-brief.json',second)
            final=safe_review(prompt,r['poem'],second['requirements'] or [prompt],NamedClient(api,'independent-requirement-check'))
            result['independent_requirement_check']=final
            mechanical=known_checks(r['poem'],task)
            if not final['confirmed'] or mechanical['hard_issues']:
                result.update(status='needs_review',poem=None,selected=None,best_unfinished=r['selected'])
            result['latest_review_complete']=not bool((r.get('selected') or {}).get('review_fallback'))
        result['budget']=api.summary();result['literary_quality_verified']=False
    except (ValueError,KeyError,TypeError,RuntimeError) as exc:
        store.event('raw_entry_incomplete',failure_type=type(exc).__name__)
        result={'protocol':VERSION,'status':'incomplete','poem':None,'selected':None,'budget':api.summary(),'literary_quality_verified':False}
    store.save('result.json',result);return result

def main():
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser(description='直接输入原题的古诗演化入口')
    p.add_argument('--prompt',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--genre-hint',default='qijue',choices=['auto','wujue','qijue','wulv','qilv','ci'])
    p.add_argument('--model',default='deepseek-reasoner');p.add_argument('--env-file',type=Path,default=ROOT.parent/'poetry-agent'/'.env')
    a=p.parse_args();load_env(a.env_file)
    r=run_raw(a.prompt,a.out,DeepSeekClient(model=a.model),hint=a.genre_hint,progress=lambda s:print(s,flush=True))
    if r.get('poem'):print(r['poem']['title']+'\n'+'\n'.join(r['poem']['lines']))
    print('状态：'+r['status']);print('记录：'+str(a.out.resolve()))
if __name__=='__main__':main()
