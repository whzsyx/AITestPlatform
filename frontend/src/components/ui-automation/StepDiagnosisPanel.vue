<!--
  Phase 15.10 — 步骤诊断面板：execution_path / assertion_method /
  loop_break_reason / match_strategy 四个徽章 + 失败步骤的 locator attempts
  折叠展示。

  设计取舍：
  - 抽组件而不是直接铺到 ExecutionDetail.vue，因为后者已 1700+ 行，再塞徽章
    + attempts 解析逻辑会让该文件无可读性可言。
  - 严格 v-if 守卫每个字段：旧记录 4 个字段全为 null 时不渲染任何徽章和折叠
    区，避免给用户视觉负担（plan 验收标准明文要求）。
  - 不新增 charting 库 / 不引入额外 NaiveUI 组件之外的 UI 库。
  - match_strategy 字段来源于 deterministic_runner 落库的 evidence
    （15.6 落地）：从 step.tool_calls 里找 ``raw_name=deterministic_runner``
    的记录, 取 result.details.match_strategy。
-->

<template>
  <div v-if="hasAnyDiagnostic" class="step-diagnosis">
    <div v-if="badges.length > 0" class="step-diagnosis__badges">
      <n-tooltip
        v-for="badge in badges"
        :key="badge.key"
        :show-arrow="false"
        :delay="200"
      >
        <template #trigger>
          <n-tag
            :type="badge.type"
            size="tiny"
            :bordered="false"
            class="step-diagnosis__badge"
          >
            <template #icon>
              <span :class="badge.icon" />
            </template>
            {{ badge.label }}
          </n-tag>
        </template>
        {{ badge.tooltip }}
      </n-tooltip>
    </div>

    <details v-if="locatorAttempts.length > 0" class="step-diagnosis__attempts">
      <summary>
        <span class="i-carbon-search-locate" />
        Locator 候选明细（{{ locatorAttempts.length }} 次）
      </summary>
      <div class="step-diagnosis__attempts-body">
        <div
          v-for="(attempt, idx) in locatorAttempts"
          :key="idx"
          class="step-diagnosis__attempt-row"
        >
          <span class="step-diagnosis__attempt-rank">#{{ idx + 1 }}</span>
          <n-tag
            :type="attempt.passed ? 'success' : 'error'"
            size="tiny"
            :bordered="false"
            class="step-diagnosis__attempt-strategy"
          >
            {{ attempt.strategy }}
          </n-tag>
          <span
            v-if="attempt.count !== null"
            class="step-diagnosis__attempt-count"
            :class="attemptCountClass(attempt.count)"
            :title="attemptCountHint(attempt.count)"
          >
            {{ attempt.count }} 命中
          </span>
          <span v-if="attempt.selector" class="step-diagnosis__attempt-selector">
            {{ attempt.selector }}
          </span>
          <span v-if="attempt.error" class="step-diagnosis__attempt-error">
            {{ attempt.error }}
          </span>
        </div>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { NTag, NTooltip } from "naive-ui";
import type { ExecutionStepResponse } from "@/services/uiAutomation";

interface Badge {
  key: string;
  label: string;
  type: "default" | "info" | "success" | "warning" | "error";
  icon: string;
  tooltip: string;
}

interface LocatorAttempt {
  strategy: string;
  selector: string | null;
  count: number | null;
  passed: boolean;
  error: string | null;
}

const props = defineProps<{
  step: ExecutionStepResponse;
}>();

// ── 徽章 ────────────────────────────────────────────────────────────
// 与 plan 15.10 一致：
// - assertion_method：deterministic=绿 / rule=蓝 / llm=紫 / triage_external=橙
// - loop_break_reason：仅 ai_step_runner 路径有值；命中即显示
// - match_strategy：从 deterministic_runner 的 evidence 取，仅 assert_text
//   用得上；exact / contains / loose 三色
// execution_path 已经在 ExecutionDetail.vue 主头里渲染过了，本组件不再重复，
// 避免一行徽章爆裂。

