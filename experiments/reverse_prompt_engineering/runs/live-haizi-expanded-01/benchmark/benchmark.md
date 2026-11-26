# 对照实验报告

| 组 | 说明 | 风格相似度 | 文学质量 | 题意 | 原创性 | 格式通过率 | 复制率 | API 调用 | Token |
|---|---|---|---|---|---|---|---|---|---|
| A | Baseline A：直接要求模仿目标诗人 | 51.71 | 60.00 | 5.00 | 4.00 | 1.00 | 0.00 | 20 | 53007 |
| B | Baseline B：阅读参考作品后一次性反推 Prompt | — | — | — | — | 0.00 | 0.00 | 2 | 7342 |
| C | Experimental C：RPE-GA 迭代优化 Prompt | 58.63 | 66.00 | 4.90 | 4.00 | 1.00 | 0.00 | 20 | 58976 |

按风格相似度排序：C, A

## 组间差值

```json
{
  "C_minus_A": {
    "style_score": 6.9223,
    "literary_quality_score": 6.0,
    "topic_adherence": -0.1,
    "originality": 0.0,
    "fitness": 6.7839
  },
  "C_minus_B": {
    "style_score": null,
    "literary_quality_score": null,
    "topic_adherence": null,
    "originality": null,
    "fitness": null
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

## 测试题目

| id | 题目 | 体裁 | 要求 |
|---|---|---|---|
| test-01 | 搬家日留下的空房间 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-02 | 山顶气象站停电的夜晚 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-03 | 旧火车站行李寄存处的雨伞 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-04 | 城市天台上的小型菜园 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-05 | 河滩上被风吹走的帐篷 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-06 | 海边灯塔的最后一位守塔人 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-07 | 老式电影院散场后的放映室 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-08 | 雪后山村的有线广播站 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-09 | 城市地下通道里的修鞋摊 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |
| test-10 | 水库泄洪前夜的观测站 | modern | 12—20行，分2—4节；每节1—6行；不得出现任何诗人姓名。 |

