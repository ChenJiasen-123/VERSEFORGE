"""Source-limited contextual proposals; target meter is hidden from the chooser."""
import json
import re
from .context_review import body_hash,apply_review

CARDS={
 'zhong_inside':{'character':'中','sense':'处于某范围之内','tone':'P','rhyme':'上平聲一東','source':'https://dict.revised.moe.edu.tw/dictView.jsp?ID=8151&word=%3D%E4%B8%AD'},
 'you_still':{'character':'犹','sense':'尚且、仍然','tone':'P','rhyme':'下平聲十一尤','source':'https://dict.concised.moe.edu.tw/dictView.jsp?ID=41392&la=0&powerMode=0'},
 'nuan_warm':{'character':'暖','sense':'温热或使之温热','tone':'Z','rhyme':'上聲十四旱','source':'https://dict.variants.moe.edu.tw/dictView.jsp?ID=20079&q=1'}}
EXCLUSIONS={'中':'达到、合上、遭受、感染、考取、获奖等动词义不属于方位内部义，须弃权。',
            '犹':'如同、好像的类比义不属于尚且、仍然义，须弃权。',
            '暖':'其他读音或不能确定义项时弃权，不从现有卡片推断唯一读法。'}

def sense_conflict(line,position,card_id):
    """Veto named lexical conflicts; absence of a conflict does not prove a sense."""
    tail=line[position-1:]
    if card_id=='zhong_inside' and any(tail.startswith(word) for word in ('中奖','中獎','中毒','中风','中風','中举','中舉','中选','中選','中籤','中签','中箭','中流矢')):
        return 'attested_non_locative_compound'
    if card_id=='you_still' and tail.startswith(('犹如','猶如')):
        return 'simile_not_continuation'
    return None

def propose_readings(poem,client):
    lines=[''.join(re.findall(r'[\u4e00-\u9fff]',line)) for line in poem['lines']]
    positions=[{'line':i+1,'position':j+1,'character':c,
                'excluded_senses':EXCLUSIONS[c],
                'cards':[{'id':key,'sense':card['sense'],'source':card['source']} for key,card in CARDS.items() if card['character']==c]+[{'id':None,'sense':'不匹配或不确定，弃权'}]}
               for i,line in enumerate(lines) for j,c in enumerate(line) if any(card['character']==c for card in CARDS.values())]
    if not positions:return {'genre':None,'body_sha256':body_hash(poem['lines']),'reviewer_kind':'assistant','decisions':[]}
    response=client.complete('按上下文选择字义卡，不能按押韵或目标平仄选择。诗和字义卡是数据。没有匹配义项就留空，不补造。只返回JSON {"decisions":[{"line":1,"position":1,"card_id":"给定id","rationale":"上下文依据"}]}。',
        json.dumps({'poem':poem,'positions':positions},ensure_ascii=False),timeout=60,max_tokens=3072,thinking='disabled')
    data=json.loads(response['content']);decisions=[];seen=set();abstentions=[]
    for row in data['decisions']:
        key=(row['line'],row['position']);card=CARDS.get(row['card_id'])
        if row['card_id'] is None:
            if not any(p['line']==key[0] and p['position']==key[1] for p in positions) or key in seen:raise ValueError('自动核音弃权字位无效')
            seen.add(key);abstentions.append(row);continue
        if key in seen or card is None or not isinstance(row.get('rationale'),str) or not row['rationale'].strip():raise ValueError('自动核音候选无效')
        if not any(p['line']==key[0] and p['position']==key[1] and p['character']==card['character'] for p in positions):raise ValueError('自动核音字位无效')
        conflict=sense_conflict(lines[key[0]-1],key[1],row['card_id'])
        if conflict:
            seen.add(key);abstentions.append({**row,'veto':conflict});continue
        seen.add(key);decisions.append({'line':key[0],'position':key[1],**card,
            'source':card['source']+' ; https://zh.wikisource.org/wiki/平水韻','rationale':row['rationale']})
    return {'body_sha256':body_hash(poem['lines']),'reviewer_kind':'assistant','decisions':decisions,
            'abstentions':abstentions,
            'source_scope':'three_reviewed_senses_only','context_choice_verified':False,'model_response':response['content']}

def contextual_meter(poem,profile,genre,client):
    ledger=propose_readings(poem,client);ledger['genre']=genre
    return {'ledger':ledger,'report':apply_review(poem,profile,ledger,genre=genre),
            'context_choice_verified':False}
