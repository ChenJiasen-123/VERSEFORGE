import json
import unittest
from unittest.mock import patch

from poetry_agent.client import DeepSeekClient
from poetry_agent.core import Poem, Task, check, compose


class SequenceClient:
    model = "test"
    mock = True

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return {"content": next(self.outputs)}


def output(lines):
    return json.dumps({"title": "测试", "lines": lines}, ensure_ascii=False)


class WorkflowTests(unittest.TestCase):
    def test_revision_fixes_constraint(self):
        client = SequenceClient([output(["梦想在长江"]), output(["长江在窗外"] )])
        result = compose(Task("夜", forbidden_words=["梦想"], required_words=["长江"]), client)
        self.assertEqual(result["status"], "constraints_passed")
        self.assertEqual(client.calls, 2)

    def test_revision_limit(self):
        client = SequenceClient([output(["梦想"])] * 3)
        result = compose(Task("夜", forbidden_words=["梦想"]), client)
        self.assertEqual(client.calls, 3)
        self.assertEqual(result["status"], "needs_review")

    def test_malformed_output_can_recover(self):
        result = compose(Task("夜"), SequenceClient(["not json", output(["夜色落在杯底"]) ]))
        self.assertEqual(result["status"], "constraints_passed")

    def test_keeps_less_broken_draft(self):
        client = SequenceClient([output(["长江"]), output(["梦想"])])
        result = compose(Task("夜", required_words=["长江", "灯"], forbidden_words=["梦想"]), client, 1)
        self.assertEqual(result["poem"]["lines"], ["长江"])

    def test_classical_and_multiline_checks(self):
        poem = Poem("春", ["细雨初收山色新。"] * 4)
        self.assertEqual(check(poem, Task("春", genre="qijue")), [])
        with self.assertRaises(ValueError):
            Poem.parse(output(["一行\n两行"]))

    def test_conflicting_constraints(self):
        with self.assertRaises(ValueError):
            Task("夜", required_words=["灯"], forbidden_words=["灯"])

    def test_key_not_sent_to_other_host(self):
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-not-real", "DEEPSEEK_BASE_URL": "https://example.com"}):
            with self.assertRaises(ValueError):
                DeepSeekClient()

    def test_aesthetic_prompt_selected_without_extra_calls(self):
        client = SequenceClient([output(["窗外的雨停了"])])
        with patch.object(client, "complete", wraps=client.complete) as call:
            result = compose(Task("雨"), client, aesthetic=True)
        self.assertIn("不为押韵扭曲语序", call.call_args.args[0])
        self.assertEqual(client.calls, 1)
        self.assertEqual(result["prompt_version"], "modern-aesthetic-0.3")

    def test_review_drives_revision_and_preserves_hard_constraints(self):
        critique = json.dumps(dict(decision='revise', preserve='等待', quote='灯',
                                   problem='关系不明', suggestion='明确位置', tradeoff='减少开放性'))
        comparison = json.dumps(dict(choice='b', quote_a='灯', quote_b='灯在门外', reason='位置使等待对象更明确，损失开放性'))
        client = SequenceClient([output(['灯']), critique, output(['灯在门外']), comparison])
        client.mock = False
        result = compose(Task('等待', required_words=['灯']), client, max_revisions=1, aesthetic=True, revision_scope='rewrite')
        self.assertEqual(client.calls, 4)
        self.assertEqual(result['poem']['lines'], ['灯在门外'])
        self.assertFalse(result['history'][0]['aesthetic_review']['quality_verified'])

    def test_comparison_can_retain_original_or_fail_safely(self):
        critique = json.dumps(dict(decision='revise', preserve='等待', quote='灯',
                                   problem='关系不明', suggestion='明确位置', tradeoff='减少开放性'))
        for decision in ('a', 'tie', 'invalid'):
            comparison = json.dumps(dict(choice=decision, quote_a='灯', quote_b='灯在门外', reason='新稿说明过多'))
            client = SequenceClient([output(['灯']), critique, output(['灯在门外']), comparison])
            client.mock = False
            result = compose(Task('等待'), client, max_revisions=1, aesthetic=True, revision_scope='rewrite')
            self.assertEqual(result['poem']['lines'], ['灯'])
            self.assertEqual(len(result['comparisons']), 1)

    def test_invented_review_quote_cannot_trigger_revision(self):
        critique = json.dumps(dict(decision='revise', preserve='等待', quote='不存在',
                                   problem='问题', suggestion='改', tradeoff='代价'))
        client = SequenceClient([output(['灯']), critique])
        client.mock = False
        result = compose(Task('等待'), client, aesthetic=True)
        self.assertEqual(client.calls, 2)
        self.assertEqual(result['poem']['lines'], ['灯'])
        self.assertIn('review_error', result['history'][0])
        self.assertEqual(result['history'][0]['review_failure_code'], 'quote_not_found')

    def test_classical_review_is_genre_specific_not_metric_certificate(self):
        client = SequenceClient([output(['東' * 7] * 4)])
        with patch.object(client, 'complete', wraps=client.complete) as call:
            result = compose(Task('雨', genre='qijue'), client, aesthetic=True)
        self.assertIn('古诗审美修订', call.call_args.args[0])
        self.assertNotIn('现代诗审美实验规则', call.call_args.args[0])
        self.assertEqual(result['prompt_version'], 'qijue-aesthetic-0.1')
        self.assertEqual(result['prosody']['status'], 'unknown')

    def test_expired_review_budget_stops_revision(self):
        clock = [0.0]
        critique = json.dumps(dict(decision='revise', preserve='等待', quote='灯',
                                   problem='关系不明', suggestion='明确位置', tradeoff='减少开放性'))
        client = SequenceClient([output(['灯']), critique])
        client.mock = False
        original = client.complete
        def complete(*args, **kwargs):
            response = original(*args, **kwargs)
            if client.calls == 2:
                clock[0] = 11.0
            return response
        client.complete = complete
        with patch('poetry_agent.core.time.monotonic', side_effect=lambda: clock[0]):
            result = compose(Task('等待'), client, budget=10, aesthetic=True)
        self.assertEqual(client.calls, 2)
        self.assertEqual(result['poem']['lines'], ['灯'])

    def test_local_revision_rejects_expansion(self):
        critique = json.dumps(dict(decision='revise', preserve='等待', quote='灯',
                                   problem='关系不明', suggestion='明确位置', tradeoff='减少开放性'))
        client = SequenceClient([output(['灯']), critique, output(['灯在门外', '等你'])])
        client.mock = False
        result = compose(Task('等待'), client, max_revisions=1, aesthetic=True)
        self.assertEqual(result['poem']['lines'], ['灯'])
        self.assertEqual(len(result['history'][1]['issues']), 2)
        self.assertEqual(result['comparisons'], [])

    def test_aesthetic_revision_cannot_displace_valid_draft_with_broken_one(self):
        critique = json.dumps(dict(decision='revise', preserve='等待', quote='灯',
                                   problem='关系不明', suggestion='明确位置', tradeoff='减少开放性'))
        client = SequenceClient([output(['灯']), critique, output(['门外'])])
        client.mock = False
        result = compose(Task('等待', required_words=['灯']), client, max_revisions=1, aesthetic=True)
        self.assertEqual(client.calls, 3)
        self.assertEqual(result['poem']['lines'], ['灯'])
        self.assertEqual(result['comparisons'], [])


if __name__ == "__main__":
    unittest.main()
