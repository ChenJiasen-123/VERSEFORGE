"""Bounded work-level evolution with independent reading and shared RPE selection."""
import copy
import hashlib
import json
from dataclasses import asdict

from experiments.evolution.selection import select_survivors, crossover_pairs
from experiments.reverse_prompt_engineering.metrics import prompt_similarity
from poetry_agent.core import Task, Poem, check, _metrical_target_and_report, metrical_revision_feedback
from poetry_agent.aesthetics import compare_bidirectional
from .protocol import (VERSION, PLANNER, PLAN_READER, WRITER_SYSTEM, READER_SYSTEM,
                       validate_plan, validate_plans, validate_reviews, dumps)
from .store import RunStore, RecordedClient, code_digest, digest

DEFAULT_CONFIG = {'population':3, 'generations':2, 'mutation_count':2, 'crossover_count':1,
                  'max_similarity':.88, 'seconds':900, 'max_calls':45,
                  'generation_tokens':16384, 'pairwise':True}


def make_task(topic):
    return Task(**topic['task'])


def task_target(task):
    # An attributed target is provided BEFORE writing, without model reinterpretation.
    dummy = {'title':'target', 'lines':['甲']}
    pair = _metrical_target_and_report(dummy, task)
    if pair is None:
        raise ValueError('classical evolution needs a supported explicit basic profile')
    return pair[0]


def known_checks(poem, task):
    issues = check(Poem(**poem), task)
    pair = _metrical_target_and_report(poem, task)
    return {'hard_issues':issues, 'meter':pair[1] if pair else None}


def gates(candidate, topic):
    reader = candidate.get('review') or {}
    known = candidate.get('checks') or {}
    req = reader.get('requirements') or []
    expected = {f'r{i+1}' for i in range(len(topic['requirements']))}
    req_ok = bool(expected) and {r.get('id') for r in req} == expected and all(r.get('status')=='satisfied' for r in req)
    a = reader.get('allusion') or {}
    allusion_ok = not topic.get('allusion_required') or bool(a.get('supported'))
    parallel_ok = topic['task']['genre'] not in ('wulv','qilv') or reader.get('parallelism')=='confirmed'
    scores = reader.get('scores') or {}
    readable = all(type(scores.get(k)) is int and scores[k]>=2 for k in ('expression','progression','diction'))
    meter = known.get('meter') or {}
    return {'known_hard_clear':bool(candidate.get('poem')) and not known.get('hard_issues') and meter.get('status')!='failed',
            'requirements_confirmed':req_ok, 'allusion_goal_met':allusion_ok,
            'reader_complete':bool(reader), 'parallelism_confirmed':parallel_ok,
            'readability_floor_met':readable,
            'meter_status':meter.get('status','unknown')}


def eligible(candidate, topic):
    g = gates(candidate, topic)
    return all(g[k] for k in ('known_hard_clear','requirements_confirmed','allusion_goal_met',
                              'reader_complete','parallelism_confirmed','readability_floor_met'))


def rank_key(candidate, topic):
    g = gates(candidate, topic)
    hard = candidate.get('checks', {}).get('hard_issues', [])
    score = (candidate.get('review') or {}).get('scores') or {}
    quality = .4*score.get('expression',0)+.3*score.get('progression',0)+.3*score.get('diction',0)
    if topic.get('allusion_required'):
        quality = .8*quality+.2*score.get('allusion',0)
    # Unknown readings remain visible, but do not fossilize an awkward parent
    # merely because a different natural word is absent from the partial table.
    tie = -int(hashlib.sha256(candidate['id'].encode()).hexdigest()[:10],16)
    return (eligible(candidate,topic), g['known_hard_clear'], -len(hard),
            g['requirements_confirmed'],g['allusion_goal_met'],g['parallelism_confirmed'],
            g['reader_complete'],quality, tie)


def genome(candidate):
    p = candidate['plan']
    return dumps({k:p[k] for k in ('experience','movement','perspective','source_id')})


