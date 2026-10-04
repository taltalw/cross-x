# 第 1 步：选择融合领域并生成构题思路

根据原子样本和 key facts，让模型从其余六个领域中选择一个组合，给出简洁的问题构造思路和四类答案构造思路。用户只指定总领域数量，不指定领域名称。

完整中英文提示词见 [双语模板](1_generate_fusion_plans_prompt_bilingual.md)。

## 输入与消息模板

输入为步骤 0 JSONL，包含 `source_file`、`source_domain`、`model`、`sample`、`key_facts`。`sample` 保存原始问答。
系统提示词使用代码中的 `SYSTEM_PROMPT`，每条用户消息传入 `source_domain`、`sample`、`key_facts`、`candidate_domains`、`domain_count`。`candidate_domains` 是除源领域外的六个领域及其英文介绍。

`--domain-count N` 范围为 2–7，包含源领域；例如 N=3，模型选择两个其他领域。每条样本恰好生成一个组合和一套思路，不再接受 `--fusion-domains`。

## 模型输出模板

下面只示意两个新增领域；实际领域由模型选择，不固定为 medical/legal。

```json
{
  "fusion_domains": ["medical", "legal"],
  "question_plan": "围绕地理位置、健康影响和法律义务设计一个联合判断任务。",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "正确整合所有领域知识的思路"},
    {"type": "missing_domain_knowledge", "missing_domain": "medical", "plan": "缺失一个领域的必要知识"},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "忽略相互作用，仅并列知识"},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "错误连接领域关系"}
  ]
}
```

程序校验所选领域恰好 N−1 个、互不重复、属于候选列表且不含源领域；`question_plan` 必须是非空字符串，四类答案各一次。保存字段为输入的来源和样本信息、更新后的 `model`、`domain_count` 及上述模型输出。字段中的中文示意在实际运行时使用英文。

## 运行

```bash
# 先设置 API_BASE_URL、API_KEY、MODEL。
NUM=100 bash knowledge/pipielines_v4/run_1.sh
```

入口依次处理七个源领域和总领域数 2、3、4；默认输入、输出位于 `V4_ROOT`。只运行某个领域或数量时，可直接调用 Python 脚本并指定 `--input`、`--output`、`--domain-count`。

已有输出需要 `--overwrite` 才能覆盖；逐行写入并保留失败前已完成的结果。
