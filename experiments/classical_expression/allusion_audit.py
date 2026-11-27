"""Source-grounded independent reading. Valid quotes do not certify interpretation."""
import json

SYSTEM='''你是古典诗用典审读者。只看题目、正文与给定典源卡，不知道作者意图。
先辨正文实际调用什么典，再判断典源与此诗处境的关系。明用暗用是显隐程度，顺用翻用是意义方向，不强迫它们互斥。
转到新题不自动叫翻用；翻用须改变、质疑或反拨原有意义。保留旧物不自动等于得鱼忘筌。
不能替正文补造人物经历、因果和动机。可以不用典，不能为典故数量加分。
识别叠典、复述故事、近似古雅词却无表达关系，以及没有必要的解释要求。允许议论、直抒、反问和留白。
只返回JSON：{"reading":"正文实际表达","references":[{"card_id":"给定ID","quote":"正文某行连续片段","function":"典故怎样改变意义或无作用","direction":"顺用/翻用/未确定"}],
"issues":[{"quote":"正文某行连续片段","problem":"实际问题","repair":"修改方向"}],"decision":"keep或revise"}。
未发现可支持的典故时references可为空，不强猜。所有引文逐字复制，不拼接。'''

def payload(prompt,poem,cards):
    return {'prompt':prompt,'poem':{'title':poem['title'],'lines':poem['lines']},'source_cards':cards}

def validate(data,poem,cards):
    if not isinstance(data,dict) or data.get('decision') not in ('keep','revise') or not isinstance(data.get('reading'),str):
        raise ValueError('用典审查结构无效')
    for key in ('references','issues'):
        if not isinstance(data.get(key),list):raise ValueError('用典审查列表无效')
        for row in data[key]:
            if not isinstance(row,dict) or not isinstance(row.get('quote'),str) or not row['quote'] or not any(row['quote'] in s for s in poem['lines']):raise ValueError('用典审查引文无效')
            fields=('function','direction') if key=='references' else ('problem','repair')
            if any(not isinstance(row.get(k),str) or not row[k].strip() for k in fields):raise ValueError('缺少判断依据')
            if key=='references' and row.get('card_id') not in {c['id'] for c in cards}:raise ValueError('典源ID无据')
    return []

def audit(prompt,poem,cards,llm):
    data,meta=llm.call_json(purpose='independent_allusion_audit',system=SYSTEM,
        user=json.dumps(payload(prompt,poem,cards),ensure_ascii=False),max_tokens=2600,thinking='disabled',
        validator=lambda d:validate(d,poem,cards))
    return {'data':data,'meta':meta,'interpretation_verified':False}
