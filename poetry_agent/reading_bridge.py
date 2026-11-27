"""Narrow source-card matching after independent reading; never tone conversion."""
import re
from .automatic_readings import CARDS,sense_conflict
from .context_review import body_hash

SUPPORTED={
 'zhong_inside':('zhōng',{'里面','之内','之中','范围内'}),
 'you_still':('yóu',{'尚且','仍然','仍旧','依然','还'}),
 'nuan_warm':('nuǎn',{'温热','温暖','使之温热','使变温热'})}

def match_source_cards(poem,report):
    if report.get('body_sha256')!=body_hash(poem['lines']):raise ValueError('语境报告与正文不一致')
    decisions=[];unmatched=[]
    for row in report['readings']:
        i,j=map(int,row['id'].split('-'));char=poem['lines'][i-1][j-1]
        senses={s.strip() for s in re.split(r'[；;、，,/]',row['sense']) if s.strip()}
        matches=[key for key,(pinyin,allowed) in SUPPORTED.items()
                 if CARDS[key]['character']==char and row['pinyin']==pinyin and senses and senses<=allowed
                 and not sense_conflict(poem['lines'][i-1],j,key)]
        if len(matches)!=1:
            unmatched.append(row);continue
        card=CARDS[matches[0]]
        decisions.append({'line':i,'position':j,'character':char,'sense':row['sense'],
            'rationale':'独立语境报告与已核来源卡的读音及有限义项同配；模型理解仍未独立认证。',
            'tone':card['tone'],'rhyme':card['rhyme'],
            'source':card['source']+' ; https://zh.wikisource.org/wiki/平水韻'})
    return {'body_sha256':body_hash(poem['lines']),'reviewer_kind':'assistant','decisions':decisions,
            'unmatched':unmatched,'context_choice_verified':False,'scope':'three_source_senses_only_not_production_override'}
