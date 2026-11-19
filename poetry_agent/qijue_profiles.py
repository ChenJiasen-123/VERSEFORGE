"""Exact basic targets from Wang Li, not all permissible metrical variants."""
SOURCE = 'https://www.gongfa.com/wanglishilv.htm'
PROFILES = {
    'ping_rhyme': ['PPZZZPP', 'ZZPPZZP', 'ZZPPPZZ', 'PPZZZPP'],
    'ping_no_rhyme': ['PPZZPPZ', 'ZZPPZZP', 'ZZPPPZZ', 'PPZZZPP'],
    'ze_rhyme': ['ZZPPZZP', 'PPZZZPP', 'PPZZPPZ', 'ZZPPZZP'],
    'ze_no_rhyme': ['ZZPPPZZ', 'PPZZZPP', 'PPZZPPZ', 'ZZPPZZP'],
}


def specification(name):
    if name not in PROFILES:
        raise ValueError('Unknown qijue basic profile')
    return {'id': name, 'tones': list(PROFILES[name]),
            'rhyme_lines_1based': [1, 2, 4] if name.endswith('_rhyme') and '_no_' not in name else [2, 4],
            'source': SOURCE, 'scope': 'exact_basic_target',
            'limitations': ['只要求本次生成遵循基本谱，不代表其他合法变格均出律',
                            '首句同韵；不在此目标内开放邻韵或拗救', 'P为平、Z为仄，须按所选旧韵辨音']}
