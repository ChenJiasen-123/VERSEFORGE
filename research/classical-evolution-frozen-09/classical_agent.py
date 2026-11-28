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
from experiments.classical_evolution.engine import ClassicalEvolution,DEFAULT_CONFIG,known_checks,eligible,rank_key
from experiments.classical_evolution.protocol import validate_reviews
from experiments.classical_evolution.store import RunStore,RecordedClient,code_digest,digest
from classical_diction import SYSTEM as DICTION_SYSTEM, POLICY as DICTION_POLICY, validate_diction, passes_diction
ROOT=Path(__file__).resolve().parent
VERSION='raw-classical-agent-0.9'
CRITIC_POLICY={'unit':'one complete poem per request','thinking':'disabled',
    'parent_review_reuse':'validated identical poem, topic, source cards and reader policy only',
    'final_review':'fresh individual reading across all recorded generations',
    'semantic_gate':'explicit central-relation status and sourced allusion integration; unresolved is ineligible',
    'response_schema':'complete semantic-reader schema appended last, version 0.8'}

EVIDENCE_POLICY='''
原文证据改用每首poem_passages内的编号，程序会取回对应原文。不要重抄或拼接诗句。
每项review用evidence_ids:["p1"]替代evidence；每项requirements用evidence_id:"p1"替代evidence，无需引文的否定或行数判断可用null并在reason说明。
allusion用anchor_ids:["p1"]替代anchors；不用典时为空数组。p0是标题，仅requirements可引用；表达和用典的依据须在p1起的正文。
编号是每首诗局部的，不可借用另一首的编号。其他字段及所有实际判断要求仍按原协议，全量返回给定id。
'''

SEMANTIC_SCHEMA='''
最终返回格式以下列完整JSON为准，替代前文旧字段示意。每首必须包含central_relation，以及allusion.integration、source_quote，不能省略；语义判断须依正文，不能为填格式一律填clear或natural。
{"reviews":[{"id":"给定id","experience":"实际体验","evidence_ids":["p1"],
"central_relation":{"status":"clear|uncertain|broken","reading":"实际关键关系","evidence_ids":["p1"],"reason":"成立或缺口的依据"},
"requirements":[{"id":"给定r1等","status":"satisfied|violated|unknown","evidence_id":null,"reason":"实际依据"}],
"allusion":{"source_id":null,"anchor_ids":[],"supported":false,"integration":"natural|uncertain|forced|not_used","source_quote":"典源text中的连续原文，不用典时为空","relation":"与当下实际关系或无","compression":"实际省去什么或无","redundancy":"重复说明或无"},
"scores":{"expression":2,"progression":2,"diction":2,"allusion":0},"problem":"最重要问题或无","suggestion":"方向或保留理由","decision":"keep|revise","parallelism":"confirmed|unconfirmed|not_applicable"}]}。
上面竖线分隔的枚举须选一项，数字按实际阅读填写。requirements全量逐项返回，每个给定诗id恰好一项review。
'''

def reader_request(payload):
    data=copy.deepcopy(payload);inner=data.get('original_input',data)
    passages={p['id']:{'p0':p['poem']['title'],**{f'p{i}':line for i,line in enumerate(p['poem']['lines'],1)}}
        for p in inner.get('poems',[])}
    for p in inner.get('poems',[]):p['poem_passages']=passages[p['id']]
    return data,passages

def resolve_reader_evidence(content,passages,sources=None):
    try:value=json.loads(content)
    except (ValueError,TypeError):return content
    if not isinstance(value,dict) or not isinstance(value.get('reviews'),list):return content
    for row in value['reviews']:
        if not isinstance(row,dict):continue
        ident=row.get('id');available=passages.get(ident,{}) if isinstance(ident,str) else {}
        def quote(key,body_only=False):
            if key is None:return None if body_only else ''
            if not isinstance(key,str) or key not in available or (body_only and key=='p0'):
                return None
            return available[key]
        if 'evidence_ids' in row:
            ids=row['evidence_ids'];row['evidence']=[quote(i,True) for i in ids] if isinstance(ids,list) else None
        for req in row.get('requirements',[]) if isinstance(row.get('requirements'),list) else []:
            if isinstance(req,dict) and 'evidence_id' in req:req['evidence']=quote(req['evidence_id'])
        allusion=row.get('allusion')
        if isinstance(allusion,dict) and 'anchor_ids' in allusion:
            ids=allusion['anchor_ids'];allusion['anchors']=[quote(i,True) for i in ids] if isinstance(ids,list) else None
        if sources is not None:
            # This is a model judgment gate, not automatic semantic certification.
            # Missing/invalid judgments must trigger the existing bounded repair,
            # rather than quietly accepting an old-format optimistic review.
            try:apply_semantic_gate(row,available,sources)
            except (ValueError,KeyError,TypeError):
                row['evidence']=None
    return json.dumps(value,ensure_ascii=False)