def blind_payload(topic, candidates, sources):
    return {'original_prompt':topic['prompt'], 'genre':topic['task']['genre'],
            'requirements':{f'r{i+1}':r for i,r in enumerate(topic['requirements'])},
            'allusion_required':bool(topic.get('allusion_required')),
            'sources':sources,
            'poems':[{'id':p['id'], 'poem':p['poem']} for p in candidates]}


class ClassicalEvolution:
    def __init__(self, topic, sources, client, directory, *, config=None, progress=lambda _:None):
        self.topic, self.sources = topic, sources
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        if self.config['population'] != 3 or not 0 <= self.config['generations'] <= 8:
            raise ValueError('initial experiment requires three candidates and 0..8 generations')
        if not 0 <= self.config['mutation_count'] <= 3 or not 0 <= self.config['crossover_count'] <= 3:
            raise ValueError('invalid offspring counts')
        self.task = make_task(topic)
        self.target = task_target(self.task)
        binding = {'protocol':VERSION, 'code_sha256':code_digest(), 'topic':topic,
                   'sources':sources, 'config':self.config, 'model':client.model,
                   'mode':'mock' if getattr(client,'mock',False) else 'live'}
        self.store = RunStore(directory, binding)
        self.client = RecordedClient(client,self.store,seconds=self.config['seconds'],
                                     max_calls=self.config['max_calls'],generation_tokens=self.config['generation_tokens'],
                                     progress=progress)
        self.progress = progress

    def _save_state(self, state):
        self.store.save('state.json', state)

    def _plans(self):
        data={'original_prompt':self.topic['prompt'], 'requirements':self.topic['requirements'],
              'allusion_required':self.topic.get('allusion_required',False), 'sources':self.sources}
        validate=lambda v:validate_plans(v,self.sources)
        first=self.client.json('initial-plans',PLANNER,data,validate)
        plans=self.client.json('reviewed-plans',PLAN_READER,{**data,'plans':first},validate)
        self.store.save('expression-plans.json',{'initial':first,'reviewed':plans})
        return plans

    def _write(self, ident, generation, plan, *, parents=(), operator='initial', problem='初稿'):
        action = 'write-'+ident
        data={'original_prompt':self.topic['prompt'], 'requirements':self.topic['requirements'],
              'task':asdict(self.task), 'metrical_target':self.target, 'sources':self.sources,
              'expression_plan':plan, 'operator':operator, 'problem_to_address':problem}
        if operator=='crossover':
            data['parent_concepts']=[{'id':p['id'],'plan':p['plan'],
                'problem':(p.get('review') or {}).get('problem')} for p in parents]
            data['crossover_instruction']='重组表达对象与视角、典源关系，写成新的完整作品。不要拼接父稿诗句。'
        elif parents:
            p=parents[0]
            feedback=metrical_revision_feedback(p['poem'],self.task)
            if feedback:
                # Preserve full sourced evidence in candidate checkpoints; the writer
                # receives a compact projection instead of two copies of the lexicon.
                feedback={k:feedback[k] for k in ('status','rule_source','line_targets',
                    'rhyme_lines_1based','instruction')}
                feedback['findings_to_review']=[{k:f[k] for k in (
                    'kind','status','line','character','text','expected_tone','actual_tone','sources',
                    'groups','positions') if k in f}
                    for f in p['checks']['meter']['findings'] if f['status'] in ('failed','unknown')]
            data['parent']={'poem':p['poem'],'review':p.get('review'),
                'checks':{'hard_issues':p['checks']['hard_issues'],'meter_status':p['checks']['meter']['status']},
                'metrical_feedback':feedback}
        def validate(value):
            p=validate_plan(value['plan'],self.sources)
            poem=asdict(Poem.parse(dumps(value['poem'])))
            change=value['change']
            if not isinstance(change,dict) or any(not isinstance(change.get(k),str) or not change[k].strip()
                for k in ('problem_addressed','preserved','changed','tradeoff')):
                raise ValueError('missing mutation rationale')
            return {'plan':p,'poem':poem,'change':change}
        obj=self.client.json(action,WRITER_SYSTEM,data,validate,thinking='enabled',
                             max_tokens=self.config['generation_tokens'])
        return {'id':ident,'generation':generation,'parent_ids':[p['id'] for p in parents],
                'operator':operator,**obj,'checks':known_checks(obj['poem'],self.task)}

    def _read(self, action, pool):
        # IDs must not reveal generation, parenthood or the baseline arm.
        aliases={p['id']:'c'+digest([self.store.binding_hash,action,p['id']])[:12] for p in pool}
        anonymous=[{'id':aliases[p['id']],'poem':p['poem']} for p in pool]
        payload=blind_payload(self.topic,anonymous,self.sources)
        requirements=payload['requirements']
        try:
            reviews=self.client.json(action,READER_SYSTEM,payload,
                lambda v:validate_reviews(v,anonymous,requirements,self.sources),max_tokens=14000)
        except (ValueError,KeyError,TypeError,RuntimeError):
            self.store.event('blind_review_incomplete', action=action)
            return [{**copy.deepcopy(p),'review':None} for p in pool]
        return [{**copy.deepcopy(p),'review':{**reviews[aliases[p['id']]],'id':p['id']}} for p in pool]

    def _select(self, pool):
        return select_survivors(pool,size=self.config['population'],
            rank_key=lambda c:rank_key(c,self.topic),genome=genome,similarity=prompt_similarity,
            max_similarity=self.config['max_similarity'])

    def _operator(self, parent, generation):
        g=gates(parent,self.topic)
        if not g['known_hard_clear']:return 'meter_repair'
        if not g['requirements_confirmed']:return 'topic_repair'
        if not g['allusion_goal_met']:return 'allusion_rebuild'
        if not g['parallelism_confirmed']:return 'parallelism_repair'
        scores=(parent.get('review') or {}).get('scores') or {}
        dimensions=['expression','progression','diction']
        if self.topic.get('allusion_required'):dimensions.append('allusion')
        weakest=min(dimensions,key=lambda k:(scores.get(k,0),dimensions.index(k)))
        if weakest=='diction':return 'diction_revision'
        if weakest=='allusion':return 'allusion_rebuild'
        return 'perspective_change' if generation%2==0 else 'expression_rebuild'

    def run(self):
        finished=self.store.load('result.json')
        if finished:return finished
        state=self.store.load('state.json') or {'generation':-1,'archive':[],'population':[],
            'history':[],'pending':None,'mode':'mock' if self.client.mock else 'live'}
        try:
            if state['generation']<0:
                plans=self._plans()
                pool=[]
                for i,plan in enumerate(plans):
                    ident=f'g00-i{i}'
                    try:pool.append(self._write(ident,0,plan))
                    except (ValueError,KeyError,TypeError,RuntimeError):
                        self.store.event('candidate_failed',candidate_id=ident)
                pool=self._read('read-g00',pool) if pool else []
                state.update(generation=0,population=self._select(pool),archive=pool)
                state['history'].append({'generation':0,'pool_ids':[p['id'] for p in pool],
                    'survivor_ids':[p['id'] for p in state['population']]})
                self._save_state(state)
            for generation in range(state['generation']+1,self.config['generations']+1):
                if not state['population'] or self.client.summary()['exhausted']:break
                parents=state['population']
                pending=state.get('pending') or {'generation':generation,'children':[]}
                state['pending']=pending
                self._save_state(state)
                children=pending['children']
                ranked=sorted(parents,key=lambda c:rank_key(c,self.topic),reverse=True)
                # Target failed candidates as well as elites, preserving diversity.
                for i,parent in enumerate(ranked[:self.config['mutation_count']]):
                    ident=f'g{generation:02d}-m{i}'
                    if any(p['id']==ident for p in children):continue
                    operator=self._operator(parent,generation)
                    try:
                        child=self._write(ident,generation,parent['plan'],parents=[parent],operator=operator,
                            problem=(parent.get('review') or {}).get('problem','检查题意与明确格律错误'))
                        children.append(child);self._save_state(state)
                    except (ValueError,KeyError,TypeError,RuntimeError):
                        self.store.event('candidate_failed',candidate_id=ident,operator=operator)
                pairs=crossover_pairs(parents,count=self.config['crossover_count'],
                    rank_key=lambda c:rank_key(c,self.topic),genome=genome,similarity=prompt_similarity)
                for i,pair in enumerate(pairs):
                    ident=f'g{generation:02d}-x{i}'
                    if any(p['id']==ident for p in children):continue
                    try:
                        children.append(self._write(ident,generation,pair[0]['plan'],parents=pair,operator='crossover',
                            problem='融合两个构思中有效的关系，避免父稿共同的缺点'))
                        self._save_state(state)
                    except (ValueError,KeyError,TypeError,RuntimeError):
                        self.store.event('candidate_failed',candidate_id=ident,operator='crossover')
                pool=self._read(f'read-g{generation:02d}',parents+children)
                survivors=self._select(pool)
                self.store.save(f'generations/g{generation:02d}.json',{
                    'parents':parents,'children':children,'evaluated_pool':pool,'survivors':survivors})
                state['archive'].extend(p for p in pool if p['generation']==generation)
                state['population']=survivors
                state['generation']=generation
                state['pending']=None
                state['history'].append({'generation':generation,'pool_ids':[p['id'] for p in pool],
                    'survivor_ids':[p['id'] for p in survivors],
                    'selection':[{'id':p['id'],'selected':p['id'] in {s['id'] for s in survivors},
                         'gates':gates(p,self.topic),'rank':rank_key(p,self.topic)[:-1]} for p in pool]})
                self._save_state(state)
            # Blind rereading across ALL generations: a later edit never erases a parent.
            pool=self._read('read-final-archive',state['archive']) if state['archive'] else []
            qualified=sorted((p for p in pool if eligible(p,self.topic)),
                             key=lambda c:rank_key(c,self.topic),reverse=True)
            selected=qualified[0] if qualified else None
            comparison=None
            if self.config['pairwise'] and len(qualified)>=2 and not self.client.mock:
                try:
                    comparison=compare_bidirectional(qualified[0]['poem'],qualified[1]['poem'],
                        {'topic':self.topic['prompt'],'genre':self.task.genre},self.client,60,relation='independent')
                    if comparison['assessment']['choice']=='b':selected=qualified[1]
                except (ValueError,KeyError,TypeError,RuntimeError):
                    comparison={'status':'incomplete_keep_ranked_candidate'}
            self.store.save('final-blind-reviews.json',pool)
            result={'protocol':VERSION,'status':'candidate_ready' if selected else 'needs_review',
                    'poem':selected['poem'] if selected else None,'selected':selected,
                    'best_unfinished':max(pool,key=lambda p:rank_key(p,self.topic)) if pool and not selected else None,
                    'completed_generations':state['generation'],'requested_generations':self.config['generations'],
                    'candidate_count':len(state['archive']),'history':state['history'],
                    'pairwise_comparison':comparison,'budget':self.client.summary(),
                    'mode':state['mode'],'literary_quality_verified':False,
                    'limitations':['文学审读与比较仍为模型判断；证据验证不等于文学认证',
                        'unknown读音不算通过；明确冲突稿不进入可展示候选',
                        '复用RPE筛选和配对；演化对象为构思与作品，不是现代诗提示词种群']}
            if selected and gates(selected,self.topic)['meter_status']=='unknown':
                result['status']='candidate_with_unresolved_readings'
        except (ValueError,KeyError,TypeError,RuntimeError) as exc:
            self.store.event('run_incomplete',failure_type=type(exc).__name__)
            self._save_state(state)
            result={'protocol':VERSION,'status':'incomplete','poem':None,
                'completed_generations':state['generation'],'budget':self.client.summary(),
                'mode':state['mode'],'literary_quality_verified':False}
        self.store.save('result.json',result)
        return result
