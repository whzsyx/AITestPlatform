<template>
  <div class="api-auto-page">
    <page-header title="API 自动化" subtitle="编排多个接口并保存可手动或定时执行的任务" icon="i-carbon-flow" />

    <n-alert v-if="!projectStore.currentProjectId" type="warning" class="mb-4">
      请先在顶栏选择一个项目，再管理 API 自动化任务。
    </n-alert>

    <template v-else>
      <div class="api-auto-toolbar">
        <n-input
          v-model:value="searchText"
          placeholder="搜索任务名称"
          clearable
          class="api-auto-toolbar__search"
          @update:value="debouncedFetchTasks"
        >
          <template #prefix><span class="i-carbon-search text-gray-400" /></template>
        </n-input>
        <n-button v-if="canEditApi" type="primary" @click="openCreateDrawer">
          <template #icon><span class="i-carbon-add" /></template>
          新建任务
        </n-button>
      </div>

      <n-spin :show="loading">
        <n-data-table
          v-if="tasks.length > 0 || loading"
          :columns="columns"
          :data="tasks"
          :row-key="(row: ApiAutomationTaskListItem) => row.id"
          :bordered="false"
          :scroll-x="1180"
          striped
        />
        <app-empty
          v-else
          icon="i-carbon-flow"
          title="暂无 API 自动化任务"
          description="新建任务后，可以把多个 API 串成顺序执行链。"
          class="mt-12"
        >
          <template v-if="canEditApi" #actions>
            <n-button type="primary" @click="openCreateDrawer">新建任务</n-button>
          </template>
        </app-empty>
      </n-spin>

      <div v-if="total > 0" class="api-auto-pager">
        <n-text depth="3" class="text-xs">共 {{ total }} 个任务</n-text>
        <n-pagination
          v-model:page="page"
          :item-count="total"
          :page-size="pageSize"
          @update:page="fetchTasks"
        />
      </div>
    </template>

    <n-drawer v-model:show="showEditor" :width="960" placement="right">
      <n-drawer-content :title="editingId ? '编辑 API 自动化任务' : '新建 API 自动化任务'" closable>
        <n-form label-placement="top">
          <div class="api-auto-form-grid">
            <n-form-item label="任务名称" required>
              <n-input v-model:value="form.name" placeholder="例如：登录后查询用户资料" :maxlength="300" />
            </n-form-item>
            <n-form-item label="执行环境">
              <n-select
                v-model:value="form.environment_id"
                :options="environmentOptions"
                placeholder="默认使用各 API 自身环境"
                clearable
                filterable
              />
            </n-form-item>
          </div>

          <n-form-item label="任务描述">
            <n-input
              v-model:value="form.description"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="可选"
            />
          </n-form-item>

          <div class="api-auto-form-grid api-auto-form-grid--settings">
            <n-form-item label="启用任务">
              <n-switch v-model:value="form.enabled" />
            </n-form-item>
            <n-form-item label="失败处理">
              <n-switch v-model:value="form.stop_on_failure">
                <template #checked>失败停止</template>
                <template #unchecked>继续执行</template>
              </n-switch>
            </n-form-item>
            <n-form-item label="超时时间">
              <n-input-number v-model:value="form.timeout_seconds" :min="1" :max="60" :step="1">
                <template #suffix>秒</template>
              </n-input-number>
            </n-form-item>
            <n-form-item label="定时类型">
              <n-select v-model:value="form.schedule_type" :options="scheduleOptions" />
            </n-form-item>
            <n-form-item v-if="form.schedule_type === 'interval'" label="执行间隔">
              <n-input-number v-model:value="form.interval_minutes" :min="1" :max="43200" :step="5">
                <template #suffix>分钟</template>
              </n-input-number>
            </n-form-item>
            <n-form-item v-if="form.schedule_type === 'daily'" label="每日时间">
              <n-input v-model:value="form.daily_time" placeholder="09:30" />
            </n-form-item>
          </div>
        </n-form>

        <div class="api-auto-section">
          <div class="api-auto-section__head">
            <div class="api-auto-section__title">
              <span class="i-carbon-list-numbered text-brand" />
              <span>执行步骤</span>
            </div>
            <div class="api-auto-step-add">
              <n-select
                v-model:value="selectedApiId"
                :options="apiOptions"
                placeholder="选择 API"
                filterable
                class="api-auto-step-add__select"
              />
              <n-button :disabled="!selectedApiId" @click="addStep">
                <template #icon><span class="i-carbon-add" /></template>
                添加步骤
              </n-button>
            </div>
          </div>

          <div v-if="stepForms.length === 0" class="api-auto-steps-empty">
            <span class="i-carbon-api text-2xl opacity-40" />
            <span>请选择 API 添加执行步骤</span>
          </div>

          <div v-else class="api-auto-steps">
            <div v-for="(step, index) in stepForms" :key="step.local_id" class="api-auto-step-card">
              <div class="api-auto-step-card__head">
                <div class="api-auto-step-card__title">
                  <n-tag size="small" round>{{ index + 1 }}</n-tag>
                  <n-tag size="small" :type="methodTagType(step.method)">{{ step.method }}</n-tag>
                  <span>{{ step.api_name }}</span>
                </div>
                <n-space size="small">
                  <n-button size="tiny" :disabled="index === 0" @click="moveStep(index, -1)">
                    <template #icon><span class="i-carbon-arrow-up" /></template>
                  </n-button>
                  <n-button size="tiny" :disabled="index === stepForms.length - 1" @click="moveStep(index, 1)">
                    <template #icon><span class="i-carbon-arrow-down" /></template>
                  </n-button>
                  <n-button size="tiny" type="error" quaternary @click="removeStep(index)">
                    <template #icon><span class="i-carbon-trash-can" /></template>
                  </n-button>
                </n-space>
              </div>

              <div class="api-auto-step-card__body">
                <n-form label-placement="top">
                  <div class="api-auto-form-grid">
                    <n-form-item label="步骤名称">
                      <n-input v-model:value="step.name" placeholder="默认使用 API 名称" />
                    </n-form-item>
                    <n-form-item label="启用步骤">
                      <n-switch v-model:value="step.enabled" />
                    </n-form-item>
                  </div>
                  <n-tabs type="line" animated class="api-auto-override-tabs">
                    <n-tab-pane name="params" tab="参数">
                      <div class="api-auto-kv-head">
                        <span>Query 参数</span>
                        <n-button size="tiny" @click="addKeyValue(step.query_params)">
                          <template #icon><span class="i-carbon-add" /></template>
                          添加
                        </n-button>
                      </div>
                      <div v-if="step.query_params.length === 0" class="api-auto-kv-empty">
                        未覆盖 Query 参数
                      </div>
                      <div
                        v-for="(item, itemIndex) in step.query_params"
                        :key="item.local_id"
                        class="api-auto-kv-row"
                      >
                        <n-input v-model:value="item.key" placeholder="参数名" />
                        <n-input v-model:value="item.value" placeholder="参数值，例如 {{runtime.user_id}}" />
                        <n-button quaternary circle type="error" @click="step.query_params.splice(itemIndex, 1)">
                          <template #icon><span class="i-carbon-close" /></template>
                        </n-button>
                      </div>
                    </n-tab-pane>
                    <n-tab-pane name="headers" tab="请求头">
                      <div class="api-auto-kv-head">
                        <span>Header</span>
                        <n-button size="tiny" @click="addKeyValue(step.headers)">
                          <template #icon><span class="i-carbon-add" /></template>
                          添加
                        </n-button>
                      </div>
                      <div v-if="step.headers.length === 0" class="api-auto-kv-empty">
                        未覆盖请求头
                      </div>
                      <div
                        v-for="(item, itemIndex) in step.headers"
                        :key="item.local_id"
                        class="api-auto-kv-row"
                      >
                        <n-input v-model:value="item.key" placeholder="Header 名称" />
                        <n-input v-model:value="item.value" placeholder="Header 值，例如 Bearer {{runtime.token}}" />
                        <n-button quaternary circle type="error" @click="step.headers.splice(itemIndex, 1)">
                          <template #icon><span class="i-carbon-close" /></template>
                        </n-button>
                      </div>
                    </n-tab-pane>
                    <n-tab-pane name="body" tab="请求体">
                      <n-form-item label="Body 覆盖方式">
                        <n-select v-model:value="step.body_override_type" :options="bodyOverrideOptions" />
                      </n-form-item>
                      <n-form-item v-if="step.body_override_type === 'json'" label="JSON Body">
                        <n-input
                          v-model:value="step.body_json_text"
                          type="textarea"
                          :autosize="{ minRows: 4, maxRows: 10 }"
                          placeholder='{"mid":"{{runtime.mid}}"}'
                        />
                      </n-form-item>
                      <n-form-item v-if="step.body_override_type === 'text'" label="文本 Body">
                        <n-input
                          v-model:value="step.body_text"
                          type="textarea"
                          :autosize="{ minRows: 4, maxRows: 10 }"
                          placeholder="可使用 {{runtime.xxx}}"
                        />
                      </n-form-item>
                    </n-tab-pane>
                    <n-tab-pane name="url" tab="地址">
                      <div class="api-auto-form-grid">
                        <n-form-item label="覆盖 Base URL">
                          <n-input v-model:value="step.base_url" placeholder="默认不覆盖" />
                        </n-form-item>
                        <n-form-item label="覆盖 Path">
                          <n-input v-model:value="step.path_override" placeholder="/api/users/{{runtime.user_id}}" />
                        </n-form-item>
                      </div>
                    </n-tab-pane>
                  </n-tabs>
                </n-form>

                <div class="api-auto-extractors">
                  <div class="api-auto-extractors__head">
                    <span>响应提取</span>
                    <n-button size="tiny" @click="addExtractor(step)">
                      <template #icon><span class="i-carbon-add" /></template>
                      添加
                    </n-button>
                  </div>
                  <div v-if="step.extractors.length === 0" class="api-auto-extractors__empty">
                    未配置提取字段
                  </div>
                  <div
                    v-for="(extractor, extractorIndex) in step.extractors"
                    :key="extractor.local_id"
                    class="api-auto-extractor-row"
                  >
                    <n-input v-model:value="extractor.name" placeholder="变量名" />
                    <n-select v-model:value="extractor.source" :options="extractorSourceOptions" />
                    <n-input
                      v-if="extractor.source === 'response_header'"
                      v-model:value="extractor.header"
                      placeholder="Header 名称"
                    />
                    <n-input
                      v-else-if="extractor.source === 'response_json'"
                      v-model:value="extractor.path"
                      placeholder="$.data.token"
                    />
                    <n-input v-else disabled placeholder="无需填写" />
                    <n-button
                      quaternary
                      circle
                      type="error"
                      @click="step.extractors.splice(extractorIndex, 1)"
                    >
                      <template #icon><span class="i-carbon-close" /></template>
                    </n-button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <template #footer>
          <n-space justify="end">
            <n-button @click="showEditor = false">取消</n-button>
            <n-button type="primary" :loading="saving" @click="saveTask">保存</n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>

    <n-modal v-model:show="showRunModal" preset="card" class="api-auto-run-modal">
      <template #header>
        <div class="api-auto-run-modal__header">
          <span>执行报告</span>
          <n-tag v-if="runResult" :type="runResult.status === 'passed' ? 'success' : 'error'">
            {{ runResult.status === "passed" ? "通过" : "失败" }}
          </n-tag>
        </div>
      </template>
      <n-spin :show="running">
        <template v-if="runResult">
          <div class="api-auto-run-summary">
            <n-statistic label="总步骤" :value="runResult.total_steps" />
            <n-statistic label="通过" :value="runResult.passed_steps" />
            <n-statistic label="失败" :value="runResult.failed_steps" />
            <n-statistic label="跳过" :value="runResult.skipped_steps" />
            <n-statistic label="耗时 ms" :value="runResult.elapsed_ms" />
          </div>

          <n-collapse accordion class="api-auto-run-steps">
            <n-collapse-item
              v-for="step in runResult.steps"
              :key="step.id"
              :title="`${step.order_index}. ${step.name}`"
              :name="step.id"
            >
              <template #header-extra>
                <n-tag size="small" :type="stepStatusTagType(step.status)">
                  {{ stepStatusLabel(step.status) }}
                </n-tag>
              </template>
              <div class="api-auto-run-step">
                <div class="api-auto-run-step__meta">
                  <div><span>URL</span>{{ step.request_url || "-" }}</div>
                  <div><span>状态码</span>{{ step.status_code ?? "-" }}</div>
                  <div><span>耗时</span>{{ step.elapsed_ms }} ms</div>
                </div>
                <n-alert v-if="step.error" type="error" class="mb-3">{{ step.error }}</n-alert>
                <div v-if="Object.keys(step.extracted_values || {}).length" class="api-auto-runtime">
                  <n-tag
                    v-for="(value, key) in step.extracted_values"
                    :key="key"
                    size="small"
                    round
                  >
                    {{ key }} = {{ formatInline(value) }}
                  </n-tag>
                </div>
                <n-tabs type="line" animated>
                  <n-tab-pane name="request" tab="请求">
                    <n-code :code="formatJson(step.request_snapshot)" language="json" />
                  </n-tab-pane>
                  <n-tab-pane name="response" tab="响应">
                    <n-code :code="formatJson(step.response_snapshot)" language="json" />
                  </n-tab-pane>
                  <n-tab-pane name="assertions" tab="断言">
                    <assertion-list :items="step.assertion_results" />
                  </n-tab-pane>
                </n-tabs>
              </div>
            </n-collapse-item>
          </n-collapse>
        </template>
        <app-empty v-else icon="i-carbon-play" title="暂无执行结果" description="点击任务列表中的执行按钮后查看报告。" />
      </n-spin>
    </n-modal>

    <n-modal v-model:show="showHistoryModal" preset="card" class="api-auto-history-modal">
      <template #header>执行历史</template>
      <n-spin :show="historyLoading">
        <n-data-table
          :columns="historyColumns"
          :data="runHistory"
          :row-key="(row: ApiAutomationRunResult) => row.id"
          :bordered="false"
          :row-props="historyRowProps"
          :scroll-x="760"
          striped
        />
      </n-spin>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import type { VNodeChild } from "vue";
