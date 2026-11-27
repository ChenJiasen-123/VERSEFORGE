import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from experiments.classical_evolution.engine import (
    ClassicalEvolution, blind_payload, eligible, rank_key,
)
from experiments.classical_evolution.protocol import validate_reviews, validate_plans
from experiments.classical_evolution.store import RunStore, RecordedClient, code_digest, digest
from experiments.evolution.selection import select_survivors, crossover_pairs


POEM={'title':'灯前','lines':['塞外音书今已断','边尘不动雁来迟','魂兮若有归来日','认取灯前旧画眉']}
TOPIC={'id':'fixture','prompt':'写七绝思念亡夫，须用典。','requirements':['七绝','思念亡夫','用典'],
       'task':{'topic':'思念亡夫','genre':'qijue','max_lines':4,'qijue_pattern':'ze_no_rhyme'},
       'allusion_required':True,'source_ids':['s']}
SOURCES={'s':{'title':'招魂','text':'魂兮归来','url':'https://example.invalid/source'}}


def plan(i):
    return {'experience':f'体验{i}','movement':f'推进{i}','perspective':f'视角{i}',
        'source_id':'s','allusion_load':'招归背景','omit':'仪节说明','present_detail':'灯前旧容','risk':'重复'}


def review(ident, score=3):
    return {'id':ident,'experience':'呼唤归来','evidence':['魂兮'],
        'requirements':[{'id':f'r{i}','status':'satisfied','evidence':'','reason':'已核对'} for i in range(1,4)],
        'allusion':{'source_id':'s','anchors':['魂兮'],'supported':True,'relation':'唤归',
            'compression':'仪式背景','redundancy':'无'},
        'scores':dict.fromkeys(('expression','progression','diction','allusion'),score),
        'problem':'无','suggestion':'保留','decision':'keep','parallelism':'not_applicable'}


def candidate(ident='a', score=3, meter='unknown'):
    return {'id':ident,'plan':plan(ident),'poem':copy.deepcopy(POEM),'generation':0,'parent_ids':[],
            'checks':{'hard_issues':[],'meter':{'status':meter}},'review':review(ident,score)}


class FixtureClient:
    model='fixture';mock=True
    def __init__(self):self.requests=[]
    def complete(self,system,user,**kwargs):
        data=json.loads(user);self.requests.append((system,data,kwargs))
        if 'poems' in data:
            obj={'reviews':[review(p['id'],3) for p in data['poems']]}
        elif 'operator' in data:
            obj={'plan':data['expression_plan'],'poem':POEM,
                 'change':{'problem_addressed':'问题','preserved':'关系','changed':'措辞','tradeoff':'无'}}
        else:obj={'plans':data.get('plans') or [plan(i) for i in range(3)]}
        return {'content':json.dumps(obj,ensure_ascii=False),'usage':{'total_tokens':10}}


