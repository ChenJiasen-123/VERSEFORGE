import json
import unittest
from pathlib import Path


class CiTranscriptionTests(unittest.TestCase):
    def test_annotated_symbols_and_runtime_pattern_agree(self):
        path = Path(__file__).parents[1] / 'poetry_agent/data/ci-profiles.json'
        profile = json.loads(path.read_text(encoding='utf-8'))['profiles']['baixiang_yijiangnan_liyu']
        mapping = str.maketrans({'○':'P', '●':'Z', '⊙':'X', '△':'P'})
        self.assertEqual([s.translate(mapping) for s in profile['source_symbols']], profile['tones'])
        self.assertEqual([len(s) for s in profile['tones']], profile['line_lengths'])
        # 昨夜夢魂中: the annotated third position is 仄, not 平.
        self.assertEqual(profile['tones'][1][2], 'Z')
        self.assertIsNone(profile['rhyme_system'])
