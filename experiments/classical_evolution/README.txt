古诗作品演化实验入口

本轮目标
复用现代诗RPE遗传算法的种群筛选、相似度生态位和父代配对；演化对象为表达构思与完整诗稿。
不把现代诗风格相似分用在古诗上，也不称作模型训练或已经证明的稳定提升。
首轮固定题集覆盖五绝、七绝。其他已有谱体可由typed Task进入，但本轮结果不证明律诗和词的质量。

链路
1. 原题和硬要求由任务文件明确给定，基本谱由程序提供，不让模型重新解释谱名。
2. 提出三种表达构思，并独立检查是否复述典源或只罗列描写。
3. 各写完整初稿；程序检查形制、禁用词及当前韵表可判定的明确冲突。
4. 盲读题意、表达、语言、用典；不透露作者意图、代数、父子关系。
5. 每代两次定向变异和一次构思层交叉，父代与子代合池，保留三名候选。
6. 两代后重读所有世代；先排除明确不合格者，再选稿，前两名可作对称AB/BA比较。
7. 无合格候选则返回needs_review或incomplete；读音待核单独标注，不能当全谱通过。

命令（在仓库目录中执行）
python -m experiments.classical_evolution.run compose --topic-file examples/classical-evolution-task.json --out runs/my-classical-evolution
python -m experiments.classical_evolution.run benchmark --split pilot --out runs/classical-evolution-pilot-01 --workers 4
python -m experiments.classical_evolution.run report --out runs/classical-evolution-pilot-01
python -m experiments.classical_evolution.run freeze --pilot runs/classical-evolution-pilot-01 --out runs/classical-evolution-freeze-01.json
python -m experiments.classical_evolution.run benchmark --split held_out --repetitions 2 --freeze runs/classical-evolution-freeze-01.json --out runs/classical-evolution-held-01 --workers 4

默认读取同级poetry-agent目录的.env，也可在子命令前用--env-file指定本地文件。
密钥只在本机读取；模型输出、公开典源、调用参数和usage可进入研究记录，认证头与密钥不会写入记录。

对照设计
四题试验后检查问题，再冻结实现、配置、十二题和典源。每题独立运行两次，每次同时跑两个流程。
旧流程为现有studio一个候选+最多三轮独立编辑；新流程为三候选两代作品演化。
两边同一模型、原题、资料及总时间/调用上限；实际使用资源不同，必须同时报告，不能只比较最好作品。
失败也保留在分母，不能悄悄重跑并用成功覆盖失败。相同输出目录恢复时复用已完成操作；输入变化要求新目录。
模型盲读分数是代理指标。24次小样本不能证明所有题目稳定；人工阅读与模型判断分开记录。

记录
experiment-binding.json：题集、配置、模型、代码摘要与预声明的全部任务。
jobs/.../calls/：逐次原始模型输出和输入摘要；call-ledger.json记录已知usage、失败与时间。
jobs/.../expression-plans.json：初构思与构思审查。
jobs/.../generations/：父代、子代、审读、选稿、淘汰，保留完整正文。
jobs/.../state.json：恢复检查点；result.json为该次终态，保留不合格诊断稿。
observations.json：机器可读的资源和门槛结果。
blind-packet.json与作品与运行汇总.txt：隐藏组别的阅读稿。
blind-mapping-private.json：盲稿与组别对应，不能提前交给盲读者。

已知限制
当前历史字表、简繁映射和多音字义项不完整，unknown不等于错字，也不等于已核音。
文学与用典仍有模型误判；验证引文只能证明字句存在，不能证明解释正确。
不直接拼接不同父诗的句子。交叉重组构思后，整首重写并重新检查。
默认每题最多900秒、45次调用；网络超时和恢复边界使它不是硬实时比赛时限。
尚未接入网页或机器人；本阶段以独立文本入口和可审查的实验记录验收。
