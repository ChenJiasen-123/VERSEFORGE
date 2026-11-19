import json
import unittest
from poetry_agent.studio import run_studio


class Client:
    model = 'fixture'
    def __init__(self, outputs): self.outputs, self.requests = iter(outputs), []
    def complete(self, system, user, **kwargs):
        self.requests.append((system, json.loads(user), kwargs))
        return {'content': json.dumps(next(self.outputs), ensure_ascii=False)}


def brief(**updates):
    value = {'genre': 'modern', 'topic': '十年后的自己', 'max_lines': 50,
             'requirements': ['不超过30行'], 'examples': ['短信', '邮件退信', 'AI助手提醒'],
             'required_words': [], 'forbidden_words': [],
             'directions': ['一张提前退休的工作证', '河床上十年的水位线', '一场无人到场的家宴'],
             'selected_direction': 1, 'pattern': None, 'unsupported_reason': ''}
    value.update(updates)
    return value


def checked(evidence='水位线'):
    return {'checks': [{'id': 'r1', 'status': 'satisfied', 'source_quote': '不超过30行',
                        'evidence': evidence, 'reason': '正文未超过行数上限。'}]}


class StudioTests(unittest.TestCase):
    def test_examples_remain_optional_and_original_prompt_reaches_writer(self):
        prompt = '写给十年后的自己。不超过30行，可以是短信、邮件退信、AI助手提醒。'
        client = Client([brief(), {'title': '河床', 'lines': ['水位线留在旧树上']}, checked()])
        result = run_studio(prompt, client=client)
        payload = client.requests[1][1]['task']
        self.assertIn(prompt, payload['extra_requirements'])
        self.assertIn('举例或可选手法，并非必用素材', payload['extra_requirements'])
        self.assertIn('河床上十年的水位线', payload['extra_requirements'])
        self.assertEqual(payload['required_words'], [])
        self.assertEqual(payload['max_lines'], 30)
        self.assertNotIn('score', result)
        self.assertEqual(len(client.requests), 3)

    def test_unsupported_form_is_not_silently_converted_to_jueju(self):
        client = Client([brief(genre='unsupported', unsupported_reason='当前未实现七律。')])
        result = run_studio('写一首七律', client=client)
        self.assertEqual(result['status'], 'unsupported')
        self.assertEqual(len(client.requests), 1)

    def test_checker_cannot_invent_a_requirement_not_quoted_from_prompt(self):
        client = Client([brief(), {'title': '河床', 'lines': ['水位线']}, {'checks': [
            {'id': 'r1', 'status': 'violated', 'source_quote': '必须使用短信', 'evidence': '', 'reason': '没写短信'}]}])
        result = run_studio('写一首诗，不超过30行，可以是短信。', client=client)
        self.assertEqual(result['checks']['initial_requirement_conflicts'], [])
        self.assertEqual(len(client.requests), 3)

    def test_confirmed_hard_conflict_gets_one_revision_and_both_drafts_are_kept(self):
        initial = {'checks': [
            {'id': 'r1', 'status': 'violated', 'source_quote': '信已经寄出', 'evidence': '明天再寄出', 'reason': '时态不符'},
            {'id': 'r2', 'status': 'satisfied', 'source_quote': '不超过30行', 'evidence': '明天再寄出', 'reason': '只有一行。'}]}
        final = {'checks': [
            {'id': 'r1', 'status': 'satisfied', 'source_quote': '信已经寄出', 'evidence': '寄出之后', 'reason': '已经寄出。'},
            {'id': 'r2', 'status': 'satisfied', 'source_quote': '不超过30行', 'evidence': '', 'reason': '只有一行。'}]}
        client = Client([brief(requirements=['信已经寄出', '不超过30行']), {'title': '河床', 'lines': ['明天再寄出']}, initial,
            {'title': '河床', 'lines': ['寄出之后，树又长高了一寸']}, final])
        result = run_studio('信已经寄出，不超过30行。', client=client)
        self.assertEqual(len(result['drafts']), 2)
        self.assertEqual(len(client.requests), 5)
        self.assertTrue(result['checks']['revision_semantics_rechecked'])
        self.assertTrue(result['checks']['requirements_confirmed'])
        self.assertEqual(client.requests[-1][1]['poem']['lines'], ['寄出之后，树又长高了一寸'])

    def test_failed_requirement_check_retains_the_generated_poem(self):
        client = Client([brief(), {'title': '河床', 'lines': ['水位线']}])
        original = client.complete
        def complete(*args, **kwargs):
            if len(client.requests) == 2:
                raise RuntimeError('service error')
            return original(*args, **kwargs)
        client.complete = complete
        result = run_studio('写一首诗，不超过30行。', client=client)
        self.assertEqual(result['poem']['lines'], ['水位线'])
        self.assertFalse(result['checks']['requirements_check_completed'])

