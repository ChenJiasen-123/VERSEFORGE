import unittest
import xml.etree.ElementTree as ET
from poetry_agent.robot import speech_ssml


class SpeechTests(unittest.TestCase):
    def test_text_cannot_insert_ssml_commands(self):
        lines = ['<break time="9s"/>', '风 & 雨']
        root = ET.fromstring(speech_ssml({'lines': lines}))
        self.assertEqual(''.join(root.itertext()), ''.join(lines))
        breaks = root.findall('{http://www.w3.org/2001/10/synthesis}break')
        self.assertEqual([b.attrib['time'] for b in breaks], ['350ms'])

    def test_no_pause_and_invalid_duration(self):
        self.assertNotIn('<break', speech_ssml({'lines': ['甲', '乙']}, 0))
        with self.assertRaises(ValueError):
            speech_ssml({'lines': ['甲']}, -1)