import {
  NAlert,
  NButton,
  NCode,
  NCollapse,
  NCollapseItem,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NPagination,
  NPopconfirm,
  NSelect,
  NSpace,
  NSpin,
  NStatistic,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  NText,
  useMessage,
} from "naive-ui";
import type { DataTableColumns, SelectOption } from "naive-ui";
import PageHeader from "@/components/common/PageHeader.vue";
import AppEmpty from "@/components/common/AppEmpty.vue";
import AssertionList from "@/components/api-testing/AssertionList.vue";
import {
  createApiAutomationTaskApi,
  deleteApiAutomationTaskApi,
  getApiAutomationRunApi,
  getApiAutomationTaskApi,
  listApiAutomationRunsApi,
  listApiAutomationTasksApi,
  listApiTestEnvironmentsApi,
  listApiTestsApi,
  runApiAutomationTaskApi,
  updateApiAutomationTaskApi,
} from "@/services/apiTesting";
import type {
  ApiAutomationExtractorSource,
  ApiAutomationRunResult,
  ApiAutomationStepPayload,
  ApiAutomationStepStatus,
  ApiAutomationTaskDetail,
  ApiAutomationTaskListItem,
  ApiAutomationTaskPayload,
  ApiBodyType,
  ApiMethod,
  ApiTestCaseListItem,
  ApiTestEnvironment,
} from "@/services/apiTesting";
import { useProjectStore } from "@/stores/project";
import { useAuthStore } from "@/stores/auth";