def apply_semantic_gate(row,passages,sources):
    meaning=row.get('central_relation')
    if not isinstance(meaning,dict) or meaning.get('status') not in ('clear','uncertain','broken'):
        raise ValueError('missing central relation judgment')
    for key in ('reading','reason'):
        if not isinstance(meaning.get(key),str) or not meaning[key].strip():
            raise ValueError('missing actual relation reading')
    ids=meaning.get('evidence_ids')
    if not isinstance(ids,list) or not ids or any(not isinstance(i,str) or i=='p0' or i not in passages for i in ids):
        raise ValueError('central relation needs actual body evidence')
    meaning['evidence']=[passages[i] for i in ids]
    a=row['allusion']
    if a.get('integration') not in ('natural','uncertain','forced','not_used'):
        raise ValueError('missing allusion integration judgment')
    source_quote=a.get('source_quote')
    if not isinstance(source_quote,str):raise ValueError('missing source quotation')
    if a.get('supported'):
        sid=a.get('source_id')
        if sid not in sources or not source_quote or source_quote not in sources[sid]['text']:
            raise ValueError('allusion quotation absent from verified source')
        if a['integration']=='not_used':raise ValueError('contradictory allusion judgment')
    if a['integration']=='natural' and not a.get('supported'):
        raise ValueError('natural integration without supported allusion')
    problems=[]
    if meaning['status']!='clear':
        row['scores']['expression']=min(row['scores']['expression'],1)
        row['scores']['diction']=min(row['scores']['diction'],1)
        problems.append('关键关系尚未成立：'+meaning['reason'])
    if a['integration'] in ('uncertain','forced'):
        a['supported']=False
        row['scores']['allusion']=min(row['scores']['allusion'],1)
        # Optional allusion must not excuse a forced phrase either.
        row['scores']['diction']=min(row['scores']['diction'],1)
        problems.append('典语接入尚未成立：'+a['relation'])
    if problems:
        row['decision']='revise'
        row['problem']='；'.join(problems)+'；原审读：'+row['problem']

PARSER_POLICY='''
genre_hint只是没有明示体裁时的偏好，auto表示无偏好；原题明写的体裁优先，不构成冲突，不得因hint不同返回unsupported。
五绝、五言绝句和五言律绝对应wujue；七绝、七言绝句对应qijue；五律对应wulv，七律对应qilv。不要因简称与全称不同误判不支持。
'''

FORM_NAMES={'五绝':'wujue','五言绝句':'wujue','五言律绝':'wujue',
            '七绝':'qijue','七言绝句':'qijue','七言律绝':'qijue',
            '五律':'wulv','五言律诗':'wulv','七律':'qilv','七言律诗':'qilv'}

def unambiguous_requested_form(prompt):
    names='|'.join(sorted(FORM_NAMES,key=len,reverse=True))
    mentioned={FORM_NAMES[m.group()] for m in re.finditer(names,prompt)}
    if len(mentioned)!=1 or re.search(r'现代诗|散文诗|古绝',prompt):return None
    for m in re.finditer(r'(?:写|作|题|采用|体裁为|诗体为)\s*(?:一首)?\s*('+names+')',prompt):
        before=prompt[max(0,m.start()-8):m.start()]
        if not re.search(r'不要|不得|不必|无需|不要求|例如|比如|可以|可选|(?:不|别|勿|可)\s*$',before):
            return FORM_NAMES[m.group(1)]
    return None

