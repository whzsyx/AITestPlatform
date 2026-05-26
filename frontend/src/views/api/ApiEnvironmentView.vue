<template>
  <div class="api-env-page">
    <page-header title="环境配置" subtitle="维护 API 管理中可复用的环境基础 URL" icon="i-carbon-cloud-service-management" />

    <n-alert v-if="!projectStore.currentProjectId" type="warning" class="mb-4">
      请先在顶栏选择一个项目，再配置 API 环境。
    </n-alert>

    <template v-else>
      <div class="api-env-toolbar">
        <n-input
          v-model:value="searchText"
          placeholder="搜索环境名称或 URL"
          clearable
          class="api-env-toolbar__search"
        >
          <template #prefix><span class="i-carbon-search text-gray-400" /></template>
        </n-input>
        <n-button type="primary" @click="openCreateDrawer">
          <template #icon><span class="i-carbon-add" /></template>
          新建环境
        </n-button>
      </div>

      <n-spin :show="loading">
        <n-data-table
          v-if="filteredItems.length > 0 || loading"
          :columns="columns"
          :data="filteredItems"
          :row-key="(row: ApiTestEnvironment) => row.id"
          :bordered="false"
          :scroll-x="920"
          striped
        />
        <app-empty
          v-else
          icon="i-carbon-cloud-service-management"
          title="暂无 API 环境"
          description="新建环境后，API 列表中可以直接选择对应基础 URL。"
          class="mt-12"
        >
          <template #actions>
            <n-button type="primary" @click="openCreateDrawer">新建环境</n-button>
          </template>
        </app-empty>
      </n-spin>
    </template>

    <n-drawer v-model:show="showEditor" :width="560" placement="right">
      <n-drawer-content :title="editingId ? '编辑环境' : '新建环境'" closable>
        <n-form label-placement="top">
          <n-form-item label="环境名称" required>
            <n-input v-model:value="form.name" placeholder="例如：测试环境" :maxlength="200" />
          </n-form-item>
          <n-form-item label="环境 URL" required>
            <n-input v-model:value="form.base_url" placeholder="https://api.example.com" />
          </n-form-item>
          <n-form-item label="描述">
            <n-input
              v-model:value="form.description"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 6 }"
              placeholder="可选，说明环境用途"
            />
          </n-form-item>
        </n-form>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showEditor = false">取消</n-button>
            <n-button type="primary" :loading="saving" @click="saveEnvironment">保存</n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>

    <n-modal v-model:show="showVariableModal" preset="card" class="api-env-variable-modal">
      <template #header>
        <div class="api-env-variable-modal__header">
          <span>环境变量</span>
          <n-text v-if="variableEnvironment" depth="3">
            {{ variableEnvironment.name }} · {{ variableEnvironment.base_url }}
          </n-text>
        </div>
      </template>
      <div class="api-env-variable-toolbar">
        <n-input
          v-model:value="variableSearchText"
          placeholder="搜索变量 Key 或 Value"
          clearable
          class="api-env-toolbar__search"
        >
          <template #prefix><span class="i-carbon-search text-gray-400" /></template>
        </n-input>
        <n-button type="primary" @click="openCreateVariableDrawer">
          <template #icon><span class="i-carbon-add" /></template>
          新建变量
        </n-button>
      </div>
      <n-spin :show="variableLoading">
        <n-data-table
          v-if="filteredVariables.length > 0 || variableLoading"
          :columns="variableColumns"
          :data="filteredVariables"
          :row-key="(row: ApiTestEnvironmentVariable) => row.id"
          :bordered="false"
          :scroll-x="760"
          striped
        />
        <app-empty
          v-else
          icon="i-carbon-parameter"
          title="暂无环境变量"
          description="变量保存后，可在 API 列表中通过 {{变量名}} 引用。"
          class="mt-8"
        >
          <template #actions>
            <n-button type="primary" @click="openCreateVariableDrawer">新建变量</n-button>
          </template>
        </app-empty>
      </n-spin>
    </n-modal>

    <n-drawer v-model:show="showVariableEditor" :width="520" placement="right">
      <n-drawer-content :title="editingVariableId ? '编辑变量' : '新建变量'" closable>
        <n-form label-placement="top">
          <n-form-item label="变量 Key" required>
            <n-input v-model:value="variableForm.key" placeholder="例如 token、mid、tenant_id" :maxlength="100" />
          </n-form-item>
          <n-form-item label="变量 Value" required>
            <n-input
              v-model:value="variableForm.value"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 8 }"
              placeholder="变量值"
            />
          </n-form-item>
          <n-form-item label="描述">
            <n-input
              v-model:value="variableForm.description"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 5 }"
              placeholder="可选，说明变量用途"
            />
          </n-form-item>
        </n-form>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showVariableEditor = false">取消</n-button>
            <n-button type="primary" :loading="variableSaving" @click="saveVariable">保存</n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from "vue";