defineOptions({ name: "ApiAutomationView" });

interface ExtractorForm {
  local_id: string;
  name: string;
  source: ApiAutomationExtractorSource;
  path: string;
  header: string;
}

interface KeyValueForm {
  local_id: string;
  key: string;
  value: string;
}

type BodyOverrideType = "inherit" | ApiBodyType;

interface StepForm {
  local_id: string;
  id: string | null;
  api_case_id: string;
  api_name: string;
  method: ApiMethod;
  path: string | null;
  name: string;
  enabled: boolean;
  base_url: string;
  path_override: string;
  query_params: KeyValueForm[];
  headers: KeyValueForm[];
  body_override_type: BodyOverrideType;
  body_json_text: string;
  body_text: string;
  extractors: ExtractorForm[];
}

const projectStore = useProjectStore();
const authStore = useAuthStore();
const message = useMessage();
const route = useRoute();
const canEditApi = computed(() => authStore.hasPermission("api_test:edit"));
const canRunApi = computed(() => authStore.hasPermission("api_test:run"));

const loading = ref(false);
const saving = ref(false);
const running = ref(false);
const historyLoading = ref(false);
const tasks = ref<ApiAutomationTaskListItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const searchText = ref("");
const environments = ref<ApiTestEnvironment[]>([]);
const apis = ref<ApiTestCaseListItem[]>([]);
const selectedApiId = ref<string | null>(null);
const showEditor = ref(false);
const showRunModal = ref(false);
const showHistoryModal = ref(false);
const editingId = ref<string | null>(null);
const runResult = ref<ApiAutomationRunResult | null>(null);
const runHistory = ref<ApiAutomationRunResult[]>([]);
const appliedRunQuery = ref<string | null>(null);
let searchTimer: number | undefined;

