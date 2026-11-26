# 现代诗风格工作流（Modern Poetry Studio）

这是一个独立实验模块，不改变原有 `main.py` 创作流程。目标是先建立**可解释、可反驳的表面测量**，再把测量编译成短提示词，用真实 API 生成文本，最后交给阅读与盲评。它不是“自动诗评器”，也不是已经验证的风格迁移系统。

## 为什么先做测量

前序 RPE-GA 的 live 运行留下了重要负结果：

- 同模型 Judge 饱和：42 条评审中 `lineation`、`literary_quality` 几乎全为 3.0，`originality` 全为 4.0。
- 确定性风格分被字面重合项主导：字符 bigram 与行尾相似度对换题生成天然接近 0。
- Prompt 从 9 条膨胀到 11 条，出现“至少一节 3 行”“器物类不超过两个”“不得使用多年后”等对优化题目过拟合的规则。
- 生成稿有局部好句，但整体更像“按规则拼装的现代诗”。

因此本模块不再直接优化一个总分，而是先问：

1. 这个指标在诗人内部稳定吗？
2. 它能区分诗人吗？
3. 它能区分人类诗与已有模型稿吗？
4. 它的方向与文学阅读判断一致吗？

只有通过审计、且有诗论依据的特征才进入提示词。

## 快速开始

在仓库根目录运行：

```powershell
# 1) 离线审计：不调用 API
python -m experiments.modern_poetry_studio.run audit

# 2) 编译提示词（不调用 API）
python -m experiments.modern_poetry_studio.run prompt --variant style_card_anti_slop --max-lines 20

# 3) Mock 生成，验证流程
python -m experiments.modern_poetry_studio.run generate --mode mock --prompt var/modern_poetry_studio/prompt-all-style_card_anti_slop.json

# 4) 评估某个运行目录
python -m experiments.modern_poetry_studio.run evaluate --run var/modern_poetry_studio/generations/<run_id>

# 5) 离线跑审计 + 全部提示词
python -m experiments.modern_poetry_studio.run all-offline

# 6) 从两次运行生成匿名 A/B 盲评包
python -m experiments.modern_poetry_studio.blind `
  --baseline-run var/modern_poetry_studio/generations-live/<baseline> `
  --style-run var/modern_poetry_studio/generations-live/<style> `
  --output var/modern_poetry_studio/blind-01
```

真实调用必须显式授权：

```powershell
python -m experiments.modern_poetry_studio.run generate `
  --mode live --authorize-spend `
  --prompt var/modern_poetry_studio/prompts/style-card-all.json
```

## 文件

| 文件 | 作用 |
|---|---|
| `poetry_agent/style/stylometry.py` | 单篇 profile、语料分布、反模式 flags、log-odds 区分词 |
| `audit.py` | 三诗人 + 既有模型稿的离线审计，输出 AUC / 稳定性 / 分布 |
| `prompt.py` | 把语料 profile 编译成可检查的短提示词 |
| `generate.py` | mock / live 生成，JSON 解析重试，保存 ledger |
| `evaluate.py` | 生成稿与人类带的表面距离、flags、阅读稿 |
| `blind.py` | 隐藏标题/方法、随机 A/B、生成盲评表与映射 |
| `run.py` | 统一 CLI |
| `tests/test_stylometry.py` | 指标单元测试 |
| `tests/test_modern_studio.py` | 解析、提示词、mock 流程测试 |

输出默认在 `var/modern_poetry_studio/`（已被 `.gitignore` 忽略），避免把语料全文、运行稿或付费结果误提交。

## 指标层

### 分布指标

行数、节数、行长中位数、行长变异系数、短行率、长行率、行末标点率、行末逗号率、无标点断行率、行首/行末虚词率、TTR、hapax、重复率、虚词占比、代词率、抽象词率、解释性连词率、问句/感叹/祈使标记率、判断词率、明喻率、标点密度、分句长度、节长变异、重复行、相邻行同头、相邻节字面回返、首尾回返、的/地/得密度、具体字面词密度、末行长度/标点/总结标记/明喻标记。

这些指标只回答“表面分布在哪里”，不回答“是不是好诗”。

### 反模式 flags

- 每行几乎都以标点收尾
- 行长过于均匀
- 长行多且句末闭合，接近分行散文
- 解释性连词偏多
- 抽象/情绪词密度偏高
- 通用抒情词偏多
- 明喻偏多
- 末行像总结/格言
- 末行以明喻封闭
- 破折号/省略号偏多
- 重复行比例偏高
- 问句行比例偏高

flags 是**诊断**，不是禁用词表。人类诗（如北岛《一切》）也会触发“抽象词偏多”“总结式结尾”，但仍成立。flag 命中不等于失败，flag 为零也不等于合格。

### 与文学研究的关系

见 [`research/modern-poetics-workflow-01.md`](../../research/modern-poetics-workflow-01.md)。核心约束：

- 分行是证据，不是分数；纸面分行不能证明朗读停顿。
- 抽象词、直接陈述、总结式结尾不是自动失败；要看前文是否支撑。
- 具体物象也会变成清单；要看动作、位置、尺度、时间是否变化。
- 重复次数不是诗性；回返是否改变关系才是。
- 结尾要承接，不必升华。

## 提示词层

`prompt.py` 只写入有诗论依据、且可操作的特征：

- 硬性行数上限；
- 行长中位数与短行率范围；
- 行末标点应少、无标点断行应多；
- 行长要有长短差；
- 少用解释性连词；
- 明喻不要密集，不要用“像……”给每节补结论；
- 重复要改变位置/对象/语气/句法功能；
- 结尾要承接，不要补可替换格言；
- 可选反模式段。

不写入诗人姓名、原诗、标志性名词清单，也不强制“每首必须有金句”。

## 当前 live-01 结果（小样本，不是结论）

详细报告：`var/modern_poetry_studio/live-01-comparison.md`（本地）。

- 基线 3 首：行长中位数 11、行长 CV 0.08、行末标点率 75%、短行率 0%、无标点断行率 27%；像分行散文。
- 风格卡 3 首：行长中位数 8、CV 0.28、行末标点率 0%、短行率 10.5%、无标点断行率 100%；表面分布接近人类留出集。
- 风格卡《操场上的水痕》《凌晨三点的售货机》《夜班渡轮》都有可保留的局部；但风格卡组经过重试与跨运行拼组，**不是受控对照**。
- in-band 96.7% 是“按目标区间做出来的”，不能当质量成绩。
- 仍需同轮对照 + 人类盲评；没有盲评不得声称“更像诗”或“质量提升”。

## 已知限制

1. 字符级指标不能识别词义、句法结构、反讽、说话位置和意象关系。
2. 反模式阈值部分来自人类语料分位数，部分来自手工常数，尚未外部验证。
3. 模型稿与人类语料题材不同，AUC 差异可能混入题材因素。
4. 当前 live 样本量小，且存在重试、超行、JSON 解析失败；生成模型对“行数硬上限”仍不完全服从。
5. 同模型 Judge 不作为主评；本模块目前没有 Judge，只输出阅读稿。
6. 没有人类盲评，不能得出审美提升结论。

## 下一步

1. 同一轮内跑 baseline / style_card / style_card_anti_slop，各题 2 次，避免跨运行拼组。
2. 将 6—9 首匿名文本交给真实读者，做配对偏好与四项评分：像诗、分行必要、意象关系、结尾承接。
3. 若盲评无差异，停止加规则；若 style_card 有稳定优势，再测试短版提示词。
4. 只有通过盲评后，才考虑把提示词搜索（RPE-GA 或 EvoPrompt 类方法）重新引入，并限制搜索空间与长度。