TASK_SEMANTICS='''
解释原题时区分限制范围和逐项覆盖：“只能写其形、声、用、痕”规定允许的描写范围，不等于四项必须全部出现；原题明说逐项须有时才逐项核对。
原题给定的人物关系也是阅读语境，不要求诗中复述身份标签；结合实际动作、称谓、语意与给定典源判断有无支持，不把“没有逐字说出身份”等同于违题。正文若与题定关系矛盾或没有支持，则如实指出。
对面落笔、移情可以不用典源，不能因为没有典源就否定这些表达路径。用典仍只认给定已核材料及正文实际建立的对应，不自行补造出处。
'''

READER_CALIBRATION='''
表达审读须区分“复述发生了什么”和“读出了怎样的体验、关系或判断”。古雅词汇、合题、物象数量本身不加表达分。
expression：0=关系无法成立；1=大部分只将题面换成古语或堆叠景物，局部可取；2=正文建立可感的关系，多数句子共同起作用；3=表达集中准确，有自己的发现；4=关系与语言高度完成。
progression看各句使经验如何变化、深入、受阻或回应，不把换地点、加景物本身当作推进。朴素喜悦、平稳展开、直抒和必要复沓都可能有效，不强制反转、冲突、故事或金句。
diction看实际句法和语意搭配，压缩可以含蓄，但不能替生硬短语补造事件。指出具体原文的对象或语义问题；不要只说“略直、可更含蓄”，也不为解释清楚而要求改成白话。
给experience、problem和suggestion填写上述实际阅读，而不是复述作者可能想写什么；评分可以低，不能为保证出稿把明显未成立处评过门槛。
先辨认全篇关键关系，再评价修辞。每项review另填central_relation:{"status":"clear|uncertain|broken","reading":"不补造事件时，从正文及原题语境能读出的关键人物、动作对象和时间关系","evidence_ids":["p1"],"reason":"成立依据，或具体缺口"}。
只有影响全篇成立的歧义才标uncertain；允许省略、换主语、历史插入、回忆、比拟和非线性。题目已给的亲属身份不必再写一遍，也不要求解释所有留白。不能因为找不到唯一白话改写就否定诗句。
若两种读法导致关键人物或事件相反而正文无足够指向，不用构思替诗选定一版；标uncertain并指出缺口。改稿若只把相邻字词换得更雅，关键缺口仍在，就不能当作已解决。
allusion另填integration:"natural|uncertain|forced|not_used"和source_quote:"给定典源text内连续原文，不用典时为空"。原句引用可辨与接入当下成立分开判断。
relation须说明典源承载的关系在眼前人物、动作或判断中如何落地；compression须说明实际省去了什么。不能只说有典名或来源相同。若核心谓语、发问者或所求对象必须靠代补才接上，integration为uncertain或forced，不能同时把典故判为自然。
允许有意迁移典源人物、反用原意、只借关系的一部分；无需复述完整故事，不强迫写出原典的情绪。直接引用可以有效，不能仅凭引用本身认定硬贴。无用典时integration为not_used。
'''

class NamedClient:
    def __init__(self,api,prefix,suffix=''):self.api,self.prefix,self.suffix=api,prefix,suffix;self.n=0;self.model=api.model;self.mock=api.mock
    def complete(self,system,user,**kw):
        self.n+=1
        policy=PARSER_POLICY+TASK_SEMANTICS if 'parse' in self.prefix else TASK_SEMANTICS
        return self.api.call(f'{self.prefix}-{self.n:02d}',system+policy+self.suffix,json.loads(user),
            thinking=kw.get('thinking') or 'disabled',max_tokens=min(kw.get('max_tokens',8192),16384))