const form = ref({
  name: "",
  description: "",
  environment_id: null as string | null,
  enabled: true,
  schedule_type: "manual" as "manual" | "interval" | "daily",
  interval_minutes: 60,
  daily_time: "09:00",
  timeout_seconds: 20,
  stop_on_failure: true,
});
const stepForms = ref<StepForm[]>([]);

const scheduleOptions = [
  { label: "手动", value: "manual" },
  { label: "间隔", value: "interval" },
  { label: "每日", value: "daily" },
];

const extractorSourceOptions = [
  { label: "JSONPath", value: "response_json" },
  { label: "响应头", value: "response_header" },
  { label: "响应文本", value: "response_text" },
  { label: "状态码", value: "status_code" },
];

const bodyOverrideOptions = [
  { label: "不覆盖", value: "inherit" },
  { label: "无 Body", value: "none" },
  { label: "JSON", value: "json" },
  { label: "文本", value: "text" },
];

const environmentOptions = computed<SelectOption[]>(() =>
  environments.value.map((item) => ({
    label: `${item.name} · ${item.base_url}`,
    value: item.id,
  })),
);

const apiOptions = computed<SelectOption[]>(() =>
  apis.value.map((item) => ({
    label: `${item.method} ${item.name} · ${item.path || item.url}`,
    value: item.id,
  })),
);

