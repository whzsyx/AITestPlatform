<template>
  <div class="fix-action-card">
    <div class="fix-action-card__head">
      <div class="fix-action-card__title">
        <span class="i-carbon-debug text-rose-500" />
        <span>失败诊断建议</span>
      </div>
      <n-tag size="small" :bordered="false" :type="confidenceTagType">
        置信度 {{ confidencePercent }}%
      </n-tag>
    </div>

    <div class="fix-action-card__body">
      <div v-if="stepLabel" class="fix-action-card__step">
        <span class="i-carbon-location-current" />
        <span>{{ stepLabel }}</span>
      </div>

      <div class="fix-action-card__section">
        <div class="fix-action-card__label">根因</div>
        <p class="fix-action-card__text">{{ meta.diagnosis.root_cause }}</p>
      </div>

      <div v-if="evidence.length" class="fix-action-card__section">
        <div class="fix-action-card__label">证据</div>
        <ul class="fix-action-card__evidence">
          <li v-for="(item, index) in evidence" :key="index">{{ item }}</li>
        </ul>
      </div>
    </div>

    <div v-if="actions.length" class="fix-action-card__actions">
      <n-button
        v-for="action in actions"
        :key="actionKey(action)"
        size="small"
        :type="buttonType(action.action)"
        secondary
        @click="runAction(action)"
      >
        <template #icon>
          <span :class="actionIcon(action.action)" />
        </template>
        {{ action.label }}
      </n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { NButton, NTag, useMessage } from "naive-ui";
import { useProjectStore } from "@/stores/project";
import type { FixActionItem, FixActionMeta } from "@/components/skills/types";

const props = defineProps<{
  meta: FixActionMeta;
}>();

const emit = defineEmits<{
  (e: "send-message", text: string): void;
}>();

const router = useRouter();
const message = useMessage();
const projectStore = useProjectStore();

const confidencePercent = computed(() =>
  Math.round(Math.max(0, Math.min(props.meta.diagnosis.confidence || 0, 1)) * 100),
);

const confidenceTagType = computed<"success" | "warning" | "error">(() => {
  if (confidencePercent.value >= 80) return "success";
  if (confidencePercent.value >= 50) return "warning";
  return "error";
});

const evidence = computed(() =>
  Array.isArray(props.meta.diagnosis.evidence)
    ? props.meta.diagnosis.evidence.filter(Boolean).slice(0, 6)
    : [],
);

const actions = computed(() =>
  Array.isArray(props.meta.suggested_actions)
    ? props.meta.suggested_actions.slice(0, 4)
    : [],
);

const stepLabel = computed(() => {
  const step = props.meta.failed_step || {};
  const no = step.step_number ?? step.index;
  const name = step.name || step.description;
  if (no && name) return `步骤 ${no}：${name}`;
  if (no) return `步骤 ${no}`;
  return name ? String(name) : "";
});

function actionKey(action: FixActionItem): string {
  return `${action.action}:${action.label}`;
}

function actionIcon(action: string): string {
  if (action === "open_trace_viewer") return "i-carbon-document-view";
  if (action === "switch_test_data_set") return "i-carbon-data-set";
  if (action === "update_test_data") return "i-carbon-edit";
  return "i-carbon-restart";
}

function buttonType(action: string): "primary" | "default" {
  return action === "retry_with_correction" ? "primary" : "default";
}

function runAction(action: FixActionItem) {
  if (action.action === "open_trace_viewer") {
    openExecutionDetail();
    return;
  }
  emit("send-message", buildRetryPrompt(action));
}

function openExecutionDetail() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) {
    message.warning("请先选择项目后再查看执行详情");
    return;
  }
  router.push({
    name: "UIExecutionDetail",
    params: { projectId, execId: props.meta.task_id },
  });
}

function buildRetryPrompt(action: FixActionItem): string {
  const params = action.params && Object.keys(action.params).length
    ? `\n修复参数：${JSON.stringify(action.params, null, 2)}`
    : "";
  return [
    `请基于失败诊断为 UI 执行任务 ${props.meta.task_id} 重新生成修复后的执行计划。`,
    `建议动作：${action.action} - ${action.label}`,
    `根因：${props.meta.diagnosis.root_cause}`,
    params,
    "请先生成可确认的执行计划卡片，不要直接执行。",
  ].filter(Boolean).join("\n");
}
</script>

<style scoped>
.fix-action-card {
  width: min(720px, 100%);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: var(--bg-card);
  overflow: hidden;
}

.fix-action-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.fix-action-card__title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-weight: 600;
}

.fix-action-card__body {
  display: grid;
  gap: 12px;
  padding: 14px;
}

.fix-action-card__step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 13px;
}

.fix-action-card__section {
  display: grid;
  gap: 6px;
}

.fix-action-card__label {
  font-size: 12px;
  color: var(--text-tertiary);
}

.fix-action-card__text {
  margin: 0;
  line-height: 1.6;
  word-break: break-word;
}

.fix-action-card__evidence {
  margin: 0;
  padding-left: 18px;
  color: var(--text-secondary);
  line-height: 1.55;
}

.fix-action-card__evidence li + li {
  margin-top: 4px;
}

.fix-action-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 14px 14px;
}
</style>