import {
  NAlert,
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NPopconfirm,
  NSpace,
  NSpin,
  NText,
  useMessage,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import PageHeader from "@/components/common/PageHeader.vue";
import AppEmpty from "@/components/common/AppEmpty.vue";
import {
  createApiTestEnvironmentApi,
  deleteApiTestEnvironmentApi,
  createApiTestEnvironmentVariableApi,
  deleteApiTestEnvironmentVariableApi,
  listApiTestEnvironmentsApi,
  listApiTestEnvironmentVariablesApi,
  updateApiTestEnvironmentApi,
  updateApiTestEnvironmentVariableApi,
} from "@/services/apiTesting";
import type { ApiTestEnvironment, ApiTestEnvironmentVariable } from "@/services/apiTesting";
import { useProjectStore } from "@/stores/project";

defineOptions({ name: "ApiEnvironmentView" });

const projectStore = useProjectStore();
const message = useMessage();

const loading = ref(false);
const saving = ref(false);
const items = ref<ApiTestEnvironment[]>([]);
const searchText = ref("");
const showEditor = ref(false);
const editingId = ref<string | null>(null);
const form = ref({
  name: "",
  base_url: "",
  description: "",
});
const showVariableModal = ref(false);
const showVariableEditor = ref(false);
const variableLoading = ref(false);
const variableSaving = ref(false);
const variableEnvironment = ref<ApiTestEnvironment | null>(null);
const variables = ref<ApiTestEnvironmentVariable[]>([]);
const variableSearchText = ref("");
const editingVariableId = ref<string | null>(null);
const variableForm = ref({
  key: "",
  value: "",
  description: "",
});

const filteredItems = computed(() => {
  const keyword = searchText.value.trim().toLowerCase();
  if (!keyword) return items.value;
  return items.value.filter((item) => {
    return (
      item.name.toLowerCase().includes(keyword) ||
      item.base_url.toLowerCase().includes(keyword) ||
      (item.description || "").toLowerCase().includes(keyword)
    );
  });
});

const filteredVariables = computed(() => {
  const keyword = variableSearchText.value.trim().toLowerCase();
  if (!keyword) return variables.value;
  return variables.value.filter((item) => {
    return (
      item.key.toLowerCase().includes(keyword) ||
      item.value.toLowerCase().includes(keyword) ||
      (item.description || "").toLowerCase().includes(keyword)
    );
  });
});

const columns: DataTableColumns<ApiTestEnvironment> = [
  {
    title: "环境名称",
    key: "name",
    minWidth: 180,
    render(row) {
      return h(
        "button",
        {
          class: "api-env-name",
          type: "button",
          onClick: () => openEditDrawer(row),
        },
        row.name,
      );
    },
  },
  {
    title: "环境 URL",
    key: "base_url",
    minWidth: 300,
    ellipsis: { tooltip: true },
    render(row) {
      return h("code", { class: "api-env-url" }, row.base_url);
    },
  },
  {
    title: "描述",
    key: "description",
    minWidth: 220,
    render(row) {
      return row.description || h(NText, { depth: 3 }, { default: () => "-" });
    },
  },
  {
    title: "更新时间",
    key: "updated_at",
    width: 180,
    render(row) {
      return new Date(row.updated_at).toLocaleString("zh-CN");
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 210,
    render(row) {
      return h(NSpace, { size: 6 }, () => [
        h(NButton, { size: "small", type: "primary", ghost: true, onClick: () => openVariableModal(row) }, {
          default: () => "变量",
        }),
        h(NButton, { size: "small", onClick: () => openEditDrawer(row) }, { default: () => "编辑" }),
        h(
          NPopconfirm,
          { onPositiveClick: () => deleteEnvironment(row.id) },
          {
            trigger: () => h(NButton, { size: "small", type: "error", ghost: true }, { default: () => "删除" }),
            default: () => `确认删除 API 环境「${row.name}」？已引用该环境的 API 会保留 Path，但不再绑定该环境。`,
          },
        ),
      ]);
    },
  },
];

const variableColumns: DataTableColumns<ApiTestEnvironmentVariable> = [
  {
    title: "Key",
    key: "key",
    minWidth: 160,
    render(row) {
      return h("code", { class: "api-env-url" }, row.key);
    },
  },
  {
    title: "Value",
    key: "value",
    minWidth: 220,
    ellipsis: { tooltip: true },
  },
  {
    title: "描述",
    key: "description",
    minWidth: 180,
    render(row) {
      return row.description || h(NText, { depth: 3 }, { default: () => "-" });
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 150,
    render(row) {
      return h(NSpace, { size: 6 }, () => [
        h(NButton, { size: "small", onClick: () => openEditVariableDrawer(row) }, { default: () => "编辑" }),
        h(
          NPopconfirm,
          { onPositiveClick: () => deleteVariable(row.id) },
          {
            trigger: () => h(NButton, { size: "small", type: "error", ghost: true }, { default: () => "删除" }),
            default: () => `确认删除环境变量「${row.key}」？`,
          },
        ),
      ]);
    },
  },
];

function openCreateDrawer() {
  editingId.value = null;
  form.value = { name: "", base_url: "", description: "" };
  showEditor.value = true;
}

function openEditDrawer(row: ApiTestEnvironment) {
  editingId.value = row.id;
  form.value = {
    name: row.name,
    base_url: row.base_url,
    description: row.description || "",
  };
  showEditor.value = true;
}

async function fetchItems() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) {
    items.value = [];
    return;
  }
  loading.value = true;
  try {
    const res = await listApiTestEnvironmentsApi(projectId);
    if (res.success) items.value = res.data;
  } catch {
    message.error("获取 API 环境失败");
  } finally {
    loading.value = false;
  }
}

async function saveEnvironment() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  if (!form.value.name.trim()) {
    message.warning("请输入环境名称");
    return;
  }
  if (!form.value.base_url.trim()) {
    message.warning("请输入环境 URL");
    return;
  }
  saving.value = true;
  const payload = {
    name: form.value.name.trim(),
    base_url: form.value.base_url.trim(),
    description: form.value.description.trim() || null,
  };
  try {
    if (editingId.value) {
      await updateApiTestEnvironmentApi(editingId.value, payload);
      message.success("API 环境已更新");
    } else {
      await createApiTestEnvironmentApi(projectId, payload);
      message.success("API 环境已创建");
    }
    showEditor.value = false;
    await fetchItems();
  } catch {
    message.error("保存 API 环境失败，请确认 URL 是 http/https 完整地址");
  } finally {
    saving.value = false;
  }
}