class KernelClient:
    def __init__(self,api,poetics=''):self.api=api;self.poetics=poetics;self.action=None;self.model=api.model;self.mock=api.mock
    def complete(self,system,user,**kw):
        if self.action is None:raise ValueError('missing kernel action identity')
        payload=json.loads(user);passages=None
        system=TASK_SEMANTICS+system
        if self.action.startswith(('initial-plans','reviewed-plans','write-')):
            system=self.poetics+'\n'+system
        elif self.action.startswith('read-'):
            system=READER_CALIBRATION+system+EVIDENCE_POLICY+SEMANTIC_SCHEMA
            payload,passages=reader_request(payload)
        r=self.api.call('kernel-'+self.action,system,payload,thinking=kw.get('thinking') or 'disabled',max_tokens=kw.get('max_tokens',8192))
        if passages is not None:
            inner=payload.get('original_input',payload)
            r={**r,'content':resolve_reader_evidence(r.get('content'),passages,inner.get('sources',{}))}
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

class IndividualEvolution(PreservingEvolution):
    def _read(self,action,pool):
        context=digest({'topic':self.topic,'sources':self.sources,'policy':CRITIC_POLICY,
            'reader_calibration':READER_CALIBRATION,'task_semantics':TASK_SEMANTICS,
            'evidence_policy':EVIDENCE_POLICY,'semantic_schema':SEMANTIC_SCHEMA})
        requirements={f'r{i+1}':r for i,r in enumerate(self.topic['requirements'])}
        result=[]
        for i,item in enumerate(pool):
            p=copy.deepcopy(item)
            reusable=bool(p.get('review')) and p.get('review_body_sha256')==digest(p['poem']) and p.get('review_context_sha256')==context
            if reusable:
                try:validate_reviews({'reviews':[p['review']]},[p],requirements,self.sources)
                except (ValueError,KeyError,TypeError):reusable=False
            if reusable and action!='read-final-archive':
                self.store.event('unchanged_parent_review_reused',action=action,candidate_id=p['id'])
            else:
                if not reusable:p['review']=None
                p=super()._read(f'{action}-single-{i:03d}',[p])[0]
                if p.get('review') is not None:p['review_context_sha256']=context
            result.append(p)
        return result

def interpret_raw(prompt,hint,api,prefix):
    error=''
    for attempt in range(2):
        try:
            brief,task=interpret_modular(prompt,hint,'仅提取原题硬要求，不将所选基本谱写成题目额外要求。',None,
                NamedClient(api,f'{prefix}-{attempt}',suffix=('\n上次结构校验失败：'+error+'。仅修正字段结构与合法枚举，不添加原题要求。') if attempt else ''),expansion_mode='none')
            expected=unambiguous_requested_form(prompt)
            if expected and (task is None or task.genre!=expected):
                raise ValueError('原题明示支持的体裁'+expected+'，不得因genre_hint不同拒绝或改成其他体裁')
            return brief,task
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

