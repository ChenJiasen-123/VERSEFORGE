import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from poetry_agent.aesthetic_examples import ROOT, load_examples
from poetry_agent.client import MockClient
from poetry_agent.core import Task, compose
from poetry_agent.candidates import compose_candidates


def copy_inputs(root):
    config = json.loads((ROOT/'poetry_agent/data/aesthetic-examples.json').read_text(encoding='utf-8'))
    feedback = json.loads((ROOT/config['feedback_file']).read_text(encoding='utf-8'))
    paths = ['poetry_agent/data/aesthetic-examples.json', config['feedback_file'],
             config['user_comment_file'], feedback['source_blind_packet']]
    for relative in paths:
        out = root/relative
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/relative, out)
    return config


class AestheticExampleTests(unittest.TestCase):
    def test_relation_mode_does_not_expose_original_fragments(self):
        class Capture(MockClient):
            def complete(self,system,user,timeout):
                self.payload=json.loads(user)
                return super().complete(system,user,timeout)
        client=Capture()
        result=compose(Task('题'),client,aesthetic=True,use_examples=True,example_relations_only=True,max_revisions=0)
        self.assertNotIn('examples',client.payload['positive_examples'])
        self.assertIn('principles',client.payload['positive_examples'])
        self.assertEqual(result['aesthetic_examples']['exposure'],'relation_analysis_without_original_fragments')
    def test_fragments_keep_user_words_separate_from_editor_analysis(self):
        payload, meta = load_examples()
        self.assertEqual(len(payload['examples']), 3)
        self.assertEqual(meta['profile'], 'user-discovery-01')
        for example in payload['examples']:
            self.assertTrue(example['quote'])
            self.assertTrue(example['user_comment_excerpt'])
            self.assertEqual(example['observation_author'], 'assistant')

    def test_changed_user_comment_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = copy_inputs(root)
            (root/config['user_comment_file']).write_text('changed', encoding='utf-8')
            with self.assertRaises(ValueError): load_examples(root)

    def test_valid_file_hash_cannot_make_an_invented_poem_quote_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = copy_inputs(root)
            path = root/config['feedback_file']
            feedback = json.loads(path.read_text(encoding='utf-8'))
            feedback['observations'][0]['exact_body_quotes'] = ['不存在于该诗的句子']
            path.write_text(json.dumps(feedback, ensure_ascii=False), encoding='utf-8')
            config['feedback_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            (root/'poetry_agent/data/aesthetic-examples.json').write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
            with self.assertRaises(ValueError): load_examples(root)

    def test_flag_requires_aesthetic_modern_before_any_api_call(self):
        class NoCall:
            def complete(self, *args, **kwargs): raise AssertionError('unexpected API call')
        for task, enabled in [(Task('题'), False), (Task('题', genre='qijue'), True)]:
            with self.assertRaises(ValueError): compose(task, NoCall(), aesthetic=enabled, use_examples=True)

    def test_generation_examples_are_opt_in_and_metadata_is_saved(self):
        class Capture(MockClient):
            def complete(self, system, user, timeout):
                self.payload = json.loads(user)
                return super().complete(system, user, timeout)
        for enabled in (False, True):
            client = Capture()
            result = compose(Task('题'), client, aesthetic=True, use_examples=enabled)
            self.assertEqual('positive_examples' in client.payload, enabled)
            self.assertEqual(result['aesthetic_examples'] is not None, enabled)

    def test_multiple_candidates_receive_the_explicit_example_option(self):
        results = [{'poem': {'lines': ['甲']}, 'issues': []}, {'poem': {'lines': ['乙']}, 'issues': []}]
        with patch('poetry_agent.candidates.compose', side_effect=results) as call:
            compose_candidates(Task('题'), MockClient(), count=2, aesthetic=True, use_examples=True, generation_thinking='disabled')
        self.assertTrue(all(c.kwargs['use_examples'] for c in call.call_args_list))
        self.assertTrue(all(c.kwargs['generation_thinking'] == 'disabled' for c in call.call_args_list))

    def test_generation_thinking_option_is_validated_and_sent_explicitly(self):
        class Capture:
            mock, model = False, 'test'
            def complete(self, *args, **kwargs):
                self.settings = kwargs
                return {'content': json.dumps({'title': '题', 'lines': ['雨停了']})}
        client = Capture()
        result = compose(Task('题'), client, generation_thinking='disabled')
        self.assertEqual(client.settings['thinking'], 'disabled')
        self.assertEqual(result['generation_thinking'], 'disabled')
        with self.assertRaises(ValueError): compose(Task('题'), client, generation_thinking='auto')
