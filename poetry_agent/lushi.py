"""Eight-line strict basic targets; semantic parallelism remains unverified."""
import re
from .wujue import PROFILES as FIVE
from .qijue_profiles import PROFILES as SEVEN
from .prosody import validate
from .rhyme_data import historical_lexicon

SOURCE = 'https://www.gongfa.com/wanglishilv.htm'
CROSSCHECK = 'https://www.ziyexing.com/files-2/wangli/shicigelv_08.htm'


def specification(genre, name):
    if genre not in ('wulv', 'qilv') or name not in FIVE:
        raise ValueError('律诗须指定五律／七律及有效基本谱')
    profiles = FIVE if genre == 'wulv' else SEVEN
    start = name.split('_')[0]
    # Only line 1 changes in first-line rhyme variants; line 5 must not rhyme.
    tones = list(profiles[start + '_no_rhyme']) * 2
    tones[0] = profiles[name][0]
    return {'id': name, 'genre': genre, 'tones': tones,
            'rhyme_lines_1based': [2, 4, 6, 8] if '_no_' in name else [1, 2, 4, 6, 8],
            'parallel_couplets_1based': [[3, 4], [5, 6]],
            'source': SOURCE, 'search_excerpt_crosscheck': CROSSCHECK,
            'source_section': '第二章第三节律诗平仄、第四节中两联对仗',
            'scope': 'exact_eight_line_basic_target',
            'limitations': ['只核严格基本谱，不穷尽可平可仄、拗救、邻韵与特殊对仗格式',
                            '语境音义仍须核对；颔颈联词义及句法对仗不由平仄检查认证']}


def evidence(lines, genre, profile):
    target = specification(genre, profile)
    width = 5 if genre == 'wulv' else 7
    normalized = [''.join(re.findall(r'[\u4e00-\u9fff]', line)) for line in lines]
    report = validate(normalized, target['tones'], [(i-1, width-1) for i in target['rhyme_lines_1based']],
                      historical_lexicon(), target['source'])
    report['scope'] = 'selected_lushi_basic_target_against_web_main_table_and_glyph_candidates'
    return {'status': 'unknown', 'basic_target_check': report,
            'parallelism': {'status': 'unknown', 'required_couplets_1based': target['parallel_couplets_1based'],
                'couplets': [{'lines': pair, 'texts': [lines[i-1] if i <= len(lines) else '' for i in pair]}
                             for pair in target['parallel_couplets_1based']],
                'semantic_check_performed': False},
            'limitations': target['limitations']}
