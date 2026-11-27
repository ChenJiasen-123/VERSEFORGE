import json
import tempfile
import unittest
from pathlib import Path
from experiments.classical_expression.compare_final import ready

class GateTests(unittest.TestCase):
    def test_live_run_cannot_be_compared(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):ready(Path(directory))
    def test_summary_alone_is_insufficient(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'summary.json').write_text(json.dumps({'status':'completed_full'}))
            with self.assertRaises(ValueError):ready(folder)

if __name__=='__main__':unittest.main()
