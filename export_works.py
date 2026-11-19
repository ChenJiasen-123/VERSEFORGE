"""Export a small, explicitly selected anthology from recorded API outputs."""
import json
from pathlib import Path

ROOT = Path(__file__).parent


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def export():
    items = []
    source = 'runs/evaluation-22aa0a7a9d7549dda235716080adfff8/raw.json'
    result = next(x['result'] for x in read(source) if x['arm'] == 'aesthetic')
    items.append((result['poem'], source, '真实API候选；工人形象及日常细节仍可质疑，未获独立文本优胜标签。'))
    source = 'runs/evaluation-0ec515826ff34205882a52d0ea801820/raw.json'
    result = next(x['result'] for x in read(source) if x['arm'] == 'aesthetic' and x['pair'] == 2)
    items.append((result['poem'], source, '真实API候选；动作迟疑较清楚，结尾比喻仍较常见。'))
    source = 'runs/e70eafa3f2a94516a9bf1faf3dc137dc.json'
    items.append((read(source)['poem'], source, '真实API双稿模型选出；屏幕收走话语等解释仍有分歧，非独立评审优胜。'))
    source = 'runs/0bb992abb57943bfba50d409bf8caa99-literary-revision.json'
    items.append((read(source)['poem'], source, '真实API单字修订稿，归舟改归人。原稿有单独的语境声韵复核，修订稿自动报告仍待核，不混用两个版本的验收结论。'))
    source = 'runs/ad895a55c6fb4bd1a4c8cead3f28b22d.json'
    items.append((read(source)['poem'], source, '保留真实API原稿，后续候选未明确胜出；积雪与露水的感知连接、语境读音仍待核。'))
    source = 'runs/8855e36e0d544d249a33613b1a3a31ba.json'
    items.append((read(source)['poem'], source, '真实API原稿；只覆盖白香词谱李煜例作谱体，词韵与多音异体未完成自动验收，末句动作关系待精修。'))
    text = ['# 项目诗词作品选\n', '从已保存的真实API运行中选择六篇，保留原始字形和标点。这里的“选”是整理范围，不代表评奖排名、人工认可、原创性认证或参数微调成果。助手另写的备选没有混入这份API作品集。\n']
    for poem, source, note in items:
        text.append('## ' + poem['title'] + '\n')
        text.append('  \n'.join(poem['lines']) + '\n')
        text.append(note + '\n')
        text.append('[原始记录](' + source.replace('\\', '/') + ')\n')
    (ROOT / 'WORKS.md').write_text('\n'.join(text), encoding='utf-8')
    return len(items)


if __name__ == '__main__':
    print('Exported recorded works:', export())