const ASSERTION_METHOD_META: Record<string, Omit<Badge, "key">> = {
  deterministic: {
    label: "断言：规则",
    type: "success",
    icon: "i-carbon-checkmark-filled",
    tooltip: "deterministic_runner 直接判定，无 LLM 介入。",
  },
  rule: {
    label: "断言：规则",
    type: "info",
    icon: "i-carbon-rule",
    tooltip: "AssertionJudge 规则路径，零 token。",
  },
  llm: {
    label: "断言：LLM",
    type: "warning",
    icon: "i-carbon-machine-learning-model",
    tooltip: "AssertionJudge 调 LLM 做语义判定，会消耗 token。",
  },
  triage_external: {
    label: "外部阻断",
    type: "error",
    icon: "i-carbon-warning-alt-filled",
    tooltip: "命中外部安全验证 / 验证码，failure_triage 短路。",
  },
  skipped: {
    label: "断言：跳过",
    type: "default",
    icon: "i-carbon-pause",
    tooltip: "本步骤未触发断言（被跳过 / 早停 / 无 expected）。",
  },
};

const LOOP_BREAK_REASON_LABEL: Record<string, string> = {
  normal: "正常完成",
  max_iter: "达到最大轮数",
  budget_exceeded: "Token 预算耗尽",
  duplicate_tool: "工具调用重复",
  snapshot_unchanged: "快照无变化",
  reasoning_drift: "推理漂移",
  fallback_budget_exceeded: "Fallback 预算超限",
};

function loopBreakReasonBadge(reason: string): Badge {
  const label = LOOP_BREAK_REASON_LABEL[reason] || reason;
  const isAbnormal = reason && reason !== "normal";
  return {
    key: "loop_break_reason",
    label: `循环退出：${label}`,
    type: isAbnormal ? "warning" : "default",
    icon: isAbnormal ? "i-carbon-warning" : "i-carbon-checkmark",
    tooltip:
      "StepRunner 退出循环的原因；非 normal 通常意味着触发了 Phase 15.7 的早停信号。",
  };
}

const MATCH_STRATEGY_META: Record<string, Omit<Badge, "key">> = {
  exact: {
    label: "匹配：精确",
    type: "success",
    icon: "i-carbon-equals",
    tooltip: "expected_result 精确匹配页面文本。",
  },
  contains: {
    label: "匹配：包含",
    type: "info",
    icon: "i-carbon-search",
    tooltip: "页面文本包含 expected_result 子串。",
  },
  loose: {
    label: "匹配：宽松",
    type: "warning",
    icon: "i-carbon-search-locate",
    tooltip: "去标点 / 折叠空白后再做 contains 匹配（15.6 三级降级最低档）。",
  },
};

const matchStrategy = computed<string | null>(() => {
  // Phase 15.6 把 match_strategy 落到 evidence.details.match_strategy；
  // 老记录里没有 -> null。assert_text 之外的 step 也没值。
  const calls = (props.step.tool_calls ?? []) as Array<Record<string, unknown>>;
  for (const c of calls) {
    const rn = String(c.raw_name ?? c.name ?? "");
    if (rn !== "deterministic_runner") continue;
    const result = (c.result as Record<string, unknown>) ?? {};
    const details = (result.details as Record<string, unknown>) ?? {};
    const strategy = details.match_strategy;
    if (typeof strategy === "string" && strategy.length > 0) return strategy;
  }
  return null;
});

const badges = computed<Badge[]>(() => {
  const list: Badge[] = [];

  if (props.step.assertion_method) {
    const meta = ASSERTION_METHOD_META[props.step.assertion_method];
    if (meta) {
      list.push({ key: "assertion_method", ...meta });
    } else {
      // 后端可能加新枚举，前端落后一版时不要崩，给个默认徽章。
      list.push({
        key: "assertion_method",
        label: `断言：${props.step.assertion_method}`,
        type: "default",
        icon: "i-carbon-rule",
        tooltip: "未识别的断言方式，请检查后端枚举。",
      });
    }
  }

  if (props.step.loop_break_reason) {
    list.push(loopBreakReasonBadge(props.step.loop_break_reason));
  }

  if (matchStrategy.value) {
    const meta = MATCH_STRATEGY_META[matchStrategy.value];
    if (meta) {
      list.push({ key: "match_strategy", ...meta });
    } else {
      list.push({
        key: "match_strategy",
        label: `匹配：${matchStrategy.value}`,
        type: "default",
        icon: "i-carbon-search",
        tooltip: "未识别的匹配策略。",
      });
    }
  }

  return list;
});

