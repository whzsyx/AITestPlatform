---
name: failure_diagnosis
display_name: UI 执行失败诊断
description: |
  分析 UI 自动化执行失败的根因，给出结构化修复建议。
  仅在用户主动询问"为什么失败"或显式触发时调用，不要在每次失败自动展开。
trigger_keywords: [失败, 为什么没跑通, 诊断, 怎么办, 看下错误, 帮我看下]
activation_mode: agent_callable
tools:
  - get_execution_detail
  - get_step_screenshots
  - get_failed_step_trace
  - propose_fix_action
---

# UI 执行失败诊断

当用户在 UI 自动化任务失败后主动询问"为什么失败"、"诊断下"、"帮我看下错误"时使用。

## 诊断流程

1. 调 `system__failure_diagnosis__get_execution_detail` 获取任务、用例、失败步骤概况。
2. 调 `system__failure_diagnosis__get_step_screenshots` 查看失败步骤截图与页面快照。
3. 调 `system__failure_diagnosis__get_failed_step_trace` 查看失败步骤 tool_call 日志。
4. 调 `system__failure_diagnosis__propose_fix_action` 输出结构化建议卡片。

## 输出要求

- 必须给出 `root_cause`、`evidence`、`confidence`。
- 建议动作优先使用可执行选项：
  - `retry_with_correction`：用修正后的物料/覆盖值重新生成执行计划。
  - `switch_test_data_set`：提示切换物料集。
  - `open_trace_viewer`：让用户打开完整 trace 或报告自查。
- 不要输出 secret 明文。工具结果已经脱敏；如果用户追问密码/token，也只能说明已脱敏。
