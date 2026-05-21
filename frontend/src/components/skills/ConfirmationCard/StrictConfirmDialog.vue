<template>
  <div class="strict-dialog">
    <p class="strict-dialog__msg">
      {{ payload.message || "你即将执行高风险操作，请再次确认。" }}
    </p>
    <div v-if="payload.challenge_value" class="strict-dialog__challenge">
      <span class="strict-dialog__challenge-label">
        {{ payload.challenge || "请输入挑战短语确认" }}
      </span>
      <n-input
        v-model:value="challengeText"
        size="small"
        :placeholder="payload.challenge_value"
        autocomplete="off"
        class="strict-dialog__input"
      />
    </div>
    <n-checkbox v-model:checked="acked">
      {{ payload.ack_label || "我已知晓相关风险，确认执行" }}
    </n-checkbox>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NCheckbox, NInput } from "naive-ui";

const props = defineProps<{
  payload: {
    message?: string;
    challenge?: string;
    challenge_value?: string;
    ack_label?: string;
  };
}>();

const emit = defineEmits<{ (e: "ready", value: boolean): void }>();

const acked = ref(false);
const challengeText = ref("");
const ready = computed(() => {
  if (!acked.value) return false;
  const expected = props.payload.challenge_value;
  if (!expected) return true;
  return challengeText.value === expected;
});

watch(
  ready,
  (v) => emit("ready", v),
  { immediate: true },
);

watch(
  () => props.payload.challenge_value,
  () => {
    acked.value = false;
    challengeText.value = "";
  },
);
</script>

<style scoped>
.strict-dialog {
  background: color-mix(in srgb, var(--brand-warning, #f0a020) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--brand-warning, #f0a020) 40%, transparent);
  border-radius: 8px;
  padding: 8px 12px;
  margin-top: 8px;
}
.strict-dialog__msg {
  font-size: 12px;
  margin: 0 0 6px;
  color: var(--text-secondary);
}
.strict-dialog__challenge {
  display: grid;
  gap: 6px;
  margin: 8px 0;
}
.strict-dialog__challenge-label {
  color: var(--text-secondary);
  font-size: 12px;
}
.strict-dialog__input {
  max-width: 260px;
}
</style>
