# 格式门修正：分节与行数下限此前未被检查

## 问题

`poetry_agent.core.check` 对现代诗只检查 `len(lines) > max_lines`，没有检查：

- 总行数下限（题目要求 12—20 行）
- 分节数（分 2—4 节）
- 每节行数（每节 1—6 行）

题目要求原本只在 `extra_requirements` 里以文本形式存在，从未被执行。
因此 `benchmark/benchmark.json` 第 8 节的 `form_ok_rate` 偏乐观。

## 用完成后的 30 首诗重算（同一个 run，离线，无 API 调用）

| 组 | 旧 form_ok | 新 form_ok | 旧 fitness | 新 fitness | 违规 |
|---|---|---|---|---|---|
| A | 1.00（10/10） | **0.80（8/10）** | 47.61 | **44.61** | test-06 只有 10 行、test-10 只有 8 行 |
| B | 1.00（10/10） | **0.80（8/10）** | 56.15 | **50.15** | test-05 写了 6 节、test-06 第 2 节 7 行 |
| C | 0.80（8/10） | **0.60（6/10）** | 52.97 | **46.97** | test-02 第 3 节 7 行、test-07 第 2 节 7 行、test-10 只有 1 节 |

排序未变：B > C > A。C 仍未通过硬约束门槛，且差距（C−B）从 −3.18 变为 −3.18。

结论不变但更严重：A、B 也不是“格式全对”，此前“C 只是格式差”的说法低估了三组共同的违规。

## 修复

`experiments/reverse_prompt_engineering/generator.py`：

- 新增 `stanza_shape(raw_lines)`：按空字符串切分，得到每节行数
- 新增 `requirement_issues(raw_lines, topic)`：从题目 `requirements` 解析
  “12—20 行”“分 2—4 节”“每节 1—6 行”并逐条检查
- `generate_poem` 的 `form_issues` 改为 `check(...) + requirement_issues(...)`

测试：新增 `tests/test_format_gate.py`（6 个用例）；`tests/test_corpus_and_metrics.py`
的分节用例改为 12 行 3 节（原 fixture 只有 4 行，能通过只是因为门没查下限）。
RPE 测试 27 个全部通过。

## 注意

`live-haizi-compact-01` 在修复前已启动，进程内还是旧的格式门；它的对照结果需要用同一
方法离线重算后才能比较。