async function deleteEnvironment(id: string) {
  try {
    await deleteApiTestEnvironmentApi(id);
    message.success("API 环境已删除");
    await fetchItems();
  } catch {
    message.error("删除 API 环境失败");
  }
}

async function openVariableModal(row: ApiTestEnvironment) {
  variableEnvironment.value = row;
  variableSearchText.value = "";
  showVariableModal.value = true;
  await fetchVariables();
}

async function fetchVariables() {
  if (!variableEnvironment.value) {
    variables.value = [];
    return;
  }
  variableLoading.value = true;
  try {
    const res = await listApiTestEnvironmentVariablesApi(variableEnvironment.value.id);
    if (res.success) variables.value = res.data;
  } catch {
    message.error("获取环境变量失败");
  } finally {
    variableLoading.value = false;
  }
}

function openCreateVariableDrawer() {
  if (!variableEnvironment.value) return;
  editingVariableId.value = null;
  variableForm.value = { key: "", value: "", description: "" };
  showVariableEditor.value = true;
}

function openEditVariableDrawer(row: ApiTestEnvironmentVariable) {
  editingVariableId.value = row.id;
  variableForm.value = {
    key: row.key,
    value: row.value,
    description: row.description || "",
  };
  showVariableEditor.value = true;
}

async function saveVariable() {
  if (!variableEnvironment.value) return;
  if (!variableForm.value.key.trim()) {
    message.warning("请输入变量 Key");
    return;
  }
  if (!variableForm.value.value.trim()) {
    message.warning("请输入变量 Value");
    return;
  }
  variableSaving.value = true;
  const payload = {
    key: variableForm.value.key.trim(),
    value: variableForm.value.value.trim(),
    description: variableForm.value.description.trim() || null,
  };
  try {
    if (editingVariableId.value) {
      await updateApiTestEnvironmentVariableApi(editingVariableId.value, payload);
      message.success("环境变量已更新");
    } else {
      await createApiTestEnvironmentVariableApi(variableEnvironment.value.id, payload);
      message.success("环境变量已创建");
    }
    showVariableEditor.value = false;
    await fetchVariables();
  } catch {
    message.error("保存环境变量失败，请确认 Key 不重复且格式正确");
  } finally {
    variableSaving.value = false;
  }
}

async function deleteVariable(id: string) {
  try {
    await deleteApiTestEnvironmentVariableApi(id);
    message.success("环境变量已删除");
    await fetchVariables();
  } catch {
    message.error("删除环境变量失败");
  }
}

watch(() => projectStore.currentProjectId, fetchItems);
onMounted(fetchItems);
</script>

<style scoped>
.api-env-page {
  min-width: 0;
}

.api-env-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.api-env-toolbar__search {
  max-width: 360px;
}

.api-env-name {
  display: inline;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--primary-color);
  font: inherit;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.api-env-name:hover {
  text-decoration: underline;
}

.api-env-url {
  color: #334155;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 2px 6px;
}

.api-env-variable-modal {
  width: min(920px, 94vw);
}

.api-env-variable-modal__header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.api-env-variable-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
</style>
