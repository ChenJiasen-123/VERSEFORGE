import copy,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import run_classical_replication as replication

class ReplicationTests(unittest.TestCase):
    def test_complete_new_registration_changes_identity_not_generation_inputs(self):
        source=json.loads((replication.ROOT/'runs/classical-evolution-fresh-held-02/experiment-binding.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as d:
            b=replication.register(Path(d)/'run','rep03')
            self.assertEqual(len(b['jobs']),24)
            self.assertEqual(len({j['key'] for j in b['jobs']}),24)
            self.assertNotEqual(b['experiment_sha256'],source['experiment_sha256'])
            for field in ('topics','sources','config','model','entry_source_sha256','diction_source_sha256','code_sha256'):
                self.assertEqual(b[field],source[field])
            self.assertEqual(b,replication.register(Path(d)/'run','rep03'))

    def test_unavailable_account_defers_unstarted_jobs_without_generating_or_rechecking_queue(self):
        flag=threading.Event();balance=Mock(return_value={'is_available':False,'status':'unavailable'})
        b={'model':'fixture'};job={'key':'one'}
        with tempfile.TemporaryDirectory() as d,patch.object(replication,'execute_job') as execute:
            result=replication.run_one(b,Path(d),job,flag,client_factory=Mock(),balance_fn=balance)
            self.assertEqual(result['state'],'deferred');self.assertTrue(flag.is_set());execute.assert_not_called()
            replication.run_one(b,Path(d),{'key':'two'},flag,client_factory=Mock(),balance_fn=balance)
            self.assertEqual(balance.call_count,1)
            self.assertFalse((Path(d)/'jobs/one/result.json').exists())

if __name__=='__main__':unittest.main()
