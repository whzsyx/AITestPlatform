<template>
  <div v-if="items.length > 0" class="assertion-list">
    <div
      v-for="(item, idx) in items"
      :key="idx"
      class="assertion-list__item"
      :class="itemModifier(item)"
    >
      <div class="assertion-list__head">
        <n-tag size="small" type="info" :bordered="false" class="assertion-list__badge">
          <template #icon>
            <span class="i-carbon-checkmark-outline" />
          </template>
          断言
        </n-tag>
        <n-tag
          v-if="hasResult(item)"
          size="small"
          :type="item.passed ? 'success' : 'error'"
          :bordered="false"
        >
          {{ item.passed ? "通过" : "失败" }}
        </n-tag>
        <span class="assertion-list__type">{{ typeLabel(item.type) }}</span>
        <code v-if="item.type === 'json_path_eq' && item.path" class="assertion-list__path">
          {{ item.path }}
        </code>
      </div>
      <div class="assertion-list__rows">
        <div class="assertion-list__row">
          <span class="assertion-list__label">期望</span>
          <code class="assertion-list__value">{{ formatValue(item.expected) }}</code>
        </div>
        <div v-if="hasResult(item)" class="assertion-list__row">
          <span class="assertion-list__label">实际</span>
          <code
            class="assertion-list__value"
            :class="{ 'assertion-list__value--miss': !item.passed }"
          >{{ formatValue(item.actual) }}</code>
        </div>
        <div
          v-if="hasResult(item) && !item.passed && item.reason"
          class="assertion-list__row assertion-list__row--reason"
        >
          <span class="assertion-list__label">原因</span>
          <span class="assertion-list__reason">{{ item.reason }}</span>
        </div>
      </div>
    </div>
  </div>
  <app-empty
    v-else
    icon="i-carbon-checkmark-outline"
    title="暂无断言"
    description="保存断言或执行后将在此展示。"
  />
</template>

<script setup lang="ts">
import { NTag } from "naive-ui";
import AppEmpty from "@/components/common/AppEmpty.vue";
import type { ApiAssertion, ApiAssertionResult, ApiAssertionType } from "@/services/apiTesting";

type AssertionItem = ApiAssertion | ApiAssertionResult;

defineProps<{
  items: AssertionItem[];
}>();

const TYPE_LABELS: Record<ApiAssertionType, string> = {
  status_code: "状态码",
  body_contains: "响应包含",
  json_path_eq: "JSON Path 等于",
};

function typeLabel(type: ApiAssertionType): string {
  return TYPE_LABELS[type] ?? type;
}

function hasResult(item: AssertionItem): item is ApiAssertionResult {
  return Object.prototype.hasOwnProperty.call(item, "passed");
}

function itemModifier(item: AssertionItem): string {
  if (!hasResult(item)) return "assertion-list__item--neutral";
  return item.passed ? "assertion-list__item--passed" : "assertion-list__item--failed";
}

function formatValue(value: unknown): string {
  if (value === undefined) return "未返回";
  if (value === null) return "null";
  if (typeof value === "string") return value === "" ? '""' : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
</script>

<style scoped>
.assertion-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.assertion-list__item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--border-color, #e5e7eb);
  border-left-width: 3px;
  border-radius: 6px;
  background: var(--card-color, #fff);
}

.assertion-list__item--passed {
  border-left-color: var(--success-color, #18a058);
}

.assertion-list__item--failed {
  border-left-color: var(--error-color, #d03050);
  background: rgba(208, 48, 80, 0.04);
}

.assertion-list__item--neutral {
  border-left-color: var(--info-color, #2080f0);
}

.assertion-list__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 13px;
}

.assertion-list__badge {
  font-weight: 600;
}

.assertion-list__type {
  color: var(--text-primary, #1f2937);
  font-weight: 500;
}

.assertion-list__path {
  padding: 0 6px;
  font-size: 12px;
  color: var(--text-secondary, #4b5563);
  background: var(--code-color, rgba(0, 0, 0, 0.04));
  border-radius: 4px;
}

.assertion-list__rows {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  line-height: 1.6;
}

.assertion-list__row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.assertion-list__row--reason {
  color: var(--error-color, #d03050);
}

.assertion-list__label {
  flex: 0 0 36px;
  color: var(--text-tertiary, #9ca3af);
}

.assertion-list__value {
  flex: 1;
  min-width: 0;
  padding: 0 6px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: var(--code-color, rgba(0, 0, 0, 0.04));
  border-radius: 4px;
  color: var(--text-primary, #1f2937);
  font-family: var(--font-family-mono, ui-monospace, SFMono-Regular, monospace);
}

.assertion-list__value--miss {
  background: rgba(208, 48, 80, 0.1);
  color: var(--error-color, #d03050);
}

.assertion-list__reason {
  flex: 1;
  word-break: break-word;
}
</style>
