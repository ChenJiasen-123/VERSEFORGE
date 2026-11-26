# 产物完整性说明（live-haizi-expanded-progression-01）

## 结论

本目录的最终结果完整；但 `state.json`、`run.json`、`events.jsonl`、`ledger.jsonl`、`cache.jsonl`
这五个顶层文件停在**第 25 代（2026-11-26T02:09Z）**，不是运行结束时的版本。

以 `report.md`、`final_prompt.*`、`final_population.json`、`benchmark/`、`population/gen_026.json`、
`population/gen_027.json` 为准。状态：**completed**，第 27 代因 patience 提前停止。

## 时间线（本机 +08:00）

| 时间 | 事件 |
|---|---|
| 09:55 | 以 `--resume` 从第 22 代续跑 |
| 10:07 | 第 25 代完成并写 `checkpoints/gen_025/` |
| 10:10 | 提交 `3a76962` 归档运行目录，快照为第 25 代 |
| 10:17—10:20 | 第 26、27 代；`final_population.json`、`final_prompt.*` 写入 |
| 10:27 | 提前停止（patience=5），写 `report.md`、`benchmark/`；运行结束 |
| 11:16 | 切换 git 分支时，git 用 10:10 提交的版本覆盖了被跟踪的五个文件 |

## 影响

- `state.json` 显示 `status=running`、`generation=25`、`pending_generation` 非空；**不要据此续跑**，
  否则会重做第 26、27 代并覆盖最终产物。
- `run.json` 的 `status` 同样是过期值。
- `events.jsonl` 缺第 26、27 代事件；`ledger.jsonl` 与 `cache.jsonl` 缺对应的调用记录（约 2.1MB）。
- 调用与 token 总量仍以 `report.md` 第 9 节为准：1444 次调用、4,986,853 token、1295.9 秒。
- 丢失的只是审计尾部；诗作、评分、变异、种群、检查点、对照实验数据均在。

## 为什么没重建

`state.json` 只能从 `report.md` 与逐代 JSON 近似拼回，拼回值会与真实运行不一致。
为避免把推测写成记录，这里保留第 25 代快照并显式标注，而不是伪造一份“完成”状态。