const columns: DataTableColumns<ApiAutomationTaskListItem> = [
  {
    title: "任务名称",
    key: "name",
    minWidth: 220,
    render(row) {
      const content = [
        h("span", { class: "api-auto-task-title__name" }, row.name),
        row.description
          ? h("span", { class: "api-auto-task-title__desc" }, row.description)
          : null,
      ];
      if (!canEditApi.value) {
        return h("div", { class: "api-auto-task-title api-auto-task-title--readonly" }, content);
      }
      return h(
        "div",
        {
          class: "api-auto-task-title",
          role: "button",
          tabindex: 0,
          onClick: () => openEditDrawer(row),
          onKeydown: (event: KeyboardEvent) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openEditDrawer(row);
            }
          },
        },
        content,
      );
    },
  },
  {
    title: "步骤",
    key: "step_count",
    width: 80,
  },
  {
    title: "环境",
    key: "environment_name",
    minWidth: 160,
    render(row) {
      return row.environment_name || "各 API 自身环境";
    },
  },
  {
    title: "定时",
    key: "schedule_type",
    minWidth: 150,
    render(row) {
      return scheduleText(row);
    },
  },
  {
    title: "启用",
    key: "enabled",
    width: 90,
    render(row) {
      return h(NTag, { size: "small", type: row.enabled ? "success" : "default" }, () =>
        row.enabled ? "启用" : "停用",
      );
    },
  },
  {
    title: "下次执行",
    key: "next_run_at",
    minWidth: 170,
    render(row) {
      return formatTime(row.next_run_at);
    },
  },
  {
    title: "最近执行",
    key: "last_run_at",
    minWidth: 170,
    render(row) {
      return formatTime(row.last_run_at);
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 280,
    fixed: "right",
    render(row) {
      const actions: VNodeChild[] = [];
      if (canRunApi.value) {
        actions.push(
          h(
            NButton,
            { size: "small", type: "primary", loading: running.value, onClick: () => runTask(row) },
            { icon: () => h("span", { class: "i-carbon-play-filled-alt" }), default: () => "执行" },
          ),
        );
      }
      actions.push(h(NButton, { size: "small", onClick: () => openHistory(row) }, { default: () => "历史" }));
      if (canEditApi.value) {
        actions.push(
          h(NButton, { size: "small", onClick: () => openEditDrawer(row) }, { default: () => "编辑" }),
          h(
            NPopconfirm,
            { onPositiveClick: () => deleteTask(row) },
            {
              trigger: () =>
                h(
                  NButton,
                  { size: "small", type: "error", quaternary: true },
                  { default: () => "删除" },
                ),
              default: () => `确定删除任务「${row.name}」吗？`,
            },
          ),
        );
      }
      return h(NSpace, { size: "small" }, () => actions);
    },
  },
];

const historyColumns: DataTableColumns<ApiAutomationRunResult> = [
  {
    title: "状态",
    key: "status",
    width: 82,
    render(row) {
      return h(NTag, { size: "small", type: row.status === "passed" ? "success" : "error" }, () =>
        row.status === "passed" ? "通过" : "失败",
      );
    },
  },
  {
    title: "触发",
    key: "trigger_type",
    width: 96,
    render(row) {
      return h(
        NTag,
        { size: "small", type: row.trigger_type === "schedule" ? "info" : "default" },
        () => triggerTypeLabel(row.trigger_type),
      );
    },
  },
  {
    title: "通过/总数",
    key: "summary",
    width: 96,
    render(row) {
      return `${row.passed_steps}/${row.total_steps}`;
    },
  },
  {
    title: "耗时",
    key: "elapsed_ms",
    width: 96,
    render(row) {
      return `${row.elapsed_ms} ms`;
    },
  },
  {
    title: "开始时间",
    key: "started_at",
    width: 170,
    render(row) {
      return formatTime(row.started_at);
    },
  },
  {
    title: "错误",
    key: "error",
    width: 180,
    ellipsis: { tooltip: true },
    render(row) {
      return row.error
        ? h("span", { class: "api-auto-history-error" }, row.error)
        : h(NText, { depth: 3 }, () => "-");
    },
  },
];

function debouncedFetchTasks() {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    page.value = 1;
    fetchTasks();
  }, 260);
}

async function fetchTasks() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) {
    tasks.value = [];
    total.value = 0;
    return;
  }
  loading.value = true;
  try {
    const res = await listApiAutomationTasksApi(projectId, {
      page: page.value,
      page_size: pageSize.value,
      search: searchText.value.trim() || undefined,
    });
    if (res.success) {
      tasks.value = res.data.items;
      total.value = res.data.total;
    }
  } catch {
    message.error("获取 API 自动化任务失败");
  } finally {
    loading.value = false;
  }
}

async function fetchSupportingData() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) {
    environments.value = [];
    apis.value = [];
    return;
  }
  try {
    const [envRes, apiRes] = await Promise.all([
      listApiTestEnvironmentsApi(projectId),
      listApiTestsApi(projectId, { page: 1, page_size: 100 }),
    ]);
    environments.value = envRes.success ? envRes.data : [];
    apis.value = apiRes.success ? apiRes.data.items : [];
  } catch {
    message.error("获取 API 基础数据失败");
  }
}

function openCreateDrawer() {
  if (!ensureCanEditApi()) return;
  editingId.value = null;
  form.value = {
    name: "",
    description: "",
    environment_id: null,
    enabled: true,
    schedule_type: "manual",
    interval_minutes: 60,
    daily_time: "09:00",
    timeout_seconds: 20,
    stop_on_failure: true,
  };
  stepForms.value = [];
  selectedApiId.value = null;
  showEditor.value = true;
}

async function openEditDrawer(row: ApiAutomationTaskListItem) {
  if (!ensureCanEditApi()) return;
  try {
    const res = await getApiAutomationTaskApi(row.id);
    if (!res.success) return;
    const detail = res.data;
    editingId.value = detail.id;
    form.value = {
      name: detail.name,
      description: detail.description || "",
      environment_id: detail.environment_id,
      enabled: detail.enabled,
      schedule_type: detail.schedule_type,
      interval_minutes: detail.interval_minutes || 60,
      daily_time: detail.daily_time || "09:00",
      timeout_seconds: detail.timeout_seconds,
      stop_on_failure: detail.stop_on_failure,
    };
    stepForms.value = detail.steps.map(stepToForm);
    selectedApiId.value = null;
    showEditor.value = true;
  } catch {
    message.error("获取任务详情失败");
  }
}

