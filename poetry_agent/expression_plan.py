"""Validate planning structure without claiming the proposed experience is good."""
import json

FIELDS=('experience','movement','rhetoric','allusion_load','removable_explanation','present_detail')
INSTRUCTION='''
每个方向先探索一种值得表达的具体体验、情感、思考或感知变化，再选择场景、视角与修辞。
不要只有乡愁、温暖等标签，也不强制复杂、尖锐、人物微动作或反转。
另返回expression_options，恰好三个对象，与directions逐项对应，每个含六个非空字符串：
experience（具体表达对象）、movement（全篇怎样建立并推进它）、rhetoric（可不用技巧）、
allusion_load（典故承担哪些背景/关系，不用则写不用及理由）、removable_explanation（因此可省的重复解释，无则说明）、
present_detail（典故不能替代的眼前独有内容）。每项简短。
用典不要求复述典源，未知出处不杜撰；少字或难懂不自动为好，多典可由共同作用中心组织。
删去背景说明时，不可连同表达赖以成立的核心关系一起删去。检查movement是否只列形、声、色、痕而没有体验的推进；若是，重新探索表达路径。
不要求读者复原完整身世，但至少应能从正文感到这些字句为何相互需要；不要只在策划中声称有情感，实际写作却退回可任意互换的物象清单。
这些是可修正的创作假设，不是新增题目要求，成品必须由正文接受独立审读。
'''

def attach_expression_options(brief):
    rows=brief.get('expression_options')
    if not isinstance(rows,list) or len(rows)!=3:raise ValueError('缺少三个表达构思')
    for row in rows:
        if not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not row[k].strip() or len(row[k])>600 for k in FIELDS):
            raise ValueError('表达构思字段无效')
    brief['directions']=[direction+'；表达构思（非新增硬要求）：'+json.dumps({k:row[k] for k in FIELDS},ensure_ascii=False)
        for direction,row in zip(brief['directions'],rows)]
    return brief
