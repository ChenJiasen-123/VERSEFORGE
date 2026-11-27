import tempfile
import unittest
from pathlib import Path
from experiments.classical_expression.selection import bind_run,rank

def row(meter,decision='keep'):
    return {'workflow':{'checks':{'hard':[],'meter':[{}, {'status':meter}],
        'requirements':{'confirmed':True,'violations':[]}}},
        'blind':{'data':{'decision':decision,'gap':'','device_risks':[]}}}

class SelectionTests(unittest.TestCase):
    def test_unknown_is_not_pass(self):
        self.assertLess(rank(row('pass','revise')),rank(row('unknown')))
    def test_literary_keep_does_not_erase_formal_failure(self):
        bad=row('failed');bad['workflow']['checks']['hard']=['wrong tone']
        self.assertLess(rank(row('unknown','revise')),rank(bad))
    def test_changed_binding_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'binding.json'
            bind_run(path,{'v':1});bind_run(path,{'v':1})
            with self.assertRaises(ValueError):bind_run(path,{'v':2})
    def test_unbound_old_cache_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'cache.jsonl').write_text('{}')
            with self.assertRaises(ValueError):bind_run(path/'binding.json',{'v':1})

if __name__=='__main__':unittest.main()