class EvolutionTests(unittest.TestCase):
    def test_two_generations_have_real_lineage_crossover_and_elite_preservation(self):
        client=FixtureClient()
        with tempfile.TemporaryDirectory() as directory, patch(
            'experiments.classical_evolution.engine.known_checks',
            return_value={'hard_issues':[],'meter':{'status':'unknown','findings':[]}}):
            engine=ClassicalEvolution(TOPIC,SOURCES,client,directory,config={'pairwise':False})
            result=engine.run()
            state=json.loads((Path(directory)/'state.json').read_text(encoding='utf-8'))
            self.assertEqual(result['completed_generations'],2)
            self.assertEqual(result['candidate_count'],9)
            winner=result['selected']['id']
            self.assertEqual(result['status'],'candidate_with_unresolved_readings')
            crossed=[p for p in state['archive'] if p['operator']=='crossover']
            self.assertEqual(len(crossed),2)
            self.assertTrue(all(len(p['parent_ids'])==2 for p in crossed))
            self.assertTrue(any(p['generation']==0 for p in state['archive']))
            resumed_client=FixtureClient()
            self.assertEqual(ClassicalEvolution(TOPIC,SOURCES,resumed_client,directory,
                config={'pairwise':False}).run()['selected']['id'],winner)
            self.assertEqual(resumed_client.requests,[])
        crossover_inputs=[d for _,d,_ in client.requests if d.get('operator')=='crossover']
        self.assertEqual(len(crossover_inputs),2)
        self.assertTrue(all('parent_concepts' in d and 'parent' not in d for d in crossover_inputs))
        self.assertNotIn('认取灯前旧画眉',json.dumps(crossover_inputs,ensure_ascii=False))
        blind_inputs=[d for _,d,_ in client.requests if 'poems' in d]
        self.assertTrue(all(p['id'].startswith('c') for d in blind_inputs for p in d['poems']))
        self.assertNotIn('g00-i',json.dumps(blind_inputs,ensure_ascii=False))

    def test_known_formal_failure_never_leaves_as_a_selected_poem(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            'experiments.classical_evolution.engine.known_checks',
            return_value={'hard_issues':['tone conflict'],'meter':{'status':'failed'}}):
            r=ClassicalEvolution(TOPIC,SOURCES,FixtureClient(),directory,
                config={'generations':0,'pairwise':False}).run()
        self.assertEqual(r['status'],'needs_review')
        self.assertIsNone(r['poem'])
        self.assertIsNotNone(r['best_unfinished'])

    def test_unknown_does_not_trap_weak_parent_but_is_never_certified_pass(self):
        parent=candidate('parent',1,'pass');child=candidate('child',4,'unknown')
        self.assertGreater(rank_key(child,TOPIC),rank_key(parent,TOPIC))
        self.assertTrue(eligible(child,TOPIC))
        self.assertEqual(child['checks']['meter']['status'],'unknown')

    def test_missing_topic_or_allusion_check_disqualifies_literary_high_score(self):
        row=candidate(score=4)
        row['review']['requirements'][1]['status']='violated'
        self.assertFalse(eligible(row,TOPIC))
        row=candidate(score=4);row['review']['scores']['diction']=0
        self.assertFalse(eligible(row,TOPIC))
        row=candidate(score=4);row['review']['allusion']['supported']=False
        self.assertFalse(eligible(row,TOPIC))

    def test_reader_does_not_see_planning_intention_or_generations(self):
        row=candidate();row['plan']['experience']='SECRET';row['change']={'why':'SECRET'}
        data=blind_payload(TOPIC,[row],SOURCES)
        self.assertNotIn('SECRET',json.dumps(data))
        self.assertEqual(set(data['poems'][0]),{'id','poem'})

    def test_blind_review_rejects_invented_or_multiline_quotes_and_foreign_sources(self):
        for bad_anchor in ('不存在','魂兮若有归来日，认取灯前旧画眉'):
            r=review('a');r['allusion']['anchors']=[bad_anchor]
            with self.assertRaises(ValueError):validate_reviews({'reviews':[r]},[candidate()],
                {'r1':'a','r2':'b','r3':'c'},SOURCES)
        r=review('a');r['allusion']['source_id']='invented'
        with self.assertRaises(ValueError):validate_reviews({'reviews':[r]},[candidate()],
            {'r1':'a','r2':'b','r3':'c'},SOURCES)

    def test_missing_requirement_id_or_duplicate_candidate_is_rejected(self):
        r=review('a');r['requirements'][2]['id']='r1'
        with self.assertRaises(ValueError):validate_reviews({'reviews':[r]},[candidate()],
            {'r1':'a','r2':'b','r3':'c'},SOURCES)
        with self.assertRaises(ValueError):validate_reviews({'reviews':[review('a'),review('a')]},
            [candidate(),candidate('b')],{'r1':'a','r2':'b','r3':'c'},SOURCES)

    def test_planning_rejects_fabricated_source_and_identical_directions(self):
        with self.assertRaises(ValueError):validate_plans({'plans':[plan(0)]*3},SOURCES)
        plans=[plan(i) for i in range(3)];plans[1]['source_id']='invented'
        with self.assertRaises(ValueError):validate_plans({'plans':plans},SOURCES)

    def test_changed_binding_and_changed_cached_action_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store=RunStore(directory,{'version':1});c=RecordedClient(FixtureClient(),store)
            c.call('one','system',{'a':1})
            with self.assertRaises(ValueError):c.call('one','system',{'a':2})
            with self.assertRaises(ValueError):RunStore(directory,{'version':2})
            text=''.join(p.read_text(encoding='utf-8') for p in Path(directory).rglob('*.json'))
            self.assertNotIn('Authorization',text)

    def test_call_budget_works_and_cached_calls_do_not_issue_new_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            raw=FixtureClient();c=RecordedClient(raw,RunStore(directory,{}),max_calls=1)
            c.call('a','s',{});c.call('a','s',{})
            self.assertEqual(len(raw.requests),1)
            self.assertEqual(c.summary()['calls'],1)
            with self.assertRaises(RuntimeError):c.call('b','s',{})

    def test_output_truncation_is_recorded_without_credentials_or_raw_errors(self):
        class Truncated:
            model='fixture';mock=True
            def complete(self,*a,**kw):
                raise RuntimeError('模型输出未正常结束（length），本次输出未采用')
        with tempfile.TemporaryDirectory() as directory:
            store=RunStore(directory,{})
            with self.assertRaises(RuntimeError):RecordedClient(Truncated(),store).call('write','system',{})
            self.assertEqual(store.load('call-ledger.json')[0]['failure_code'],'output_length')
            self.assertNotIn('length）',json.dumps(store.load('call-ledger.json'),ensure_ascii=False))

    def test_mutation_targets_observed_weakness_instead_of_random_word_changes(self):
        engine=object.__new__(ClassicalEvolution);engine.topic=TOPIC
        row=candidate();row['review']['scores']['diction']=1
        self.assertEqual(engine._operator(row,1),'diction_revision')
        row['review']['allusion']['supported']=False
        self.assertEqual(engine._operator(row,2),'allusion_rebuild')

    def test_frozen_held_out_resume_keeps_failed_jobs_and_does_not_repeat_calls(self):
        from experiments.classical_evolution.run import benchmark
        from experiments.classical_evolution.engine import DEFAULT_CONFIG
        topic={**TOPIC,'split':'held_out'}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);freeze=root/'freeze.json'
            freeze.write_text(json.dumps({'code_sha256':code_digest(),'sources_sha256':digest(SOURCES),
                'held_out_sha256':digest([topic]),'config':DEFAULT_CONFIG,'model':'fixture'}),encoding='utf-8')
            args=SimpleNamespace(split='held_out',seconds=900,max_calls=45,model='fixture',
                repetitions=1,out=root/'benchmark',workers=1,freeze=freeze)
            with patch('experiments.classical_evolution.run.load_data',return_value=([topic],SOURCES)), \
                 patch('experiments.classical_evolution.run.DeepSeekClient',return_value=FixtureClient()) as factory:
                benchmark(args)
                calls=factory.call_count
                benchmark(args)
                self.assertEqual(factory.call_count,calls)
            binding=json.loads((args.out/'experiment-binding.json').read_text(encoding='utf-8'))
            self.assertEqual(len(binding['jobs']),2)
            observations=json.loads((args.out/'observations.json').read_text(encoding='utf-8'))
            self.assertEqual(len(observations),2)
            self.assertTrue(any(r['status']=='incomplete' for r in observations))


class SharedSelectionTests(unittest.TestCase):
    def test_feasible_elite_survives_similarity_niching_and_failed_children(self):
        pool=[{'id':'elite','v':9,'text':'same'},{'id':'clone','v':8,'text':'same'},
              {'id':'different','v':1,'text':'other'}]
        selected=select_survivors(pool,size=2,rank_key=lambda x:x['v'],genome=lambda x:x['text'],
            similarity=lambda a,b:float(a==b))
        self.assertEqual([p['id'] for p in selected],['elite','different'])
        pairs=crossover_pairs(pool,count=1,rank_key=lambda x:x['v'],genome=lambda x:x['text'],
            similarity=lambda a,b:float(a==b))
        self.assertEqual([p['id'] for p in pairs[0]],['elite','different'])


if __name__=='__main__':unittest.main()
