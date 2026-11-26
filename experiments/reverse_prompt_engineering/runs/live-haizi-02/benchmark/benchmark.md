# 对照实验报告

| 组 | 说明 | 风格相似度 | 文学质量 | 题意 | 原创性 | 格式通过率 | 复制率 | API 调用 | Token |
|---|---|---|---|---|---|---|---|---|---|
| A | Baseline A：直接要求模仿目标诗人 | 56.23 | 60.00 | 5.00 | 4.00 | 1.00 | 0.00 | 10 | 16899 |
| B | Baseline B：阅读参考作品后一次性反推 Prompt | 55.76 | 52.00 | 4.80 | 3.40 | 1.00 | 0.00 | 11 | 23235 |
| C | Experimental C：RPE-GA 迭代优化 Prompt | 51.43 | 60.00 | 5.00 | 4.00 | 1.00 | 0.00 | 10 | 19068 |

按风格相似度排序：A, B, C

## 组间差值

```json
{
  "C_minus_A": {
    "style_score": -4.7972,
    "literary_quality_score": 0.0,
    "topic_adherence": 0.0,
    "originality": 0.0,
    "fitness": -4.0776
  },
  "C_minus_B": {
    "style_score": -4.3302,
    "literary_quality_score": 8.0,
    "topic_adherence": 0.2,
    "originality": 0.6,
    "fitness": -2.4807
  }
}
```

## 公平性与独立测试

- same_test_topics: True
- same_reference_set: held_out
- same_generation_parameters_within_group: True
- judge_sees_prompt_or_group: False
- prompts_mutated_after_test: False
- note: A 组按题目生成模仿指令；B/C 使用固定 Prompt。三组均使用相同题目、参考集、生成参数和评审 rubric。

## 局限

- 样本量小，单次运行不能证明统计显著性或普遍优越性。
- 评委可能与被生成模型同家族；即使匿名和独立调用，仍存在自评偏差。
- 风格相似度是特征与 LLM 评审的代理指标，不等于人类读者对‘像’的判断。
- 本次为真实 DeepSeek 调用；仍为单次小样本，不能证明统计显著性或普遍优越性。
- 本次 live 运行经历过中止重跑：live-haizi-01 因 stanza 空行解析和 max_lines 冲突中止；live-haizi-02 早期因 analysis max_tokens 截断中止，并因一个旧进程未完全退出而出现重复 gen1 与额外调用。最终结果来自修复后的完成链；调用/token 为 ledger 累计，包含中止尝试。
- 因此这是一次工程原型试跑，不是预注册的一次性干净实验；不能据此做强因果或统计结论。
- 最终最优候选 g02-m02-1fb0da75 只经过 3 次优化题目评估（score_std=5.39），未进入确认重评；确认重评只覆盖重评前的 top-2，它们分数下降后该候选才成为第一。因此“最优”适应度可能高估，不能视为稳健优胜者。

## 测试题目

| id | 题目 | 体裁 | 要求 |
|---|---|---|---|
| test-01 | 搬家日留下的空房间 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-02 | 山顶气象站停电的夜晚 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-03 | 旧火车站行李寄存处的雨伞 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-04 | 城市天台上的小型菜园 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-05 | 河滩上被风吹走的帐篷 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |

