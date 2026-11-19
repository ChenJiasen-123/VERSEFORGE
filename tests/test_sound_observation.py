import json
import unittest
from poetry_agent.aesthetics import review, failure_code


class Reply:
    def __init__(self, quote): self.quote = quote
    def complete(self, *args, **kwargs):
        return {'content': json.dumps(dict(decision='keep', preserve='重复的压力', quote='灯',
            problem='词短但作用有前文支撑', keep_reason='不需要为了整齐增加句子', suggestion='', tradeoff='',
            text_sound=dict(quote=self.quote, mechanism='短句', semantic_effect='暂停辨认', uncertainty='也可接续读',
                            basis={'kind':'interpretation','why_unverified':'未独立分析句法'})))}


class SoundObservationTests(unittest.TestCase):
    def test_modern_keep_without_sound_analysis_is_incomplete(self):
        class MissingSound(Reply):
            def complete(self, *args, **kwargs):
                result = super().complete(*args, **kwargs)
                data = json.loads(result['content'])
                del data['text_sound']
                return {'content': json.dumps(data)}
        with self.assertRaises(ValueError) as error:
            review({'lines': ['灯']}, {'genre': 'modern'}, MissingSound('灯'), 10)
        self.assertEqual(failure_code(error.exception), 'missing_text_sound')

    def test_sound_evidence_must_exist_in_the_poem(self):
        with self.assertRaises(ValueError):
            review({'lines': ['灯']}, {'genre': 'modern'}, Reply('风'), 10)

    def test_paper_analysis_is_not_claimed_as_listening(self):
        result = review({'lines': ['灯']}, {'genre': 'modern'}, Reply('灯'), 10)
        self.assertEqual(result['text_sound_status'], 'recorded_not_auditory_verified')
        self.assertEqual(result['text_sound_basis_check']['status'], 'not_program_verified')

    def test_wrong_count_cannot_be_accepted_as_a_valid_review(self):
        class WrongCount(Reply):
            def complete(self, *args, **kwargs):
                data = json.loads(super().complete(*args, **kwargs)['content'])
                data['text_sound']['basis']={'kind':'literal_repeat','fragment':'再数一次','occurrence_count':3}
                return {'content':json.dumps(data)}
        with self.assertRaises(ValueError) as exc:
            review({'lines':['灯','再数一次她说再数一次']}, {'genre':'modern'}, WrongCount('再数一次'), 10)
        self.assertEqual(failure_code(exc.exception), 'invalid_sound_basis')
