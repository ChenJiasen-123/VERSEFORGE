import json
import unittest
from poetry_agent.aesthetics import review, failure_code


class Reply:
    def __init__(self, quote): self.quote = quote
    def complete(self, *args, **kwargs):
        return {'content': json.dumps(dict(decision='keep', preserve='重复的压力', quote='灯',
            problem='词短但作用有前文支撑', keep_reason='不需要为了整齐增加句子', suggestion='', tradeoff='',
            text_sound=dict(quote=self.quote, mechanism='短句', semantic_effect='暂停辨认', uncertainty='也可接续读')))}


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
