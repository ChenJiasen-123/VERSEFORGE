import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import run_classical_fresh_validation as driver

class FreshValidationTests(unittest.TestCase):
    def test_registration_freezes_two_repetitions_and_refuses_changed_or_old_prompts(self):
        original=driver.ROOT/'research/classical-evolution-fresh-topics-02.json'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);file=root/'topics.json';file.write_bytes(original.read_bytes())
            b=driver.register(file,root/'run');self.assertEqual(len(b['jobs']),24)
            self.assertEqual(b,driver.register(file,root/'run'))
            rows=json.loads(file.read_text(encoding='utf-8'));rows[0]['prompt']+='变更'
            file.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'binding changed'):driver.register(file,root/'run')
            old=json.loads((driver.ROOT/'experiments/classical_evolution/topics.json').read_text(encoding='utf-8'))
            rows[0]['prompt']=old[0]['prompt'];file.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'old exposed'):driver.register(file,root/'other')

    def test_creator_receives_original_prompt_full_library_and_no_gold_task_or_source_choice(self):
        topic={'id':'one','prompt':'写五绝一首：原题。','task':{'genre':'wujue','forbidden_words':['金标准专用']},
            'requirements':['金标准限制'],'source_ids':['gold-only']}
        b={'topics':[topic],'sources':{'full-library':{'text':'已核原文'}},'config':{'max_calls':45}}
        job={'key':'one-r1','topic_id':'one'}
        with tempfile.TemporaryDirectory() as d,patch.object(driver.classical_agent,'run_raw',return_value={'status':'fixture'}) as run:
            driver.execute_job(copy.deepcopy(b),Path(d),job,object())
            self.assertEqual(run.call_args.args[0],topic['prompt'])
            self.assertEqual(set(run.call_args.kwargs),{'hint','library','config','progress'})
            self.assertEqual(run.call_args.kwargs['library'],b['sources'])
            self.assertEqual(run.call_args.kwargs['hint'],'auto')
            result=Path(d)/'jobs'/job['key']/'result.json';result.parent.mkdir(parents=True);result.write_text('{}')
            driver.execute_job(b,Path(d),job,object());self.assertEqual(run.call_count,1)

if __name__=='__main__':unittest.main()
