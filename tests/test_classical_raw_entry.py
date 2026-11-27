import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from tests.test_classical_evolution import FixtureClient,TOPIC,SOURCES,POEM,candidate
from classical_agent import run_raw,PreservingEvolution,select_sources
from experiments.classical_evolution.engine import ClassicalEvolution
from experiments.classical_evolution.store import RunStore,RecordedClient,digest
from audit_classical_evolution import audit

class RawFixture(FixtureClient):
    def __init__(self):super().__init__();self.parses=0
    def complete(self,system,user,**kw):
        d=json.loads(user)
        if 'prompt' in d and 'genre_hint' in d:
            self.requests.append((system,d,kw));self.parses+=1
            return {'content':json.dumps({'genre':'qijue','topic':'思念亡夫','max_lines':4,
                'requirements':['七绝','思念亡夫','用典'] if self.parses==1 else ['独立约束1','独立约束2','独立约束3'],
                'examples':[],'required_words':[],'forbidden_words':[],'pattern':'ze_no_rhyme','unsupported_reason':''},ensure_ascii=False),'usage':{'total_tokens':10}}
        if 'verified_sources' in d:
            self.requests.append((system,d,kw))
            return {'content':json.dumps({'source_ids':list(d['verified_sources'])[:1],'allusion_required':True,'requirement_quote':'须用典','reason':'唤归关系'},ensure_ascii=False),'usage':{'total_tokens':10}}
        return super().complete(system,user,**kw)

class FinalFail(FixtureClient):
    def complete(self,system,user,**kw):
        d=json.loads(user);inner=d.get('original_input',d)
        if len(inner.get('poems',[]))>=9:
            self.requests.append((system,d,kw));return {'content':'{"reviews":[]}','usage':{'total_tokens':1}}
        return super().complete(system,user,**kw)

class RawEntryTests(unittest.TestCase):
    def test_raw_prompt_parses_selects_sources_and_rechecks_without_manual_task(self):
        c=RawFixture()
        with tempfile.TemporaryDirectory() as directory, \
             patch('experiments.classical_evolution.engine.known_checks',return_value={'hard_issues':[],'meter':{'status':'unknown','findings':[]}}), \
             patch('classical_agent.known_checks',return_value={'hard_issues':[],'meter':{'status':'unknown','findings':[]}}), \
             patch('classical_agent.safe_review',return_value={'complete':True,'confirmed':True}) as check:
            r=run_raw(TOPIC['prompt'],directory,c,library=SOURCES,config={'generations':0,'pairwise':False})
            self.assertIsNotNone(r['poem']);self.assertEqual(c.parses,2)
            self.assertEqual(check.call_args.args[2],['独立约束1','独立约束2','独立约束3'])
            self.assertEqual(r['budget']['calls'],len(c.requests))
            before=len(c.requests)
            self.assertEqual(run_raw(TOPIC['prompt'],directory,c,library=SOURCES,config={'generations':0,'pairwise':False})['poem'],r['poem'])
            self.assertEqual(len(c.requests),before)
        parses=[d for _,d,_ in c.requests if 'prompt' in d and 'genre_hint' in d]
        self.assertTrue(all('poem' not in d and 'expression_plan' not in d for d in parses))

    def test_global_budget_does_not_reset_between_frontend_and_kernel(self):
        c=RawFixture()
        with tempfile.TemporaryDirectory() as directory:
            r=run_raw(TOPIC['prompt'],directory,c,library=SOURCES,config={'generations':0,'max_calls':4})
        self.assertLessEqual(len(c.requests),4);self.assertIsNone(r['poem'])

    def test_required_allusion_with_no_matching_source_stops_before_writing(self):
        c=RawFixture()
        with tempfile.TemporaryDirectory() as directory:
            r=run_raw(TOPIC['prompt'],directory,c,library={})
        self.assertEqual(r['status'],'needs_review')
        self.assertFalse(any('operator' in d for _,d,_ in c.requests))

    def test_optional_allusion_cannot_be_promoted_to_a_requirement(self):
        class Wrong(FixtureClient):
            def complete(self,*a,**kw):return {'content':json.dumps({'source_ids':['s'],'allusion_required':True,'requirement_quote':'可以用典','reason':'x'},ensure_ascii=False)}
        with tempfile.TemporaryDirectory() as directory:
            api=RecordedClient(Wrong(),RunStore(directory,{}))
            with self.assertRaises(ValueError):select_sources('写七绝，可以用典。',SOURCES,api)

    def test_mandatory_allusion_cannot_silently_be_omitted(self):
        class Wrong(FixtureClient):
            def complete(self,*a,**kw):return {'content':json.dumps({'source_ids':['s'],'allusion_required':False,'requirement_quote':'','reason':'x'})}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):select_sources('写七绝，至少一处用典。',SOURCES,RecordedClient(Wrong(),RunStore(directory,{})))

    def test_failed_final_review_retains_previously_validated_identical_poems(self):
        with tempfile.TemporaryDirectory() as directory,patch('experiments.classical_evolution.engine.known_checks',return_value={'hard_issues':[],'meter':{'status':'unknown','findings':[]}}):
            r=PreservingEvolution(TOPIC,SOURCES,FinalFail(),directory,config={'pairwise':False}).run()
        self.assertIsNotNone(r['poem'])
        self.assertFalse(r['selected']['review_fallback']['latest_review_complete'])
        self.assertEqual(r['selected']['review_body_sha256'],digest(r['poem']))

    def test_fallback_does_not_reuse_a_review_after_body_changed(self):
        row=candidate();row['review_body_sha256']=digest(row['poem']);row['poem']['lines'][0]='更改正文而旧引文仍在'
        e=object.__new__(PreservingEvolution);e.topic=TOPIC;e.sources=SOURCES;e.store=Mock()
        with patch.object(ClassicalEvolution,'_read',return_value=[{**copy.deepcopy(row),'review':None}]):
            r=e._read('failed',[row])
        self.assertIsNone(r[0]['review']);self.assertNotIn('review_fallback',r[0])

    def test_raw_archive_audit_checks_original_constraints_and_independent_confirmation(self):
        mechanical={'hard_issues':[],'meter':{'status':'unknown','findings':[]}}
        with tempfile.TemporaryDirectory() as directory, \
             patch('experiments.classical_evolution.engine.known_checks',return_value=mechanical), \
             patch('classical_agent.known_checks',return_value=mechanical), \
             patch('audit_classical_evolution.known_checks',return_value=mechanical), \
             patch('classical_agent.safe_review',return_value={'complete':True,'confirmed':True}):
            root=Path(directory);job=root/'jobs'/'fixture'
            run_raw(TOPIC['prompt'],job,RawFixture(),library=SOURCES,config={'generations':0,'pairwise':False})
            binding=json.loads((job/'binding.json').read_text(encoding='utf-8'))
            experiment={**binding,'topics':[TOPIC],'jobs':[{'key':'fixture','topic_id':'fixture','arm':'raw_classical_evolution'}]}
            (root/'experiment-binding.json').write_text(json.dumps(experiment),encoding='utf-8')
            self.assertEqual(audit(root)['violations'],[])
            result=json.loads((job/'result.json').read_text(encoding='utf-8'))
            result['independent_requirement_check']['confirmed']=False
            (job/'result.json').write_text(json.dumps(result),encoding='utf-8')
            self.assertIn('raw output lacks independent original-prompt confirmation',[v['issue'] for v in audit(root)['violations']])

if __name__=='__main__':unittest.main()
