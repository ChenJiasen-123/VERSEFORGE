# 古典绝句表达策略实验

状态：evolution-01 已结束，三代演化与留出正反序比较结果见 reports/evolution-01/REPORT.md；不能据此认定文学质量提高。阅读材料见 READINGS_01/02/03；用典专项的已知问题与未通过稿见 allusion-study-01/REPORT.md。以下运行说明及局限保留供复查，实际完成情况以报告和记录为准。

范围：五绝、七绝；探索表达对象，之后选择视角、结构、用典／对面落笔／移情／白描等路径。不要求技巧、尖锐、反转或末句点题。

`topics.json` 固定6道优化题与6道留出题，校验值记录在 `preregistration.json`。

运行：`python -m experiments.classical_expression.run` 只估算；加 `--live --run-id 新名称` 在首道优化题上测试3份初始策略。`--live --full --run-id evolution-01` 已用于本次正式实验，勿并发启动相同run-id。

复用现有RPE的Budget、LLMCache、JsonlLedger及JSON调用层。当前DeepSeek传输不支持temperature参数，三组统一沿用服务默认。盲读只收原题、标题与正文，不接收创作意图。引文验证不能认证解释正确。

已实现：源码/题集/知识文件版本绑定、代际pending快照、已完成作品复用、格式与题意优先的序数筛选、表达盲读驱动最多3轮改稿。序数排序不是校准后的文学分数，风险数量等代理可能有偏差，不能据此宣布审美改善。

局限与后续事项：失败调用用量仍未知；逐轮持久化和离线重放的覆盖范围须按报告核对；典故审读不构成语义正确性证明；18首留出及正反序比较已完成，但大量判断不一致，未进行独立人类盲评。额外加入audit.py后，源码全集指纹会改变，旧运行不可直接重启，需要先核对运行时源码版本。不能通过改写旧binding绕过。

离线核查：`python -m experiments.classical_expression.audit evolution-01`。生成reports下的audit、blind、mapping-private；评阅时仅提供blind，映射及模型自评不交给读者。该工具列清单，不验证诗歌解释的正确性。

API记录不含请求头或密钥；`.env`不入库。试跑不改动网页生产流程。
