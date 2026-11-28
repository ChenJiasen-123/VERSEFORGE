import io,json,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from check_deepseek_balance import query_balance,ENDPOINT

class BalanceTests(unittest.TestCase):
    def test_only_official_get_and_availability_are_exposed(self):
        opener=Mock();opener.open.return_value=io.BytesIO(json.dumps({'is_available':True,'balance_infos':[{'total_balance':'private-amount'}]}).encode())
        result=query_balance(SimpleNamespace(key='private-credential'),opener)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,ENDPOINT);self.assertEqual(request.get_method(),'GET')
        self.assertTrue(result['is_available'])
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('balance_infos',result)

    def test_missing_or_non_boolean_availability_cannot_start_verification(self):
        for value in ({},{'is_available':'true'},{'is_available':False}):
            opener=Mock();opener.open.return_value=io.BytesIO(json.dumps(value).encode())
            result=query_balance(SimpleNamespace(key='private-credential'),opener)
            self.assertIsNot(result.get('is_available'),True)

if __name__=='__main__':unittest.main()
