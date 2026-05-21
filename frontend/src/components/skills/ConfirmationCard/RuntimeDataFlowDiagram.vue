<template>
  <section class="cc-section">
    <header class="cc-section__head">
      <span class="i-carbon-flow-data text-cyan-500" />
      <span>运行时数据流（{{ edges.length }}）</span>
    </header>

    <ul class="runtime-flow">
      <li v-for="edge in edges" :key="`${edge.from_case_id}-${edge.to_case_id}`" class="runtime-flow__edge">
        <span class="runtime-flow__case">{{ caseTitle(edge.from_case_id) }}</span>
        <span class="i-carbon-arrow-right runtime-flow__arrow" />
        <span class="runtime-flow__case">{{ caseTitle(edge.to_case_id) }}</span>
        <span class="runtime-flow__keys">
          <n-tag
            v-for="key in edge.runtime_keys"
            :key="key"
            size="tiny"
            :bordered="false"
            type="info"
          >
            {{ key }}
          </n-tag>
        </span>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { NTag } from "naive-ui";
import type { CaseSummary, RuntimeDataEdge } from "../types";

const props = defineProps<{
  edges: RuntimeDataEdge[];
  cases: CaseSummary[];
}>();

const casesById = computed(() => new Map(props.cases.map((item) => [item.id, item])));

function caseTitle(id: string) {
  const item = casesById.value.get(id);
  if (!item) return id.slice(0, 8);
  return `TC-${String(item.case_no).padStart(4, "0")} ${item.title}`;
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
.runtime-flow {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.runtime-flow__edge {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.runtime-flow__case {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
}
.runtime-flow__arrow {
  color: var(--text-tertiary);
  justify-self: center;
}
.runtime-flow__keys {
  display: inline-flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px;
  min-width: 0;
}
@media (max-width: 720px) {
  .runtime-flow__edge {
    grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr);
  }
  .runtime-flow__keys {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}
</style>
