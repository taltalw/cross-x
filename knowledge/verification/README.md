# Verification：三层质量评审分享包

先读[三层审计与LLM五维评分综合指南](三层审计与LLM五维评分_综合阅读指南.md)：每个指标的用途、当前公式、输入输出、运行命令及实施状态均在其中。

- [Process Auditing指标导航](process_auditing/README.md)：DDE、KNC、KRC、CDNS。
- [设计文档与附图索引](process_auditing/design_docs/README.md)：区分当前实现与历史方案。
- [LLM五维评审说明](llm_judge/LLM5_README.md)：英文Prompt、两阶段评审、复核和统计。
- [必要性规则与单样本复测](llm_judge/LLM5_必要性规则修复与单样本复测_20261005.md)。

只分享指标设计、实现、现有证据及离线测试，发送本verification文件夹的ZIP即可；完整原语料重算还需pipielines_v4输出、atomic数据和实际模型服务。ZIP不包含完整原语料、密钥、模型权重或Python环境，但现有报告内包含评测样本和材料。

Human Verification仅完成设计和机器路由，没有实际人工裁决；CDNS结果为模拟，LLM5结果为同模型单题流程测试。不要把它们表述成全量独立质量验收。

解压后进入本目录，使用综合指南中的相对路径命令。默认脚本针对原仓库层级；脱离原仓库重跑原始数据时显式传入--input等参数。历史JSON中的绝对路径只作原运行溯源。

包清单：[PACKAGE_MANIFEST.json](PACKAGE_MANIFEST.json)。验收结果：[PACKAGE_VALIDATION.json](PACKAGE_VALIDATION.json)。
