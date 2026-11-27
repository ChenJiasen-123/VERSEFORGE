import json
import tempfile
import unittest
from pathlib import Path
from poetry_agent.recording_client import RecordingClient

class Client:
    model='fixture'
    def complete(self,*args,**kwargs):return {'content':'{invalid','usage':{},'authorization':'secret'}

class RecordingTests(unittest.TestCase):
    def test_output_survives_downstream_parser_failure_without_auth_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.json';c=RecordingClient(Client(),path)
            r=c.complete('system','user')
            with self.assertRaises(ValueError):json.loads(r['content'])
            saved=path.read_text(encoding='utf-8')
            self.assertIn('{invalid',saved);self.assertNotIn('secret',saved)
            with self.assertRaises(ValueError):RecordingClient(Client(),path)

    def test_exception_records_category_without_raw_exception_text(self):
        class Broken(Client):
            def complete(self,*args,**kwargs):raise RuntimeError('private exception detail')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.json';c=RecordingClient(Broken(),path)
            with self.assertRaises(RuntimeError):c.complete('s','u')
            self.assertNotIn('private exception detail',path.read_text(encoding='utf-8'))