function stepToForm(step: ApiAutomationTaskDetail["steps"][number]): StepForm {
  const overrides = step.request_overrides || {};
  const bodyOverrideType = inferBodyOverrideType(overrides);
  return {
    local_id: step.id,
    id: step.id,
    api_case_id: step.api_case_id,
    api_name: step.api_name || step.name || "未命名 API",
    method: (step.method || "GET") as ApiMethod,
    path: step.path,
    name: step.name || "",
    enabled: step.enabled,
    base_url: stringOverride(overrides.base_url),
    path_override: stringOverride(overrides.path),
    query_params: mappingToKeyValues(overrides.query_params),
    headers: mappingToKeyValues(overrides.headers),
    body_override_type: bodyOverrideType,
    body_json_text:
      "body_json" in overrides ? JSON.stringify(overrides.body_json ?? {}, null, 2) : "",
    body_text: stringOverride(overrides.body_text),
    extractors: (step.extractors || []).map((item) => ({
      local_id: `${step.id}-${item.name}-${Math.random()}`,
      name: item.name,
      source: item.source,
      path: item.path || "",
      header: item.header || "",
    })),
  };
}

function addStep() {
  if (!ensureCanEditApi()) return;
  const api = apis.value.find((item) => item.id === selectedApiId.value);
  if (!api) return;
  stepForms.value.push({
    local_id: `${api.id}-${Date.now()}`,
    id: null,
    api_case_id: api.id,
    api_name: api.name,
    method: api.method,
    path: api.path,
    name: "",
    enabled: true,
    base_url: "",
    path_override: "",
    query_params: [],
    headers: [],
    body_override_type: "inherit",
    body_json_text: "",
    body_text: "",
    extractors: [],
  });
  selectedApiId.value = null;
}

function removeStep(index: number) {
  if (!ensureCanEditApi()) return;
  stepForms.value.splice(index, 1);
}

function moveStep(index: number, delta: number) {
  if (!ensureCanEditApi()) return;
  const target = index + delta;
  if (target < 0 || target >= stepForms.value.length) return;
  const copy = [...stepForms.value];
  const [item] = copy.splice(index, 1);
  copy.splice(target, 0, item);
  stepForms.value = copy;
}

function addExtractor(step: StepForm) {
  if (!ensureCanEditApi()) return;
  step.extractors.push({
    local_id: `${step.local_id}-extractor-${Date.now()}`,
    name: "",
    source: "response_json",
    path: "$.data.id",
    header: "",
  });
}

function addKeyValue(target: KeyValueForm[]) {
  if (!ensureCanEditApi()) return;
  target.push({
    local_id: `kv-${Date.now()}-${Math.random()}`,
    key: "",
    value: "",
  });
}

async function saveTask() {
  if (!ensureCanEditApi()) return;
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  const payload = buildPayload();
  if (!payload) return;
  saving.value = true;
  try {
    if (editingId.value) {
      await updateApiAutomationTaskApi(editingId.value, payload);
      message.success("任务已更新");
    } else {
      await createApiAutomationTaskApi(projectId, payload);
      message.success("任务已创建");
    }
    showEditor.value = false;
    await fetchTasks();
  } catch {
    message.error("保存 API 自动化任务失败");
  } finally {
    saving.value = false;
  }
}

function buildPayload(): ApiAutomationTaskPayload | null {
  if (!form.value.name.trim()) {
    message.warning("请填写任务名称");
    return null;
  }
  if (stepForms.value.length === 0) {
    message.warning("请至少添加一个执行步骤");
    return null;
  }
  const steps: ApiAutomationStepPayload[] = [];
  for (const [index, step] of stepForms.value.entries()) {
    const requestOverrides = buildRequestOverrides(step);
    if (!requestOverrides) return null;
    steps.push({
      id: step.id,
      api_case_id: step.api_case_id,
      name: step.name.trim() || null,
      enabled: step.enabled,
      order_index: index + 1,
      request_overrides: requestOverrides,
      extractors: step.extractors
        .filter((item) => item.name.trim())
        .map((item) => ({
          name: item.name.trim(),
          source: item.source,
          path: item.path.trim() || null,
          header: item.header.trim() || null,
        })),
    });
  }
  return {
    name: form.value.name.trim(),
    description: form.value.description.trim() || null,
    environment_id: form.value.environment_id,
    enabled: form.value.enabled,
    schedule_type: form.value.schedule_type,
    interval_minutes: form.value.schedule_type === "interval" ? form.value.interval_minutes : null,
    daily_time: form.value.schedule_type === "daily" ? form.value.daily_time : null,
    timeout_seconds: Number(form.value.timeout_seconds || 20),
    stop_on_failure: form.value.stop_on_failure,
    steps,
  };
}

