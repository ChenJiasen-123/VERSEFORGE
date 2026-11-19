import json
import unittest
from unittest.mock import patch

from poetry_agent.client import DeepSeekClient
from poetry_agent.core import Poem, Task, check, compose, metrical_revision_feedback


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


def review_output(fields):
    fields['text_sound'] = dict(quote=fields['quote'], mechanism='短行',
        semantic_effect='突出等候的对象', uncertainty='也可以与后文接续理解',
        basis={'kind':'interpretation','why_unverified':'仅作可能的句法解释'})
    return json.dumps(fields)


class WorkflowTests(unittest.TestCase):
    def test_metric_feedback_distinguishes_mismatch_from_unresolved_reading(self):
        lines = ['雨雷送雨漲春江', '柳岸初晴燕影雙', '石徑微寒花尚濕', '歸舟半掩小篷窗']
        feedback = metrical_revision_feedback({'lines': lines}, Task('雨', genre='qijue', qijue_pattern='ping_rhyme'))
        first = next(x for x in feedback['findings_to_review'] if x.get('line') == 1 and x.get('character') == 1)
        self.assertEqual((first['status'], first['text'], first['expected_tone']), ('failed', '雨', 'P'))
        self.assertEqual(feedback['line_targets'][0]['current_text'], lines[0])
        self.assertEqual(feedback['line_targets'][0]['required_tones'], 'PPZZZPP')
        self.assertEqual(feedback['line_targets'][0]['required_tones_chinese'], '平／平／仄／仄／仄／平／平')
        self.assertTrue(any(x['status'] == 'unknown' for x in feedback['findings_to_review']))
        self.assertIn('unknown仅表示', feedback['instruction'])
        self.assertIsNone(metrical_revision_feedback({'lines': ['雨']}, Task('雨')))

    def test_each_metrical_repair_is_rechecked_and_new_rhyme_error_is_sent_back(self):
        original = ['新雷送雨漲春江', '柳岸初晴燕影雙', '石徑微寒花尚濕', '歸舟半掩小篷窗']
        first = ['雨' + original[0][1:]] + original[1:]
        second = original[:-1] + [original[-1][:-1] + '東']
        client = SequenceClient([output(first), output(second), output(original)])
        with patch.object(client, 'complete', wraps=client.complete) as call:
            result = compose(Task('雨', genre='qijue', qijue_pattern='ping_rhyme'), client)
        self.assertEqual(result['poem']['lines'], original)
        self.assertEqual(len(result['history']), 3)
        sent = json.loads(call.call_args_list[2].args[1])['revision']['metrical_feedback']
        rhyme = next(x for x in sent['findings_to_review'] if x['kind'] == 'rhyme')
        self.assertEqual(rhyme['status'], 'failed')
        self.assertEqual(rhyme['positions'][-1]['text'], '東')
        self.assertEqual(rhyme['positions'][-1]['line'], 4)
        self.assertEqual(result['history'][2]['metrical_feedback_sent'], sent)
        transition = json.loads(call.call_args_list[2].args[1])['revision']['metrical_transition']
        self.assertEqual(transition['counts']['fixed_failures'], 1)
        self.assertEqual(transition['counts']['new_failures'], 1)
        self.assertEqual(result['history'][1]['metrical_transition'], transition)
        self.assertEqual(result['history'][2]['issues'], [])
        self.assertEqual(result['prosody']['basic_target_check']['status'], 'unknown')

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
        self.assertEqual(result["prompt_version"], "modern-aesthetic-0.5")

    def test_review_drives_revision_and_preserves_hard_constraints(self):
        critique = review_output(dict(decision='revise', preserve='等待', quote='灯',
                                   problem='关系不明', suggestion='明确位置', tradeoff='减少开放性'))
        comparison = json.dumps(dict(choice='b', quote_a='灯', quote_b='灯在门外', reason='位置使等待对象更明确，损失开放性'))
        reverse = json.dumps(dict(choice='a', quote_a='灯在门外', quote_b='灯', reason='换序后仍选修订稿'))
        client = SequenceClient([output(['灯']), critique, output(['灯在门外']), comparison, reverse])
        client.mock = False
        result = compose(Task('等待', required_words=['灯']), client, max_revisions=1, aesthetic=True, revision_scope='rewrite')
        self.assertEqual(client.calls, 5)
        self.assertEqual(result['poem']['lines'], ['灯在门外'])
        self.assertFalse(result['history'][0]['aesthetic_review']['quality_verified'])
        self.assertEqual(result['comparisons'][0]['comparison_relation'], 'revision')

    def test_comparison_can_retain_original_or_fail_safely(self):
        critique = review_output(dict(decision='revise', preserve='等待', quote='灯',
                                   problem='关系不明', suggestion='明确位置', tradeoff='减少开放性'))
        for decision in ('a', 'tie', 'invalid'):
            comparison = json.dumps(dict(choice=decision, quote_a='灯', quote_b='灯在门外', reason='新稿说明过多'))
            reverse = json.dumps(dict(choice={'a': 'b', 'tie': 'tie', 'invalid': 'invalid'}[decision],
                                      quote_a='灯在门外', quote_b='灯', reason='换序后保留原稿或弃权'))
            client = SequenceClient([output(['灯']), critique, output(['灯在门外']), comparison, reverse])
            client.mock = False
            result = compose(Task('等待'), client, max_revisions=1, aesthetic=True, revision_scope='rewrite')
            self.assertEqual(result['poem']['lines'], ['灯'])
            self.assertEqual(len(result['comparisons']), 1)

    def test_invented_review_quote_cannot_trigger_revision(self):
        critique = review_output(dict(decision='revise', preserve='等待', quote='不存在',
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
        critique = review_output(dict(decision='revise', preserve='等待', quote='灯',
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
        critique = review_output(dict(decision='revise', preserve='等待', quote='灯',
                                   problem='关系不明', suggestion='明确位置', tradeoff='减少开放性'))
        client = SequenceClient([output(['灯']), critique, output(['灯在门外', '等你'])])
        client.mock = False
        result = compose(Task('等待'), client, max_revisions=1, aesthetic=True)
        self.assertEqual(result['poem']['lines'], ['灯'])
        self.assertTrue(result['history'][1]['issues'])
        self.assertEqual(result['history'][1]['revision_scope_check']['status'], 'failed')
        self.assertEqual(result['comparisons'], [])

    def test_aesthetic_revision_cannot_displace_valid_draft_with_broken_one(self):
        critique = review_output(dict(decision='revise', preserve='等待', quote='灯',
                                   problem='关系不明', suggestion='明确位置', tradeoff='减少开放性'))
        client = SequenceClient([output(['灯']), critique, output(['门外'])])
        client.mock = False
        result = compose(Task('等待', required_words=['灯']), client, max_revisions=1, aesthetic=True)
        self.assertEqual(client.calls, 3)
        self.assertEqual(result['poem']['lines'], ['灯'])
        self.assertEqual(result['comparisons'], [])


if __name__ == "__main__":
    unittest.main()