def run_raw(prompt,directory,client,*,hint='auto',library=None,config=None,progress=lambda _:None):
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>10000:raise ValueError('原题须为1—10000字文本')
    library=library if library is not None else json.loads((ROOT/'experiments/classical_evolution/sources.json').read_text(encoding='utf-8'))
    config={**DEFAULT_CONFIG,**(config or {})}
    knowledge=json.loads((ROOT/'experiments/classical_expression/knowledge.json').read_text(encoding='utf-8'))
    poetics='\n'.join(SYSTEM.strip().splitlines()[:3]+knowledge['principles'])
    binding={'protocol':VERSION,'entry_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'code_sha256':code_digest(),'prompt':prompt,'hint':hint,'source_library':library,'config':config,
        'poetics_knowledge':knowledge,'critic_policy':CRITIC_POLICY,
        'diction_policy':DICTION_POLICY,'diction_source_sha256':hashlib.sha256((ROOT/'classical_diction.py').read_bytes()).hexdigest(),
        'model':client.model,'mode':'mock' if getattr(client,'mock',False) else 'live'}
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
        kernel=IndividualEvolution(topic,sources,proxy,Path(directory)/'kernel',
            config={**config,'entry_source_sha256':binding['entry_source_sha256'],'poetics_knowledge_sha256':digest(knowledge),'critic_policy':CRITIC_POLICY},progress=stage)
        r=kernel.run();result={**r,'protocol':VERSION,'effective_topic':topic,'kernel_protocol':r['protocol']}
        result['kernel_budget']=r['budget'];result['budget']=api.summary()
        if r.get('selected'):
            progress('独立复核原题')
            second,_=interpret_raw(prompt,hint,api,'independent-parse')
            store.save('independent-brief.json',second)
            reviewed=kernel.store.load('final-blind-reviews.json') or []
            others=sorted((p for p in reviewed if eligible(p,topic)),key=lambda p:rank_key(p,topic),reverse=True)
            queue=[r['selected']]+others;seen=set();attempts=[];approved=None;approved_diction=None
            for candidate in queue:
                if len(attempts)>=3:break
                # Do not solicit another verdict on the same body under a new title or punctuation.
                body_key=digest([re.sub(r'[\s，。！？、；：,.!?;:]+','',line) for line in candidate['poem']['lines']])
                if body_key in seen:continue
                seen.add(body_key)
                mechanical=known_checks(candidate['poem'],task)
                attempt={'candidate_id':candidate['id'],'check':None,'known_hard_issues':mechanical['hard_issues'],'bare_diction':None}
                attempts.append(attempt)
                if mechanical['hard_issues']:continue
                # First read only the poem, before supplying topic/source hints.
                # This does not generate another poem or ask a human to rewrite it.
                passages={f'p{i}':line for i,line in enumerate(candidate['poem']['lines'],1)}
                action=f'bare-diction-check-{len(attempts):02d}'
                try:
                    diction=api.json(action,DICTION_SYSTEM,{'title':candidate['poem']['title'],'passages':passages},
                        lambda v:validate_diction(v,passages),thinking=DICTION_POLICY['thinking'],max_tokens=DICTION_POLICY['max_tokens'])
                except (ValueError,KeyError,TypeError,RuntimeError):
                    attempt['bare_diction_status']='incomplete'
                    continue
                bare={'poem_sha256':digest(candidate['poem']),'action':action,'review':diction,'approved':passes_diction(diction)}
                attempt['bare_diction']=bare
                if not bare['approved']:continue
                check_client=NamedClient(api,f'independent-requirement-check-{len(attempts):02d}',
                    suffix='\n用典核对只用以下已核典源，不另猜出处：'+json.dumps(sources,ensure_ascii=False))
                final=safe_review(prompt,candidate['poem'],second['requirements'] or [prompt],check_client)
                attempt['check']=final
                if final['confirmed'] and not mechanical['hard_issues']:
                    approved=candidate;approved_diction=bare;break
            result['postcheck_attempts']=attempts
            result['independent_requirement_check']=attempts[-1]['check'] if approved else next((a['check'] for a in attempts if a['check'] is not None),None)
            result['bare_diction_check']=approved_diction
            if approved:
                status='candidate_with_unresolved_readings' if approved['checks']['meter']['status']=='unknown' else 'candidate_ready'
                result.update(status=status,poem=approved['poem'],selected=approved,best_unfinished=None)
                result['latest_review_complete']=not bool(approved.get('review_fallback'))
            else:
                result.update(status='needs_review',poem=None,selected=None,best_unfinished=r['selected'],latest_review_complete=False)
        result['budget']=api.summary();result['literary_quality_verified']=False
    except (ValueError,KeyError,TypeError,RuntimeError) as exc:
        store.event('raw_entry_incomplete',failure_type=type(exc).__name__)
        result={'protocol':VERSION,'status':'incomplete','poem':None,'selected':None,'budget':api.summary(),'literary_quality_verified':False}
    store.save('result.json',result);return result

def main():
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser(description='直接输入原题的古诗演化入口')
    p.add_argument('--prompt',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--genre-hint',default='auto',choices=['auto','wujue','qijue','wulv','qilv','ci'])
    p.add_argument('--model',default='deepseek-reasoner');p.add_argument('--env-file',type=Path,default=ROOT.parent/'poetry-agent'/'.env')
    a=p.parse_args();load_env(a.env_file)
    r=run_raw(a.prompt,a.out,DeepSeekClient(model=a.model),hint=a.genre_hint,progress=lambda s:print(s,flush=True))
    if r.get('poem'):print(r['poem']['title']+'\n'+'\n'.join(r['poem']['lines']))
    print('状态：'+r['status']);print('记录：'+str(a.out.resolve()))
if __name__=='__main__':main()