function buildRequestOverrides(step: StepForm): Record<string, unknown> | null {
  const out: Record<string, unknown> = {};
  const queryParams = keyValuesToMapping(step.query_params);
  const headers = keyValuesToMapping(step.headers);
  if (Object.keys(queryParams).length > 0) out.query_params = queryParams;
  if (Object.keys(headers).length > 0) out.headers = headers;
  if (step.base_url.trim()) out.base_url = step.base_url.trim();
  if (step.path_override.trim()) out.path = step.path_override.trim();

  if (step.body_override_type === "none") {
    out.body_type = "none";
    out.body_json = null;
    out.body_text = null;
  } else if (step.body_override_type === "json") {
    const parsed = parseBodyJson(step.body_json_text, step.api_name);
    if (parsed === undefined) return null;
    out.body_type = "json";
    out.body_json = parsed;
    out.body_text = null;
  } else if (step.body_override_type === "text") {
    out.body_type = "text";
    out.body_json = null;
    out.body_text = step.body_text;
  }
  return out;
}

function keyValuesToMapping(items: KeyValueForm[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const item of items) {
    const key = item.key.trim();
    if (!key) continue;
    out[key] = item.value;
  }
  return out;
}

function mappingToKeyValues(value: unknown): KeyValueForm[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => ({
    local_id: `kv-${key}-${Math.random()}`,
    key,
    value: stringifyKeyValue(item),
  }));
}

function inferBodyOverrideType(overrides: Record<string, unknown>): BodyOverrideType {
  if (overrides.body_type === "none") return "none";
  if (overrides.body_type === "json" || "body_json" in overrides) return "json";
  if (overrides.body_type === "text" || "body_text" in overrides) return "text";
  return "inherit";
}

function parseBodyJson(text: string, apiName: string): unknown | undefined {
  const raw = text.trim();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    try {
      return JSON.parse(normalizeJsonTemplatePlaceholders(raw));
    } catch {
      message.warning(`步骤「${apiName}」的 JSON Body 格式不正确`);
      return undefined;
    }
  }
}

function normalizeJsonTemplatePlaceholders(raw: string): string {
  const variablePattern = "[A-Za-z_][A-Za-z0-9_.-]*";
  const rootPattern = new RegExp(`^\\s*\\{\\{\\s*(${variablePattern})\\s*\\}\\}\\s*$`);
  const rootMatch = raw.match(rootPattern);
  if (rootMatch) {
    return `"{{${rootMatch[1]}}}"`;
  }
  return raw.replace(
    new RegExp(`([:\\[,]+\\s*)\\{\\{\\s*(${variablePattern})\\s*\\}\\}`, "g"),
    (_match, prefix: string, key: string) => `${prefix}"{{${key}}}"`,
  );
}

function stringOverride(value: unknown): string {
  if (value == null) return "";
  return typeof value === "string" ? value : String(value);
}

function stringifyKeyValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

async function runTask(row: ApiAutomationTaskListItem) {
  if (!ensureCanRunApi()) return;
  running.value = true;
  showRunModal.value = true;
  runResult.value = null;
  try {
    const res = await runApiAutomationTaskApi(row.id);
    if (res.success) {
      runResult.value = res.data;
      await fetchTasks();
    }
  } catch {
    message.error("执行 API 自动化任务失败");
  } finally {
    running.value = false;
  }
}

async function openHistory(row: ApiAutomationTaskListItem) {
  showHistoryModal.value = true;
  historyLoading.value = true;
  try {
    const res = await listApiAutomationRunsApi(row.id, { page: 1, page_size: 20 });
    runHistory.value = res.success ? res.data.items : [];
  } catch {
    message.error("获取执行历史失败");
  } finally {
    historyLoading.value = false;
  }
}

function historyRowProps(row: ApiAutomationRunResult) {
  return {
    class: "api-auto-history-row",
    onClick: () => {
      runResult.value = row;
      showRunModal.value = true;
    },
  };
}

async function openRunFromRouteQuery() {
  const runId = typeof route.query.run_id === "string" ? route.query.run_id : "";
  if (!runId || appliedRunQuery.value === runId) return;

  appliedRunQuery.value = runId;
  showRunModal.value = true;
  running.value = true;
  runResult.value = null;
  try {
    const res = await getApiAutomationRunApi(runId);
    if (res.success) {
      runResult.value = res.data;
    }
  } catch {
    message.error("加载 API 自动化执行报告失败");
  } finally {
    running.value = false;
  }
}

async function deleteTask(row: ApiAutomationTaskListItem) {
  if (!ensureCanEditApi()) return;
  try {
    await deleteApiAutomationTaskApi(row.id);
    message.success("任务已删除");
    await fetchTasks();
  } catch {
    message.error("删除 API 自动化任务失败");
  }
}

function ensureCanEditApi() {
  if (canEditApi.value) return true;
  message.warning("没有 API 管理编辑权限");
  return false;
}

function ensureCanRunApi() {
  if (canRunApi.value) return true;
  message.warning("没有 API 测试执行权限");
  return false;
}

function scheduleText(row: ApiAutomationTaskListItem) {
  if (row.schedule_type === "manual") return "手动";
  if (row.schedule_type === "interval") return `每 ${row.interval_minutes || "-"} 分钟`;
  return `每日 ${row.daily_time || "-"}`;
}

