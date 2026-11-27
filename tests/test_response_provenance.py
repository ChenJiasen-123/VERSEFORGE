import io
import json
import os
import unittest
from unittest.mock import patch, MagicMock
from poetry_agent.client import DeepSeekClient

class ResponseProvenanceTests(unittest.TestCase):
    def test_receipt_preserves_server_identity_without_exposing_secret(self):
        secret='test-secret-do-not-log'
        response={'id':'server-id-123','model':'actual-model','created':123,
            'choices':[{'finish_reason':'stop','message':{'content':'{}'}}],
            'usage':{'total_tokens':9}}
        opener=MagicMock()
        opener.open.return_value=io.BytesIO(json.dumps(response).encode())
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':secret,'DEEPSEEK_BASE_URL':'https://api.deepseek.com'}), patch('urllib.request.build_opener',return_value=opener):
            result=DeepSeekClient().complete('system','user',timeout=10)
        receipt=result['response_metadata']
        self.assertEqual(receipt['id'],'server-id-123')
        self.assertEqual(receipt['model'],'actual-model')
        self.assertEqual(len(receipt['key_fingerprint_sha256']),16)
        self.assertIn('started_utc',receipt)
        self.assertNotIn(secret,json.dumps(result))
        self.assertEqual(result['usage']['total_tokens'],9)
