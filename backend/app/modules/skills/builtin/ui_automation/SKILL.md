---
name: system_ui_automation
display_name: 内置 · UI 自动化（对话入口停用）
version: 2.3.0
description: |
  AI 对话触发 UI 自动化入口已停用。用例执行只从"用例管理"页面的执行入口发起。
trigger_keywords: []
activation_mode: agent_callable
category: system
tools: []
---

# 内置 · UI 自动化（对话入口停用）

## 何时使用

不要在 AI 对话中使用本技能。若用户在对话里要求"跑用例 / 执行 UI 自动化"，
请提示用户前往"用例管理"页面选择用例后点击执行。

## 兼容说明

后端仍保留 `system__ui_automation__*` 工具实现和 UI 执行 API，供历史计划、
内部调试和用例管理执行链路兼容；这些工具不再暴露给 AI 对话路由。