function triggerTypeLabel(value: ApiAutomationRunResult["trigger_type"]) {
  if (value === "schedule") return "定时执行";
  return "手动执行";
}

function formatTime(value: string | null | undefined) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatJson(value: unknown) {
  if (value == null) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatInline(value: unknown) {
  if (typeof value === "string") return value;
  return formatJson(value);
}

function methodTagType(method: ApiMethod | null) {
  if (method === "GET") return "info";
  if (method === "POST") return "success";
  if (method === "DELETE") return "error";
  return "warning";
}

function stepStatusTagType(status: ApiAutomationStepStatus) {
  if (status === "passed") return "success";
  if (status === "skipped") return "warning";
  if (status === "running") return "info";
  return "error";
}

function stepStatusLabel(status: ApiAutomationStepStatus) {
  if (status === "passed") return "通过";
  if (status === "skipped") return "跳过";
  if (status === "running") return "运行中";
  return "失败";
}

watch(
  () => projectStore.currentProjectId,
  async () => {
    page.value = 1;
    await Promise.all([fetchSupportingData(), fetchTasks()]);
  },
  { immediate: true },
);

watch(
  () => route.query.run_id,
  () => {
    openRunFromRouteQuery();
  },
);

onMounted(openRunFromRouteQuery);
</script>

<style scoped>
.api-auto-page {
  min-width: 0;
}

.api-auto-toolbar,
.api-auto-section__head,
.api-auto-step-card__head,
.api-auto-extractors__head,
.api-auto-run-modal__header,
.api-auto-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.api-auto-toolbar {
  margin-bottom: 16px;
}

.api-auto-toolbar__search {
  max-width: 360px;
}

.api-auto-task-title {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  max-width: 100%;
  cursor: pointer;
  line-height: 1.35;
  outline: none;
}

.api-auto-task-title--readonly {
  cursor: default;
}

.api-auto-task-title__name {
  color: var(--text-primary);
  font-weight: 600;
  transition: color var(--duration-fast) var(--easing-standard);
}

.api-auto-task-title__desc {
  max-width: 360px;
  color: var(--text-tertiary);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.api-auto-task-title:not(.api-auto-task-title--readonly):hover .api-auto-task-title__name,
.api-auto-task-title:focus-visible .api-auto-task-title__name {
  color: var(--brand-primary);
}

.api-auto-pager {
  margin-top: 16px;
}

.api-auto-form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.api-auto-form-grid--settings {
  grid-template-columns: 120px 140px 140px minmax(150px, 1fr) minmax(150px, 1fr);
}

.api-auto-section {
  margin-top: 8px;
}

.api-auto-section__head {
  margin-bottom: 12px;
}

.api-auto-section__title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.api-auto-step-add {
  display: flex;
  align-items: center;
  gap: 8px;
}

.api-auto-step-add__select {
  width: 360px;
}

.api-auto-steps {
  display: grid;
  gap: 12px;
}

.api-auto-steps-empty,
.api-auto-extractors__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 96px;
  color: var(--text-tertiary);
  border: 1px dashed var(--border-subtle);
  border-radius: var(--radius-md);
}

.api-auto-extractors__empty {
  min-height: 42px;
  font-size: 12px;
}

.api-auto-step-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-card);
}

.api-auto-step-card__head {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.api-auto-step-card__title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  min-width: 0;
}

.api-auto-step-card__body {
  padding: 12px;
}

.api-auto-extractors__head {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
}

.api-auto-override-tabs {
  margin-top: 4px;
}

.api-auto-kv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
}

.api-auto-kv-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  color: var(--text-tertiary);
  font-size: 12px;
  border: 1px dashed var(--border-subtle);
  border-radius: var(--radius-md);
}

.api-auto-kv-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(180px, 2fr) 34px;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.api-auto-extractor-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) 130px minmax(160px, 1.5fr) 34px;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.api-auto-run-modal {
  width: min(1080px, 92vw);
}

.api-auto-history-modal {
  width: min(860px, 90vw);
}

.api-auto-run-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.api-auto-run-step__meta {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px 120px;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
}

.api-auto-run-step__meta span {
  display: block;
  color: var(--text-tertiary);
  font-size: 12px;
  margin-bottom: 2px;
}

.api-auto-runtime {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

:deep(.api-auto-history-row) {
  cursor: pointer;
}

.api-auto-history-error {
  display: inline-block;
  max-width: 168px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
  color: var(--text-secondary);
}

:deep(.api-auto-history-row:hover td) {
  background: var(--bg-active);
}

@media (max-width: 900px) {
  .api-auto-form-grid,
  .api-auto-form-grid--settings,
  .api-auto-run-summary,
  .api-auto-run-step__meta,
  .api-auto-kv-row,
  .api-auto-extractor-row {
    grid-template-columns: 1fr;
  }

  .api-auto-toolbar,
  .api-auto-section__head,
  .api-auto-step-add {
    align-items: stretch;
    flex-direction: column;
  }

  .api-auto-toolbar__search,
  .api-auto-step-add__select {
    max-width: none;
    width: 100%;
  }
}
</style>
