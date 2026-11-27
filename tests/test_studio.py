import json
import unittest
from poetry_agent.studio import EXPANSION_ANCHOR_WRAPPER, run_studio


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
        client = Client([brief(genre='unsupported', unsupported_reason='当前未实现鹧鸪天。')])
        result = run_studio('写一首鹧鸪天', client=client)
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

    def test_rpe_v4_style_mode_loads_optimal_prompt_and_preserves_stanza_breaks(self):
        client = Client([
            brief(),
            {'title': '十年水位', 'lines': ['水位线刻在灰石壁上', '黑夜先于回信抵达', '', '我把耳朵贴向河床', '听水底的骨头发响']},
            checked('水位线'),
        ])
        result = run_studio('写给十年后的自己，不超过30行。', client=client, style_mode='rpe_v4')
        writer_system = client.requests[1][0]
        writer_kwargs = client.requests[1][2]
        self.assertIn('原初尺度', writer_system)
        self.assertEqual(writer_kwargs.get('thinking'), 'enabled')
        self.assertEqual(writer_kwargs.get('max_tokens'), 65536)
        self.assertIn('', result['poem']['lines'])
        self.assertEqual(result['checks']['final_hard_issues'], [])
        self.assertEqual(result['style_engine']['mode'], 'rpe_v4')
        self.assertEqual(result['style_engine']['prompt_version'], 'v6')
        self.assertEqual(result['style_engine']['generation_thinking'], 'enabled')
        self.assertEqual(result['style_engine']['final_diagnostics']['stanza_count'], 2)
        self.assertGreater(result['style_engine']['final_diagnostics']['score'], 0.0)

    def test_expand_v1_and_none_expansion_modes(self):
        constraint_only = {
            'genre': 'modern', 'topic': '深夜自省', 'max_lines': 20,
            'requirements': ['不超过20行'], 'examples': [],
            'required_words': [], 'forbidden_words': [], 'pattern': None, 'unsupported_reason': '',
        }
        anchors_payload = {
            'anchors': [{
                'entry_anchor': '掌心微凉的铁钥匙',
                'world_scale': '掌心余温与窗外整片黑夜正面对峙',
                'stance_and_relation': '第一人称直呼黑夜与自己',
                'arc_turn': '由静守转向推门迎风',
                'avoid': '避开熬夜加班流水账',
            }],
            'selected_anchor': 0,
        }
        c_exp = Client([
            constraint_only,
            anchors_payload,
            {'title': '夜门', 'lines': ['铁钥匙凉在掌心', '黑夜压住门楣', '', '我推开门', '风替我喊出名字']},
            checked('铁钥匙'),
        ])
        r_exp = run_studio('写深夜自省，不超过20行。', client=c_exp, style_mode='rpe_v4', expansion_mode='expand_v1')
        self.assertEqual(r_exp['style_engine']['expansion_mode'], 'expand_v1')
        self.assertIn('掌心微凉的铁钥匙', c_exp.requests[2][1]['task']['extra_requirements'])

        c_none = Client([
            constraint_only,
            {'title': '直出', 'lines': ['黑夜落在肩上', '', '我不说话']},
            checked('黑夜'),
        ])
        r_none = run_studio('写深夜自省，不超过20行。', client=c_none, style_mode='rpe_v4', expansion_mode='none')
        self.assertEqual(r_none['style_engine']['expansion_mode'], 'none')
        self.assertNotIn('本次构思方向', c_none.requests[1][1]['task']['extra_requirements'])

    def test_expansion_wrapper_specifies_orthogonal_axes_avoid_injection_and_stance_diversity(self):
        for token in ('previous_poem', '【起跳物象】', '【时空维度】', '【发话姿态】',
                      '正交换轴', '旱地讨雨', '仰头逼问', '泥土换成石头', '同义换皮', 'avoid'):
            self.assertIn(token, EXPANSION_ANCHOR_WRAPPER)

    def test_rewrite_with_expand_v1_uses_new_anchor_and_omits_previous_poem_body_from_writer(self):
        previous = {
            'title': '旱地裂口',
            'lines': ['干裂的泥土张嘴讨雨', '', '我仰头逼问低垂的乌云', '第三行旧句绝不应进入写诗提示'],
        }
        constraint_only = {
            'genre': 'modern', 'topic': '久旱与回声', 'max_lines': 20,
            'requirements': ['不超过20行'], 'examples': [],
            'required_words': [], 'forbidden_words': [], 'pattern': None, 'unsupported_reason': '',
        }
        anchors_payload = {
            'anchors': [{
                'entry_anchor': '渡口熄灭的铜马灯',
                'world_scale': '冬夜结冰的江面与世代迁徙的渡船相互沉默',
                'stance_and_relation': '俯身平视冰层下的暗流，低声交付姓名',
                'arc_turn': '从守渡人退入江底钟声的回响',
                'avoid': '避开上一稿的泥土、乌云与旱地讨雨，避开日常琐事',
            }],
            'selected_anchor': 0,
        }
        client = Client([
            constraint_only,
            anchors_payload,
            {'title': '冰下渡口', 'lines': ['铜马灯在渡口凉透', '江面封住去年的船印', '', '我俯身把名字交给暗流']},
            checked('铜马灯'),
        ])
        run_studio('写久旱与回声，不超过20行。', previous=previous, client=client,
                   style_mode='rpe_v4', expansion_mode='expand_v1')
        # Anchor expansion stage receives full previous_poem + orthogonal instructions
        exp_sys, exp_user, _ = client.requests[1]
        self.assertIn('正交换轴', exp_sys)
        self.assertEqual(exp_user['previous_poem'], previous)
        # Writer stage receives new anchor (with avoid) + title reminder ONLY, never old poem lines/JSON
        writer_extra = client.requests[2][1]['task']['extra_requirements']
        self.assertIn('渡口熄灭的铜马灯', writer_extra)
        self.assertIn('避开上一稿的泥土、乌云与旱地讨雨', writer_extra)
        self.assertIn('《旱地裂口》', writer_extra)
        self.assertIn('标题勿与上一稿', writer_extra)
        self.assertNotIn(json.dumps(previous, ensure_ascii=False), writer_extra)
        for old_line in previous['lines']:
            if old_line:
                self.assertNotIn(old_line, writer_extra)

    def test_rewrite_with_none_expansion_passes_only_title_and_first_two_nonempty_lines(self):
        previous = {
            'title': '旱地裂口',
            'lines': ['第一行旧泥土讨雨', '', '第二行仰头逼问乌云', '第三行旧句不该传入', '第四行旧句也不该传入'],
        }
        constraint_only = {
            'genre': 'modern', 'topic': '久旱与回声', 'max_lines': 20,
            'requirements': ['不超过20行'], 'examples': [],
            'required_words': [], 'forbidden_words': [], 'pattern': None, 'unsupported_reason': '',
        }
        client = Client([
            constraint_only,
            {'title': '夜渡', 'lines': ['冰面托住旧船灯', '', '我向水底归还钥匙']},
            checked('冰面'),
        ])
        run_studio('写久旱与回声，不超过20行。', previous=previous, client=client,
                   style_mode='rpe_v4', expansion_mode='none')
        writer_extra = client.requests[1][1]['task']['extra_requirements']
        self.assertIn('《旱地裂口》', writer_extra)
        self.assertIn('第一行旧泥土讨雨 / 第二行仰头逼问乌云', writer_extra)
        self.assertIn('切换起跳物象、时空尺度与发话姿态', writer_extra)
        self.assertNotIn('第三行旧句不该传入', writer_extra)
        self.assertNotIn('第四行旧句也不该传入', writer_extra)
        self.assertNotIn(json.dumps(previous, ensure_ascii=False), writer_extra)

    def test_rewrite_with_native_interpret_omits_previous_poem_body_from_writer(self):
        previous = {'title': '旧河床', 'lines': ['旧水位线刻在石壁上', '旧回信没有抵达']}
        client = Client([brief(), {'title': '新刻度', 'lines': ['水位线留在旧树上']}, checked()])
        run_studio('写给十年后的自己，不超过30行。', previous=previous, client=client)
        self.assertEqual(client.requests[0][1]['previous_poem'], previous)
        writer_extra = client.requests[1][1]['task']['extra_requirements']
        self.assertIn('《旧河床》', writer_extra)
        self.assertNotIn('旧水位线刻在石壁上', writer_extra)
        self.assertNotIn('旧回信没有抵达', writer_extra)
        self.assertNotIn(json.dumps(previous, ensure_ascii=False), writer_extra)



