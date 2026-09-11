# I/O Guard 输入、输出与工具端模型优化报告（2026-08-13，2026-08-14 更新）

## 结论

本轮不是只改规则或抬高阈值，而是重新审计标签、重建阶段化数据集、训练并选择新的模型参数。最终生产候选为三个独立的字符 n-gram TF-IDF + Logistic Regression 二分类头，分别用于用户输入、模型输出和外部/工具内容。工具结果先解析为字符串叶节点，再逐字段分类，避免把 JSON 键名和结构误学成攻击。

旧的 `io-guard-bge-classifier-v2-zh` 保持非生产状态。它在内部七分类测试上准确率约 80.33%、宏 F1 约 83.31%，但在真实中文正常内容上产生灾难性过检，且越狱类召回仅约 43.99%。

## 数据与防泄漏

最终数据集包含 16,795 条，使用稳定语义组划分：训练 10,885、验证 1,878、测试 4,032。同一学术样本的输入、输出、拒答和工具变体始终进入同一 split；InjecAgent 进一步按攻击指令分组，防止相同攻击句跨训练与测试。2026-08-14 增加了网页实测中发现的中文“取消安全限制/作废任务”攻击变体，以及 `[OTP]`、`[API_KEY]`、`[PHONE]`、`[EMAIL]` 脱敏占位符正常输出。

覆盖范围：

- 输入：AlignBench、SafetyBench 中文安全讨论、Chinese Do-Not-Answer、Safety-Prompts、deepset prompt injection、JailbreakBench、PurpleLlama 与项目错误挖掘样本。
- 输出：AlignBench 参考答案、安全拒答、危险直接回答和凭证泄露输出。
- 检索/工具：BIPIA、InjecAgent、PurpleLlama 间接注入、正常网页证据、邮件、搜索结果、日历、评论、简介和项目工具样本。

关键标签修复：Chinese Do-Not-Answer 中的事实核验、社会议题、普通安全咨询和拟人化问答不再一律标为 IO Guard 风险；只保留非法/不安全行动协助以及未经授权的隐私/机密索取为正类。

## 模型与超参数搜索

比较了以下候选：

1. 旧 Transformer v2 七分类头；
2. BGE 向量 + 七分类 Logistic Regression 阶段头；
3. BGE 向量 + 二分类 Logistic Regression 阶段头；
4. 字符 2–5 / 2–6 gram TF-IDF + Logistic Regression，搜索 `C={0.3,1,3,10}` 与 `class_weight={None,balanced}`。

字符模型更能保留中文局部指令词、混合语言注入和工具字段内的短命令，最终胜出。完整候选参数与验证/测试结果在 `training_metadata.json`。

## 最终生产阈值与独立测试

| 端 | 阈值 | Precision | Recall | F1 | FPR |
|---|---:|---:|---:|---:|---:|
| 输入 | 0.6825 | 95.10% | 87.07% | 90.91% | 2.21% |
| 输出 | 0.30 | 100.00% | 100.00% | 100.00% | 0.00% |
| 检索内容 | 0.70 | 100.00% | 99.40% | 99.70% | 0.00% |
| 工具结果 | 0.70 | 100.00% | 96.12% | 98.02% | 0.00% |

在自动选择阈值 0.65 下，字符串叶节点测试集：检索召回 100%、FPR 0%；工具召回 100%、FPR 2.53%。生产使用更稳健的 0.70，整体 content 召回 98.14%、FPR 0%。运行时对一个工具结果的每个字符串字段取最大风险分，因此不会再因 `emails`、`profile`、`repository` 等 JSON 结构本身误报。

## 剩余边界

- 输入头尚未达到 1% FPR 与 85% recall 同时成立。若将阈值调至 0.80，测试 FPR 约 1.03%，但 recall 降至约 79.87%。当前选择 0.6825，结合确定性提示词注入、短指令和输出泄露规则使用。
- 训练语料以中文和英文为主，多语种混合注入仍需继续补充。
- 工具逐字段解析支持 JSON 和 Python 字典字符串；无法解析的纯文本仍作为一个字段检查。
- 模型头约 2.5 MB，可提交仓库；训练数据需按各数据源许可单独获取，不在仓库分发。

## 2026-08-20：中文短句校准

网页实测发现输入分类头在极短中文上的两个相反问题：“我的电话号码是多少”
和“请告诉我我的邮箱”可能被高置信误判，而“制造炸弹”“炸弹怎么做”及
“自制爆炸物”等短句可能没有超过模型阈值。由于统一调整输入阈值会在误报率
和危险召回率之间产生直接冲突，本次保留生产阈值 `0.6825`，在语义检测器内
增加窄范围短句校准：

- 明确查询本人电话、邮箱和联系方式的完整短句优先作为正常意图；
- 同时出现危险对象和制作动作的输入以 `0.99` 风险分兜底；
- 明确联系方式泄露、窃取或绕过权限的短句同样以 `0.99` 风险分兜底；
- “不要制造炸弹”“如何识别可疑爆炸物”“炸弹的危害是什么”等否定、
  防范、识别和安全教育语境保持放行。

上述正负样本已加入阶段数据集构建脚本，供下一次模型重训使用。运行时回归
同时覆盖自定义分类器漏报、当前 `io-guard-stage-char-v3` 真实模型以及
`/v1/input/check` API。

## 复现

```powershell
python evaluation/scripts/build_io_guard_stage_dataset.py `
  --v2-data-root <v2-data> `
  --academic-data-root <academic-data> `
  --output-root <stage-v3-data>

python evaluation/scripts/train_io_guard_char_heads.py `
  --dataset-root <stage-v3-data> `
  --output-dir <stage-v3-model> `
  --max-fpr 0.01 `
  --min-recall 0.85 `
  --production-ready `
  --production-threshold input=0.6825 `
  --production-threshold output=0.30 `
  --production-threshold content=0.70
```

训练数据统计及 SHA-256 位于 `evaluation/reports/io_guard_stage_v3_dataset_stats.json`，训练参数与全部错误样本索引位于模型目录的 `training_metadata.json`。
