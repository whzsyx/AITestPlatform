<template>
  <div class="api-module-tree">
    <n-spin :show="loading" size="small">
      <n-tree
        v-if="treeData.length > 0"
        :data="treeData"
        :selected-keys="selectedKeys"
        :node-props="nodeProps"
        :render-suffix="renderSuffix"
        block-line
        selectable
        default-expand-all
        @update:selected-keys="handleSelect"
      />
      <div v-else-if="!loading" class="api-module-tree__empty">
        <span class="i-carbon-folder-add text-2xl block mb-2 opacity-40" />
        <div class="api-module-tree__empty-text">暂无模块</div>
        <n-button size="tiny" type="primary" @click="handleAddRoot">
          <template #icon><span class="i-carbon-add" /></template>
          新建模块
        </n-button>
      </div>
    </n-spin>

    <n-dropdown
      :show="showContextMenu"
      :x="contextMenuX"
      :y="contextMenuY"
      :options="contextMenuOptions"
      placement="bottom-start"
      @select="handleContextAction"
      @clickoutside="showContextMenu = false"
    />

    <n-modal v-model:show="showNameDialog" preset="dialog" :title="nameDialogTitle">
      <n-input
        v-model:value="nameInput"
        placeholder="请输入模块名称"
        :maxlength="200"
        @keyup.enter="confirmNameDialog"
      />
      <template #action>
        <n-button @click="showNameDialog = false">取消</n-button>
        <n-button type="primary" :disabled="!nameInput.trim()" @click="confirmNameDialog">
          确定
        </n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, ref, watch } from "vue";
import {
  NButton,
  NDropdown,
  NInput,
  NModal,
  NSpin,
  NTooltip,
  NTree,
  useDialog,
  useMessage,
} from "naive-ui";
import type { TreeOption } from "naive-ui";
import {
  createApiTestModuleApi,
  deleteApiTestModuleApi,
  getApiTestModuleTreeApi,
  updateApiTestModuleApi,
} from "@/services/apiTesting";
import type { ApiTestModuleTreeNode } from "@/services/apiTesting";
import { useProjectStore } from "@/stores/project";

const props = defineProps<{
  showCaseCount?: boolean;
}>();

const emit = defineEmits<{
  (e: "select", moduleId: string | null): void;
}>();

const message = useMessage();
const dialog = useDialog();
const projectStore = useProjectStore();

const loading = ref(false);
const modules = ref<ApiTestModuleTreeNode[]>([]);
const selectedModuleId = ref<string | null>(null);

const selectedKeys = computed(() => (selectedModuleId.value ? [selectedModuleId.value] : []));

function buildTreeData(nodes: ApiTestModuleTreeNode[]): TreeOption[] {
  return nodes.map((node) => ({
    key: node.id,
    label: props.showCaseCount === false ? node.name : `${node.name}（${node.case_count}）`,
    rawCount: node.case_count,
    children: node.children.length > 0 ? buildTreeData(node.children) : undefined,
  }));
}

const treeData = computed(() => buildTreeData(modules.value));

function renderSuffix({ option }: { option: TreeOption }) {
  return h("div", { class: "api-module-tree__suffix" }, [
    h(
      NTooltip,
      { placement: "top" },
      {
        trigger: () =>
          h(
            NButton,
            {
              size: "tiny",
              quaternary: true,
              circle: true,
              onClick: (event: MouseEvent) => {
                event.stopPropagation();
                contextMenuNodeId.value = option.key as string;
                openAddChildDialog();
              },
            },
            { icon: () => h("span", { class: "i-carbon-add-alt" }) },
          ),
        default: () => "新建子模块",
      },
    ),
    h(
      NTooltip,
      { placement: "top" },
      {
        trigger: () =>
          h(
            NButton,
            {
              size: "tiny",
              quaternary: true,
              circle: true,
              onClick: (event: MouseEvent) => {
                event.stopPropagation();
                contextMenuNodeId.value = option.key as string;
                openRenameDialog(String(option.label).split("（")[0]);
              },
            },
            { icon: () => h("span", { class: "i-carbon-edit" }) },
          ),
        default: () => "重命名",
      },
    ),
    h(
      NTooltip,
      { placement: "top" },
      {
        trigger: () =>
          h(
            NButton,
            {
              size: "tiny",
              quaternary: true,
              circle: true,
              type: "error",
              onClick: (event: MouseEvent) => {
                event.stopPropagation();
                confirmDeleteModule(option.key as string, String(option.label).split("（")[0]);
              },
            },
            { icon: () => h("span", { class: "i-carbon-trash-can" }) },
          ),
        default: () => "删除",
      },
    ),
  ]);
}