// ── locator attempts 折叠 ─────────────────────────────────────────
// 来源：step.tool_calls 里 ``deterministic_runner`` 记录的
// ``result.details.attempts``。15.6 后即使部分尝试失败也会全量落 evidence，
// 这里展平成行表，让用户一眼分辨"locator 是因为 0 命中还是 5 命中"。

const locatorAttempts = computed<LocatorAttempt[]>(() => {
  const calls = (props.step.tool_calls ?? []) as Array<Record<string, unknown>>;
  const out: LocatorAttempt[] = [];
  for (const c of calls) {
    const rn = String(c.raw_name ?? c.name ?? "");
    if (rn !== "deterministic_runner") continue;
    const result = (c.result as Record<string, unknown>) ?? {};
    const details = (result.details as Record<string, unknown>) ?? {};
    const arr = details.attempts;
    if (!Array.isArray(arr)) continue;
    for (const item of arr) {
      if (!item || typeof item !== "object") continue;
      const obj = item as Record<string, unknown>;
      const strategy = String(obj.strategy ?? obj.kind ?? "unknown");
      const selector =
        typeof obj.selector === "string" ? (obj.selector as string) : null;
      const count =
        typeof obj.count === "number" ? (obj.count as number) : null;
      const passedRaw = obj.passed ?? obj.matched ?? obj.success;
      const passed = passedRaw === true || count === 1;
      const errorRaw = obj.error ?? obj.error_kind ?? obj.message ?? null;
      const error = typeof errorRaw === "string" ? errorRaw : null;
      out.push({ strategy, selector, count, passed, error });
    }
  }
  return out;
});

const hasAnyDiagnostic = computed(
  () => badges.value.length > 0 || locatorAttempts.value.length > 0,
);

function attemptCountClass(count: number): string {
  if (count === 1) return "step-diagnosis__attempt-count--ok";
  if (count === 0) return "step-diagnosis__attempt-count--zero";
  return "step-diagnosis__attempt-count--many";
}

function attemptCountHint(count: number): string {
  if (count === 1) return "唯一命中（strict 通过）";
  if (count === 0) return "未命中：locator 找不到任何元素";
  return `多命中（${count} 个）：strict 失败，需要更具体的候选`;
}
</script>

<style scoped>
.step-diagnosis {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.step-diagnosis__badges {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
}
.step-diagnosis__badge {
  font-variant-numeric: tabular-nums;
}
.step-diagnosis__attempts {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 6px 10px;
  background: var(--bg-secondary, rgba(128, 128, 128, 0.04));
}
.step-diagnosis__attempts > summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.step-diagnosis__attempts[open] > summary {
  margin-bottom: 6px;
}
.step-diagnosis__attempts-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.step-diagnosis__attempt-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  flex-wrap: wrap;
}
.step-diagnosis__attempt-rank {
  font-size: 11px;
  color: var(--text-tertiary);
  width: 24px;
  font-variant-numeric: tabular-nums;
}
.step-diagnosis__attempt-strategy {
  flex-shrink: 0;
}
.step-diagnosis__attempt-count {
  font-variant-numeric: tabular-nums;
}
.step-diagnosis__attempt-count--ok {
  color: #18a058;
}
.step-diagnosis__attempt-count--zero {
  color: #d03050;
}
.step-diagnosis__attempt-count--many {
  color: #f0a020;
}
.step-diagnosis__attempt-selector {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  color: var(--text-primary);
  background: var(--bg-card);
  padding: 1px 4px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}
.step-diagnosis__attempt-error {
  color: #d03050;
  font-size: 11px;
}
</style>
