"""Four strict basic five-character regulated-quatrain targets, not ancient jueju."""
import re
from .prosody import validate
from .rhyme_data import historical_lexicon

SOURCE = 'https://www.gongfa.com/wanglishilv.htm'
PROFILES = {
    'ze_no_rhyme': ['ZZPPZ', 'PPZZP', 'PPPZZ', 'ZZZPP'],
    'ze_rhyme': ['ZZZPP', 'PPZZP', 'PPPZZ', 'ZZZPP'],
    'ping_no_rhyme': ['PPPZZ', 'ZZZPP', 'ZZPPZ', 'PPZZP'],
    'ping_rhyme': ['PPZZP', 'ZZZPP', 'ZZPPZ', 'PPZZP'],
}


def specification(name):
    if name not in PROFILES:
        raise ValueError('Unknown wujue basic profile')
    return {'id': name, 'tones': list(PROFILES[name]),
            'rhyme_lines_1based': [2, 4] if '_no_' in name else [1, 2, 4],
            'source': SOURCE, 'source_section': '第二章第五节律绝（甲）五言绝句',
            'scope': 'exact_basic_target',
            'limitations': ['仅核指定律绝基本谱，不覆盖古绝、可平可仄、拗救或首句邻韵',
                            'P为平、Z为仄，按旧韵辨音，缺字与多音保留unknown']}


def evidence(lines, profile):
    target = specification(profile)
    normalized = [''.join(re.findall(r'[\u4e00-\u9fff]', line)) for line in lines]
    report = validate(normalized, target['tones'], [(i-1, 4) for i in target['rhyme_lines_1based']],
                      historical_lexicon(), target['source'])
    report['scope'] = 'selected_wujue_basic_target_against_web_main_table'
    return {'status': 'unknown', 'basic_target_check': report,
            'limitations': ['指定基本谱与网页主表检查不等于所有五言绝句的合律认证',
                            '语境音义、异体、文学质量与原创性须另核']}