function nodeProps({ option }: { option: TreeOption }) {
  return {
    onContextmenu(event: MouseEvent) {
      event.preventDefault();
      contextMenuNodeId.value = option.key as string;
      contextMenuX.value = event.clientX;
      contextMenuY.value = event.clientY;
      showContextMenu.value = true;
    },
  };
}

const showContextMenu = ref(false);
const contextMenuX = ref(0);
const contextMenuY = ref(0);
const contextMenuNodeId = ref<string | null>(null);
const contextMenuOptions = [
  { label: "新建子模块", key: "add-child" },
  { label: "重命名", key: "rename" },
  { type: "divider", key: "d1" },
  { label: "删除", key: "delete" },
];

function handleContextAction(key: string) {
  showContextMenu.value = false;
  if (key === "add-child") {
    openAddChildDialog();
  } else if (key === "rename") {
    const node = findNode(modules.value, contextMenuNodeId.value!);
    openRenameDialog(node?.name ?? "");
  } else if (key === "delete") {
    const node = findNode(modules.value, contextMenuNodeId.value!);
    confirmDeleteModule(contextMenuNodeId.value!, node?.name ?? "");
  }
}

const showNameDialog = ref(false);
const nameInput = ref("");
const nameDialogMode = ref<"add-root" | "add-child" | "rename">("add-root");

const nameDialogTitle = computed(() => {
  if (nameDialogMode.value === "rename") return "重命名模块";
  if (nameDialogMode.value === "add-child") return "新建子模块";
  return "新建顶级模块";
});

function handleAddRoot() {
  nameDialogMode.value = "add-root";
  nameInput.value = "";
  showNameDialog.value = true;
}

function openAddChildDialog() {
  nameDialogMode.value = "add-child";
  nameInput.value = "";
  showNameDialog.value = true;
}

function openRenameDialog(currentName: string) {
  nameDialogMode.value = "rename";
  nameInput.value = currentName;
  showNameDialog.value = true;
}

function confirmDeleteModule(id: string, name: string) {
  dialog.warning({
    title: "确认删除",
    content: `确定删除模块「${name}」及其所有子模块和接口测试？此操作不可恢复。`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: () => handleDelete(id),
  });
}

async function confirmNameDialog() {
  const name = nameInput.value.trim();
  if (!name) return;
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  try {
    if (nameDialogMode.value === "add-root") {
      await createApiTestModuleApi(projectId, { name });
      message.success("模块创建成功");
    } else if (nameDialogMode.value === "add-child") {
      await createApiTestModuleApi(projectId, { name, parent_id: contextMenuNodeId.value });
      message.success("子模块创建成功");
    } else {
      await updateApiTestModuleApi(contextMenuNodeId.value!, { name });
      message.success("重命名成功");
    }
    showNameDialog.value = false;
    await fetchModules();
  } catch {
    message.error("操作失败");
  }
}

async function handleDelete(moduleId: string) {
  try {
    await deleteApiTestModuleApi(moduleId);
    message.success("模块已删除");
    if (selectedModuleId.value === moduleId) {
      selectedModuleId.value = null;
      emit("select", null);
    }
    await fetchModules();
  } catch {
    message.error("删除失败");
  }
}

function handleSelect(keys: Array<string | number>) {
  if (keys.length === 0) {
    selectedModuleId.value = null;
    emit("select", null);
  } else {
    selectedModuleId.value = keys[0] as string;
    emit("select", keys[0] as string);
  }
}

function clearSelection() {
  selectedModuleId.value = null;
  emit("select", null);
}

async function fetchModules() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) {
    modules.value = [];
    return;
  }
  loading.value = true;
  try {
    const res = await getApiTestModuleTreeApi(projectId);
    if (res.success) modules.value = res.data;
  } catch {
    message.error("获取模块树失败");
  } finally {
    loading.value = false;
  }
}

function findNode(nodes: ApiTestModuleTreeNode[], id: string): ApiTestModuleTreeNode | null {
  for (const node of nodes) {
    if (node.id === id) return node;
    const found = findNode(node.children, id);
    if (found) return found;
  }
  return null;
}

watch(() => projectStore.currentProjectId, fetchModules, { immediate: true });

defineExpose({
  fetchModules,
  clearSelection,
  openAddRootDialog: handleAddRoot,
});
</script>

<style scoped>
.api-module-tree {
  min-height: 200px;
}

.api-module-tree__empty {
  text-align: center;
  padding: 40px 12px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.api-module-tree__empty-text {
  margin-bottom: 8px;
}

.api-module-tree :deep(.api-module-tree__suffix) {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: 4px;
}

.api-module-tree :deep(.api-module-tree__suffix > .n-tooltip) {
  display: none;
}

.api-module-tree :deep(.n-tree-node:hover .api-module-tree__suffix > .n-tooltip) {
  display: inline-flex;
}
</style>
