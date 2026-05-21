<template>
  <section class="cc-section">
    <header class="cc-section__head">
      <span class="i-carbon-edit text-amber-500" />
      <span>即席步骤（{{ draft.steps.length }}）</span>
      <n-tag size="tiny" :bordered="false" :type="confidenceType">
        置信度 {{ Math.round(draft.draft_confidence * 100) }}%
      </n-tag>
    </header>

    <div class="adhoc-head">
      <n-input
        :value="draft.title"
        size="small"
        placeholder="标题"
        @update:value="updateRoot('title', $event)"
      />
      <n-input
        :value="draft.target_url || ''"
        size="small"
        placeholder="入口 URL（可选）"
        @update:value="updateRoot('target_url', $event || null)"
      />
    </div>

    <div class="adhoc-steps">
      <div
        v-for="(step, idx) in draft.steps"
        :key="idx"
        class="adhoc-step"
      >
        <span class="adhoc-step__no">{{ idx + 1 }}</span>
        <div class="adhoc-step__fields">
          <n-input
            :value="step.action"
            size="small"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 3 }"
            placeholder="操作"
            @update:value="updateStep(idx, 'action', $event)"
          />
          <n-input
            :value="step.expected_result || ''"
            size="small"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 3 }"
            placeholder="预期结果"
            @update:value="updateStep(idx, 'expected_result', $event || null)"
          />
        </div>
        <div class="adhoc-step__actions">
          <n-button quaternary circle size="tiny" :disabled="idx === 0" @click="moveStep(idx, -1)">
            <template #icon><span class="i-carbon-arrow-up" /></template>
          </n-button>
          <n-button
            quaternary
            circle
            size="tiny"
            :disabled="idx === draft.steps.length - 1"
            @click="moveStep(idx, 1)"
          >
            <template #icon><span class="i-carbon-arrow-down" /></template>
          </n-button>
          <n-button
            quaternary
            circle
            size="tiny"
            type="error"
            :disabled="draft.steps.length <= 1"
            @click="removeStep(idx)"
          >
            <template #icon><span class="i-carbon-trash-can" /></template>
          </n-button>
        </div>
      </div>
    </div>

    <n-button size="tiny" quaternary @click="addStep">
      <template #icon><span class="i-carbon-add" /></template>
      添加步骤
    </n-button>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { NButton, NInput, NTag } from "naive-ui";
import type { AdhocCaseDraft, AdhocStepDraft } from "../types";

const props = defineProps<{ modelValue: AdhocCaseDraft }>();
const emit = defineEmits<{
  (e: "update:modelValue", value: AdhocCaseDraft): void;
}>();

const draft = computed(() => props.modelValue);
const confidenceType = computed<"success" | "warning" | "error">(() => {
  if (draft.value.draft_confidence >= 0.75) return "success";
  if (draft.value.draft_confidence >= 0.6) return "warning";
  return "error";
});

function renumber(steps: AdhocStepDraft[]) {
  return steps.map((s, i) => ({ ...s, step_number: i + 1 }));
}

function commit(update: Partial<AdhocCaseDraft>) {
  emit("update:modelValue", {
    ...draft.value,
    ...update,
    steps: renumber(update.steps ?? draft.value.steps),
  });
}

function updateRoot<K extends keyof AdhocCaseDraft>(key: K, value: AdhocCaseDraft[K]) {
  commit({ [key]: value } as Partial<AdhocCaseDraft>);
}

function updateStep(index: number, key: keyof AdhocStepDraft, value: string | number | null) {
  const steps = draft.value.steps.map((s, i) =>
    i === index ? { ...s, [key]: value } : s,
  );
  commit({ steps });
}

function addStep() {
  const steps = [
    ...draft.value.steps,
    {
      step_number: draft.value.steps.length + 1,
      action: "",
      expected_result: "操作完成且页面无错误提示",
    },
  ];
  commit({ steps });
}

function removeStep(index: number) {
  if (draft.value.steps.length <= 1) return;
  commit({ steps: draft.value.steps.filter((_, i) => i !== index) });
}

function moveStep(index: number, delta: -1 | 1) {
  const target = index + delta;
  if (target < 0 || target >= draft.value.steps.length) return;
  const steps = [...draft.value.steps];
  [steps[index], steps[target]] = [steps[target], steps[index]];
  commit({ steps });
}
</script>

<style scoped>
.cc-section {
  padding: 8px 0;
  border-bottom: 1px dashed var(--border-subtle);
}
.cc-section__head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.adhoc-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(160px, 0.7fr);
  gap: 8px;
  margin-bottom: 8px;
}
.adhoc-steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 6px;
}
.adhoc-step {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
}
.adhoc-step__no {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--bg-page-soft);
  color: var(--text-tertiary);
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.adhoc-step__fields {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: 6px;
}
.adhoc-step__actions {
  display: inline-flex;
  gap: 2px;
}
@media (max-width: 720px) {
  .adhoc-head,
  .adhoc-step__fields {
    grid-template-columns: 1fr;
  }
  .adhoc-step {
    grid-template-columns: 24px minmax(0, 1fr);
  }
  .adhoc-step__actions {
    grid-column: 2;
  }
}
</style>
