<template>
  <div class="api-test-page">
    <page-header title="API 列表" subtitle="维护常规 HTTP API，请求地址由环境 URL 或自定义 URL 与 Path 组合" icon="i-carbon-api" />

    <n-alert v-if="!projectStore.currentProjectId" type="warning" class="mb-4">
      请先在顶栏选择一个项目，再管理 API。
    </n-alert>

    <div
      v-else
      class="api-test-layout"
      :class="{ 'api-test-layout--side-collapsed': moduleSidebarCollapsed }"
    >
      <aside
        class="api-test-layout__side"
        :class="{ 'api-test-layout__side--collapsed': moduleSidebarCollapsed }"
      >
        <div v-show="moduleSidebarCollapsed" class="api-test-layout__side-rail">
          <n-tooltip placement="right">
            <template #trigger>
              <n-button size="small" quaternary circle @click="moduleSidebarCollapsed = false">
                <template #icon><span class="i-carbon-chevron-right" /></template>
              </n-button>
            </template>
            展开模块目录
          </n-tooltip>
          <n-tooltip placement="right">
            <template #trigger>
              <n-button
                size="small"
                quaternary
                circle
                :class="{ 'text-brand': selectedModuleId == null }"
                @click="handleShowAll"
              >
                <template #icon><span class="i-carbon-list" /></template>
              </n-button>
            </template>
            查看全部 API
          </n-tooltip>
          <n-tooltip placement="right">
            <template #trigger>
              <n-button size="small" quaternary circle @click="moduleTreeRef?.openAddRootDialog()">
                <template #icon><span class="i-carbon-add" /></template>
              </n-button>
            </template>
            新建模块
          </n-tooltip>
        </div>

        <div v-show="!moduleSidebarCollapsed" class="api-test-layout__side-header">
          <div class="api-test-layout__side-title">
            <span class="i-carbon-tree-view text-brand" />
            <span>模块目录</span>
          </div>
          <div class="api-test-layout__side-actions">
            <n-tooltip placement="top">
              <template #trigger>
                <n-button size="tiny" quaternary circle @click="moduleSidebarCollapsed = true">
                  <template #icon><span class="i-carbon-chevron-left" /></template>
                </n-button>
              </template>
              收起模块目录
            </n-tooltip>
            <n-tooltip placement="top">
              <template #trigger>
                <n-button size="tiny" quaternary circle @click="moduleTreeRef?.openAddRootDialog()">
                  <template #icon><span class="i-carbon-add" /></template>
                </n-button>
              </template>
              新建模块
            </n-tooltip>
            <n-tooltip placement="top">
              <template #trigger>
                <n-button
                  size="tiny"
                  quaternary
                  circle
                  :class="{ 'text-brand': selectedModuleId == null }"
                  @click="handleShowAll"
                >
                  <template #icon><span class="i-carbon-list" /></template>
                </n-button>
              </template>
              查看全部 API
            </n-tooltip>
          </div>
        </div>
        <div v-show="!moduleSidebarCollapsed" class="api-test-layout__side-body">
          <api-module-tree
            ref="moduleTreeRef"
            :show-case-count="false"
            @select="handleModuleSelect"
            @changed="handleModuleTreeChanged"
          />
        </div>
      </aside>

      <section class="api-test-layout__main">
        <div class="api-test-toolbar">
          <n-input
            v-model:value="searchText"
            placeholder="搜索 API 名称、URL 或 Path"
            clearable
            class="api-test-toolbar__search"
            @update:value="debouncedFetch"
          >
            <template #prefix><span class="i-carbon-search text-gray-400" /></template>
          </n-input>
          <div class="api-test-toolbar__actions">
            <n-button
              :disabled="selectedBatchCount === 0"
              :loading="batchRunning"
              @click="runSelectedBatch"
            >
              <template #icon><span class="i-carbon-play-filled-alt" /></template>
              批量执行 {{ selectedBatchCount ? `(${selectedBatchCount})` : "" }}
            </n-button>
            <n-button
              :disabled="!selectedModuleId"
              :loading="batchRunning"
              @click="runCurrentModuleBatch"
            >
              <template #icon><span class="i-carbon-play-outline" /></template>
              当前模块全部执行
            </n-button>
            <n-button type="primary" @click="openCreateDrawer">
              <template #icon><span class="i-carbon-add" /></template>
              新建 API
            </n-button>
          </div>
        </div>

        <n-spin :show="loading" class="api-test-table">
          <n-data-table
            v-if="items.length > 0 || loading"
            class="api-test-data-table"
            :columns="columns"
            :data="items"
            :row-key="(row: ApiTestCaseListItem) => row.id"
            :bordered="false"
            :checked-row-keys="checkedRowKeys"
            :scroll-x="1360"
            striped
            @update:checked-row-keys="handleCheckedRowKeys"
          />
          <app-empty
            v-else
            icon="i-carbon-api"
            title="暂无 API"
            :description="selectedModuleId ? '该模块下还没有 API，可新建一条 HTTP 请求。' : '选择左侧模块后新建 API，API 必须保存到具体模块下。'"
            class="mt-12"
          >
            <template #actions>
              <n-button type="primary" @click="openCreateDrawer">新建 API</n-button>
            </template>
          </app-empty>
        </n-spin>

        <div v-if="total > 0" class="api-test-pager">
          <n-text depth="3" class="text-xs">共 {{ total }} 条 API</n-text>
          <n-pagination
            v-model:page="page"
            :item-count="total"
            :page-size="pageSize"
            @update:page="fetchCases"
          />
        </div>
      </section>
    </div>

    <n-drawer v-model:show="showEditor" :width="720" placement="right">
      <n-drawer-content :title="editingId ? '编辑 API' : '新建 API'" closable>
        <n-form label-placement="top">
          <n-form-item label="所属模块" required>
            <n-select
              v-model:value="form.module_id"
              :options="moduleOptions"
              placeholder="请选择模块"
              filterable
            />
          </n-form-item>
          <n-form-item label="API 名称" required>
            <n-input v-model:value="form.name" placeholder="例如：创建订单接口" :maxlength="300" />
          </n-form-item>
          <div class="api-test-form-grid">
            <n-form-item label="请求方法" required>
              <n-select v-model:value="form.method" :options="methodOptions" />
            </n-form-item>
            <n-form-item label="URL 来源" required>
              <n-radio-group v-model:value="form.url_mode">
                <n-radio-button value="environment">选择环境 URL</n-radio-button>
                <n-radio-button value="custom">手动填写 URL</n-radio-button>
              </n-radio-group>
            </n-form-item>
          </div>
          <div class="api-test-form-grid api-test-form-grid--url">
            <n-form-item v-if="form.url_mode === 'environment'" label="环境 URL" required>
              <n-select
                v-model:value="form.environment_id"
                :options="environmentOptions"
                placeholder="请选择环境"
                filterable
              />
            </n-form-item>
            <n-form-item v-else label="Base URL" required>
              <n-input v-model:value="form.base_url" placeholder="https://api.example.com" />
            </n-form-item>
            <n-form-item label="Path 路径" required>
              <n-auto-complete
                v-model:value="form.path"
                :options="variableAutoOptions(form.path)"
                placeholder="/api/orders"
              />
            </n-form-item>
          </div>
          <n-tabs v-model:value="editorTab" type="line" animated class="api-test-editor-tabs">
            <n-tab-pane name="params" tab="参数">
              <div class="api-test-kv-list">
                <div class="api-test-kv-list__head">
                  <span>Key</span>
                  <span>Value</span>
                  <span />
                </div>
                <div
                  v-for="(row, index) in paramRows"
                  :key="row.id"
                  class="api-test-kv-row"
                >
                  <n-auto-complete
                    v-model:value="row.key"
                    :options="variableAutoOptions(row.key)"
                    placeholder="page"
                  />
                  <n-auto-complete
                    v-model:value="row.value"
                    :options="variableAutoOptions(row.value)"
                    placeholder="1"
                  />
                  <n-button quaternary circle @click="removeKeyValueRow(paramRows, index)">
                    <template #icon><span class="i-carbon-trash-can" /></template>
                  </n-button>
                </div>
                <n-button size="small" secondary @click="addKeyValueRow(paramRows)">
                  <template #icon><span class="i-carbon-add" /></template>
                  添加参数
                </n-button>
              </div>
            </n-tab-pane>
            <n-tab-pane name="headers" tab="请求头">
              <div class="api-test-kv-list">
                <div class="api-test-kv-list__head">
                  <span>Key</span>
                  <span>Value</span>
                  <span />
                </div>
                <div
                  v-for="(row, index) in headerRows"
                  :key="row.id"
                  class="api-test-kv-row"
                >
                  <n-auto-complete
                    v-model:value="row.key"
                    :options="variableAutoOptions(row.key)"
                    placeholder="Content-Type"
                  />
                  <n-auto-complete
                    v-model:value="row.value"
                    :options="variableAutoOptions(row.value)"
                    placeholder="application/json"
                  />
                  <n-button quaternary circle @click="removeKeyValueRow(headerRows, index)">
                    <template #icon><span class="i-carbon-trash-can" /></template>
                  </n-button>
                </div>
                <n-button size="small" secondary @click="addKeyValueRow(headerRows)">
                  <template #icon><span class="i-carbon-add" /></template>
                  添加请求头
                </n-button>
              </div>
            </n-tab-pane>
            <n-tab-pane name="body" tab="请求体">
              <n-form-item label="请求体类型">
                <n-radio-group v-model:value="form.body_type">
                  <n-radio-button value="none">无</n-radio-button>
                  <n-radio-button value="json">JSON</n-radio-button>
                  <n-radio-button value="text">文本</n-radio-button>
                </n-radio-group>
              </n-form-item>
              <n-form-item v-if="form.body_type === 'json'" label="JSON 请求数据">
                <n-input
                  v-model:value="bodyJsonText"
                  type="textarea"
                  :autosize="{ minRows: 8, maxRows: 18 }"
                  placeholder='{"name":"demo"}'
                />
              </n-form-item>
              <n-form-item v-if="form.body_type === 'text'" label="文本请求数据">
                <n-input
                  v-model:value="bodyText"
                  type="textarea"
                  :autosize="{ minRows: 8, maxRows: 18 }"
                />
              </n-form-item>
            </n-tab-pane>
          </n-tabs>
          <div class="api-test-assertions">
            <div class="api-test-assertions__title">断言</div>
            <div class="api-test-form-grid">
              <n-form-item label="期望状态码">
                <n-input-number v-model:value="assertStatusCode" :min="100" :max="599" />
              </n-form-item>
              <n-form-item label="响应包含文本">
                <n-auto-complete
                  v-model:value="assertBodyContains"
                  :options="variableAutoOptions(assertBodyContains)"
                  placeholder="可选"
                />
              </n-form-item>
            </div>
            <div class="api-test-form-grid">
              <n-form-item label="JSON Path">
                <n-input v-model:value="assertJsonPath" placeholder="例如 $.data.id" />
              </n-form-item>
              <n-form-item label="期望值">
                <n-auto-complete
                  v-model:value="assertJsonExpected"
                  :options="variableAutoOptions(assertJsonExpected)"
                  placeholder='例如 123 或 "ok"'
                />
              </n-form-item>
            </div>
          </div>
        </n-form>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showEditor = false">取消</n-button>
            <n-button type="primary" :loading="saving" @click="saveCase">保存</n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>

    <n-modal v-model:show="showRunModal" preset="card" title="接口调试" class="api-test-run-modal">
      <n-spin :show="runDetailLoading">
        <div class="api-test-run-content">
          <section class="api-test-run-section">
            <div class="api-test-run-section__title">
              <span>请求配置</span>
              <n-button
                size="small"
                secondary
                :disabled="!runTargetDetail"
                @click="copyCurlCommand"
              >
                <template #icon><span class="i-carbon-copy" /></template>
                复制 cURL
              </n-button>
            </div>
            <div v-if="runDisplayCase" class="api-test-run-meta">
              <div>
                <span>接口名称</span>
                <strong>{{ runDisplayCase.name }}</strong>
              </div>
              <div>
                <span>请求方式</span>
                <strong>{{ runDisplayCase.method }}</strong>
              </div>
              <div>
                <span>所属模块</span>
                <strong>{{ runDisplayCase.module_name || "-" }}</strong>
              </div>
              <div>
                <span>环境</span>
                <strong>{{ runDisplayCase.environment_name || "自定义 URL" }}</strong>
              </div>
              <div>
                <span>Base URL</span>
                <strong>{{ runDisplayBaseUrl || "-" }}</strong>
              </div>
              <div>
                <span>Path</span>
                <strong>{{ runDisplayPath || "-" }}</strong>
              </div>
            </div>

            <div v-if="runTargetDetail" class="api-test-run-config-grid">
              <div class="api-test-preview-block">
                <div class="api-test-preview-block__title">参数</div>
                <div v-if="runParamPreviewRows.length" class="api-test-preview-table">
                  <div v-for="row in runParamPreviewRows" :key="row.key" class="api-test-preview-row">
                    <span>{{ row.key }}</span>
                    <code>{{ row.value }}</code>
                  </div>
                </div>
                <n-text v-else depth="3">无</n-text>
              </div>
              <div class="api-test-preview-block">
                <div class="api-test-preview-block__title">请求头</div>
                <div v-if="runHeaderPreviewRows.length" class="api-test-preview-table">
                  <div v-for="row in runHeaderPreviewRows" :key="row.key" class="api-test-preview-row">
                    <span>{{ row.key }}</span>
                    <code>{{ row.value }}</code>
                  </div>
                </div>
                <n-text v-else depth="3">无</n-text>
              </div>
              <div class="api-test-preview-block api-test-preview-block--wide">
                <div class="api-test-preview-block__title">请求体</div>
                <n-code :code="runRequestBodyPreview" :language="runRequestBodyLanguage" word-wrap />
              </div>
              <div class="api-test-preview-block api-test-preview-block--wide">
                <div class="api-test-preview-block__title">断言</div>
                <div v-if="runAssertionPreviewRows.length" class="api-test-preview-table">
                  <div
                    v-for="(row, index) in runAssertionPreviewRows"
                    :key="`${row.key}-${index}`"
                    class="api-test-preview-row"
                  >
                    <span>{{ row.key }}</span>
                    <code>{{ row.value }}</code>
                  </div>
                </div>
                <n-text v-else depth="3">无</n-text>
              </div>
            </div>
          </section>

          <section class="api-test-run-section">
            <div class="api-test-run-section__title">执行设置</div>
            <n-form label-placement="top" class="api-test-run-controls">
              <n-form-item label="临时覆盖 Base URL（可选）">
                <n-input v-model:value="runBaseUrlOverride" placeholder="留空则使用 API 保存的环境 URL 或自定义 URL" />
              </n-form-item>
              <n-form-item label="超时时间">
                <n-input-number v-model:value="runTimeout" :min="1" :max="60" />
              </n-form-item>
            </n-form>
            <n-space justify="end">
              <n-button @click="showRunModal = false">关闭</n-button>
              <n-button type="primary" :loading="running" @click="runSelectedCase">
                <template #icon><span class="i-carbon-play-filled-alt" /></template>
                执行
              </n-button>
            </n-space>
          </section>

          <section class="api-test-run-section">
            <div class="api-test-run-section__title">
              <span>响应数据</span>
              <n-button
                v-if="runResult"
                size="small"
                secondary
                @click="copyResponseBody"
              >
                <template #icon><span class="i-carbon-copy" /></template>
                复制响应体
              </n-button>
            </div>
            <n-spin :show="running">
              <div v-if="running" class="api-test-run-waiting">
                正在执行接口请求，请稍候...
              </div>
              <div v-else-if="runResult" class="api-test-run-result">
                <div class="api-test-run-result__summary">
                  <n-tag :type="runResult.passed ? 'success' : 'error'">
                    {{ runResult.passed ? "通过" : "未通过" }}
                  </n-tag>
                  <span>状态码：{{ runResult.status_code ?? "-" }}</span>
                  <span>耗时：{{ runResult.elapsed_ms }} ms</span>
                  <span>实际 URL：{{ runResult.request_url }}</span>
                </div>
                <n-alert v-if="runResult.error" type="error" class="mt-3">
                  {{ runResult.error }}
                </n-alert>
                <div v-if="runResult.assertions.length > 0" class="api-test-run-result__assertions">
                  <div
                    v-for="(item, idx) in runResult.assertions"
                    :key="idx"
                    class="api-test-run-result__assertion"
                  >
                    <n-tag size="small" :type="item.passed ? 'success' : 'error'">
                      {{ item.passed ? "PASS" : "FAIL" }}
                    </n-tag>
                    <div class="api-test-run-result__assertion-body">
                      <span>{{ item.reason }}</span>
                      <div v-if="!item.passed" class="api-test-run-result__assertion-values">
                        <span>
                          期望：
                          <code>{{ formatAssertionValue(item.expected) }}</code>
                        </span>
                        <span>
                          实际：
                          <code>{{ formatAssertionValue(item.actual) }}</code>
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
                <n-tabs type="line" animated>
                  <n-tab-pane name="body" tab="响应体">
                    <n-code :code="formattedResponseBody" :language="responseBodyLanguage" word-wrap />
                  </n-tab-pane>
                  <n-tab-pane name="headers" tab="响应头">
                    <n-code :code="formattedResponseHeaders" language="json" word-wrap />
                  </n-tab-pane>
                </n-tabs>
              </div>
              <app-empty
                v-else
                icon="i-carbon-play-filled-alt"
                title="等待执行"
                description="点击执行后，响应体会在当前弹窗下方展示。"
              />
            </n-spin>
          </section>
        </div>
      </n-spin>
    </n-modal>

    <n-modal
      v-model:show="showBatchReport"
      preset="card"
      title="API 批量执行报告"
      class="api-test-batch-report-modal"
    >
      <div v-if="batchReport" class="api-test-batch-report">
        <div class="api-test-batch-summary">
          <div>
            <span>总数</span>
            <strong>{{ batchReport.total }}</strong>
          </div>
          <div>
            <span>通过</span>
            <strong class="text-success">{{ batchReport.passed }}</strong>
          </div>
          <div>
            <span>失败</span>
            <strong class="text-error">{{ batchReport.failed }}</strong>
          </div>
          <div>
            <span>通过率</span>
            <strong>{{ formatPercent(batchReport.passed, batchReport.total) }}</strong>
          </div>
          <div>
            <span>总耗时</span>
            <strong>{{ batchReport.elapsed_ms }} ms</strong>
          </div>
          <div>
            <span>范围</span>
            <strong>{{ batchReport.scope === "module" ? "当前模块" : "勾选 API" }}</strong>
          </div>
        </div>
        <div class="api-test-batch-actions">
          <n-button secondary @click="downloadBatchReport">
            <template #icon><span class="i-carbon-download" /></template>
            下载报告 CSV
          </n-button>
        </div>
        <n-data-table
          :columns="batchReportColumns"
          :data="batchReport.items"
          :row-key="(row: ApiTestBatchRunItem) => row.case_id"
          :row-props="batchReportRowProps"
          :bordered="false"
          :scroll-x="1360"
          striped
        />
      </div>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from "vue";
import {
  NAlert,
  NAutoComplete,
  NButton,
  NCode,
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
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  NText,
  NTooltip,
  useMessage,
} from "naive-ui";
import type { DataTableColumns, DataTableRowKey, SelectOption } from "naive-ui";
import PageHeader from "@/components/common/PageHeader.vue";
import AppEmpty from "@/components/common/AppEmpty.vue";
import ApiModuleTree from "@/components/api-testing/ApiModuleTree.vue";
import {
  createApiTestApi,
  deleteApiTestApi,
  getApiTestApi,
  getApiTestModuleTreeApi,
  listApiTestEnvironmentsApi,
  listApiTestEnvironmentVariablesApi,
  listApiTestsApi,
  runApiTestApi,
  runApiTestsBatchApi,
  updateApiTestApi,
} from "@/services/apiTesting";
import type {
  ApiAssertion,
  ApiAssertionResult,
  ApiBodyType,
  ApiMethod,
  ApiRenderedRequestConfig,
  ApiTestBatchRunItem,
  ApiTestBatchRunResult,
  ApiTestCaseDetail,
  ApiTestCaseListItem,
  ApiTestEnvironment,
  ApiTestEnvironmentVariable,
  ApiTestModuleTreeNode,
  ApiTestRunResult,
} from "@/services/apiTesting";
import { useProjectStore } from "@/stores/project";

defineOptions({ name: "ApiTestView" });

const projectStore = useProjectStore();
const message = useMessage();
const moduleTreeRef = ref<InstanceType<typeof ApiModuleTree>>();
const moduleSidebarCollapsed = ref(false);
const selectedModuleId = ref<string | null>(null);
const moduleNodes = ref<ApiTestModuleTreeNode[]>([]);
const environments = ref<ApiTestEnvironment[]>([]);
const environmentVariables = ref<Record<string, ApiTestEnvironmentVariable[]>>({});
const items = ref<ApiTestCaseListItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const loading = ref(false);
const saving = ref(false);
const checkedRowKeys = ref<DataTableRowKey[]>([]);
const searchText = ref("");
let searchTimer: number | undefined;
let kvRowSeed = 0;

interface KeyValueRow {
  id: number;
  key: string;
  value: string;
}

interface PreviewRow {
  key: string;
  value: string;
}

const methodOptions = ["GET", "POST", "PUT", "PATCH", "DELETE"].map((value) => ({
  label: value,
  value,
}));

const moduleOptions = computed<SelectOption[]>(() => flattenModules(moduleNodes.value));
const environmentOptions = computed<SelectOption[]>(() =>
  environments.value.map((item) => ({
    label: `${item.name} - ${item.base_url}`,
    value: item.id,
  })),
);

const showEditor = ref(false);
const editingId = ref<string | null>(null);
const editorTab = ref("params");
const form = ref({
  module_id: "",
  name: "",
  method: "GET" as ApiMethod,
  url_mode: "environment" as "environment" | "custom",
  environment_id: "",
  base_url: "",
  path: "",
  body_type: "none" as ApiBodyType,
});
const paramRows = ref<KeyValueRow[]>([createKeyValueRow()]);
const headerRows = ref<KeyValueRow[]>([createKeyValueRow("Content-Type", "application/json")]);
const bodyJsonText = ref("{}");
const bodyText = ref("");
const assertStatusCode = ref<number | null>(200);
const assertBodyContains = ref("");
const assertJsonPath = ref("");
const assertJsonExpected = ref("");

const showRunModal = ref(false);
const runCaseId = ref<string | null>(null);
const runTarget = ref<ApiTestCaseListItem | null>(null);
const runTargetDetail = ref<ApiTestCaseDetail | null>(null);
const runSnapshotRequest = ref<ApiRenderedRequestConfig | null>(null);
const runDetailLoading = ref(false);
const runBaseUrlOverride = ref("");
const runTimeout = ref(15);
const running = ref(false);
const runResult = ref<ApiTestRunResult | null>(null);
const showBatchReport = ref(false);
const batchRunning = ref(false);
const batchReport = ref<ApiTestBatchRunResult | null>(null);

const runDisplayCase = computed(() => runTargetDetail.value ?? runTarget.value);
const runRenderedRequest = computed(() => runSnapshotRequest.value ?? runTargetDetail.value?.rendered_request ?? null);
const runDisplayBaseUrl = computed(
  () => runRenderedRequest.value?.base_url ?? runDisplayCase.value?.base_url ?? "",
);
const runDisplayPath = computed(
  () => runRenderedRequest.value?.path ?? runDisplayCase.value?.path ?? runDisplayCase.value?.url ?? "",
);
const runParamPreviewRows = computed(() =>
  objectToPreviewRows(runRenderedRequest.value?.query_params ?? runTargetDetail.value?.query_params ?? {}),
);
const runHeaderPreviewRows = computed(() =>
  objectToPreviewRows(runRenderedRequest.value?.headers ?? runTargetDetail.value?.headers ?? {}),
);
const runAssertionPreviewRows = computed(() =>
  assertionPreviewRows(runRenderedRequest.value?.assertions ?? runTargetDetail.value?.assertions ?? []),
);
const runRequestBodyPreview = computed(() =>
  formatRequestBody(runRenderedRequest.value ?? runTargetDetail.value),
);
const runRequestBodyLanguage = computed(
  () => (runRenderedRequest.value ?? runTargetDetail.value)?.body_type === "text" ? "text" : "json",
);
const formattedResponseBody = computed(() => formatResponseBody(runResult.value).code);
const responseBodyLanguage = computed(() => formatResponseBody(runResult.value).language);
const formattedResponseHeaders = computed(() => stringifyJson(runResult.value?.response_headers ?? {}));
const selectedBatchCount = computed(() => checkedRowKeys.value.length);
const activeEnvironmentVariables = computed(() => {
  if (form.value.url_mode !== "environment" || !form.value.environment_id) return [];
  return environmentVariables.value[form.value.environment_id] || [];
});
const batchReportColumns: DataTableColumns<ApiTestBatchRunItem> = [
  {
    title: "API 名称",
    key: "name",
    minWidth: 220,
    ellipsis: { tooltip: true },
  },
  {
    title: "方法",
    key: "method",
    width: 82,
    render(row) {
      return h(NTag, { size: "small", type: methodTagType(row.method) }, { default: () => row.method });
    },
  },
  {
    title: "环境",
    key: "environment_name",
    width: 140,
    render(row) {
      return row.environment_name || "自定义 URL";
    },
  },
  { title: "模块", key: "module_name", width: 140, ellipsis: { tooltip: true } },
  {
    title: "结果",
    key: "passed",
    width: 88,
    render(row) {
      return h(NTag, { size: "small", type: row.passed ? "success" : "error" }, {
        default: () => (row.passed ? "通过" : "失败"),
      });
    },
  },
  { title: "状态码", key: "status_code", width: 90 },
  { title: "耗时", key: "elapsed_ms", width: 90, render: (row) => `${row.elapsed_ms} ms` },
  {
    title: "断言",
    key: "assertions",
    width: 110,
    render(row) {
      return `${row.assertion_count - row.failed_assertion_count}/${row.assertion_count}`;
    },
  },
  { title: "请求 URL", key: "request_url", minWidth: 260, ellipsis: { tooltip: true } },
  { title: "失败原因", key: "error", minWidth: 220, ellipsis: { tooltip: true } },
];

const columns: DataTableColumns<ApiTestCaseListItem> = [
  { type: "selection", width: 48 },
  {
    title: "接口名称",
    key: "name",
    minWidth: 220,
    render(row) {
      return h(
        "span",
        {
          class: "api-test-name-text",
          role: "button",
          tabindex: 0,
          title: row.name,
          onClick: () => openEditDrawer(row.id),
          onKeydown: (event: KeyboardEvent) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openEditDrawer(row.id);
            }
          },
        },
        row.name,
      );
    },
  },
  {
    title: "方法",
    key: "method",
    width: 92,
    render(row) {
      return h(NTag, { size: "small", type: methodTagType(row.method) }, { default: () => row.method });
    },
  },
  {
    title: "环境",
    key: "environment_name",
    width: 150,
    render(row) {
      return row.environment_name || "自定义 URL";
    },
  },
  { title: "Base URL", key: "base_url", minWidth: 220, ellipsis: { tooltip: true } },
  { title: "Path", key: "path", minWidth: 220, ellipsis: { tooltip: true } },
  { title: "模块", key: "module_name", width: 150 },
  {
    title: "操作",
    key: "actions",
    width: 210,
    render(row) {
      return h(NSpace, { size: 6 }, () => [
        h(NButton, { size: "small", type: "primary", ghost: true, onClick: () => openRunModal(row) }, {
          default: () => "执行",
        }),
        h(NButton, { size: "small", onClick: () => openEditDrawer(row.id) }, { default: () => "编辑" }),
        h(
          NPopconfirm,
          { onPositiveClick: () => deleteCase(row.id) },
          {
            trigger: () => h(NButton, { size: "small", type: "error", ghost: true }, { default: () => "删除" }),
            default: () => `确认删除 API「${row.name}」？`,
          },
        ),
      ]);
    },
  },
];

function methodTagType(method: ApiMethod) {
  if (method === "GET") return "success";
  if (method === "POST") return "info";
  if (method === "DELETE") return "error";
  return "warning";
}

function handleCheckedRowKeys(keys: DataTableRowKey[]) {
  checkedRowKeys.value = keys;
}

function batchReportRowProps(row: ApiTestBatchRunItem) {
  return {
    class: "api-test-batch-report-row",
    onClick: () => openBatchRunModal(row),
  };
}

function handleModuleSelect(moduleId: string | null) {
  selectedModuleId.value = moduleId;
  checkedRowKeys.value = [];
  page.value = 1;
  fetchCases();
}

function handleShowAll() {
  selectedModuleId.value = null;
  moduleTreeRef.value?.clearSelection();
  checkedRowKeys.value = [];
  page.value = 1;
  fetchCases();
}

function handleModuleTreeChanged(nodes: ApiTestModuleTreeNode[]) {
  moduleNodes.value = nodes;
}

function debouncedFetch() {
  if (searchTimer) window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    page.value = 1;
    fetchCases();
  }, 250);
}

async function fetchCases() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  loading.value = true;
  try {
    const res = await listApiTestsApi(projectId, {
      page: page.value,
      page_size: pageSize,
      module_id: selectedModuleId.value,
      search: searchText.value.trim() || undefined,
    });
    if (res.success) {
      items.value = res.data.items;
      total.value = res.data.total;
      const currentIds = new Set(res.data.items.map((item) => item.id));
      checkedRowKeys.value = checkedRowKeys.value.filter((id) => currentIds.has(String(id)));
    }
  } catch {
    message.error("获取 API 列表失败");
  } finally {
    loading.value = false;
  }
}

async function fetchModules() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) {
    moduleNodes.value = [];
    return;
  }
  const res = await getApiTestModuleTreeApi(projectId);
  if (res.success) moduleNodes.value = res.data;
}

async function fetchEnvironments() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) {
    environments.value = [];
    return;
  }
  const res = await listApiTestEnvironmentsApi(projectId);
  if (res.success) environments.value = res.data;
}

async function fetchEnvironmentVariables(environmentId: string) {
  if (!environmentId || environmentVariables.value[environmentId]) return;
  try {
    const res = await listApiTestEnvironmentVariablesApi(environmentId);
    if (res.success) {
      environmentVariables.value = {
        ...environmentVariables.value,
        [environmentId]: res.data,
      };
    }
  } catch {
    message.error("获取环境变量失败");
  }
}

function openCreateDrawer() {
  editingId.value = null;
  const defaultEnvironmentId = environments.value[0]?.id || "";
  form.value = {
    module_id: selectedModuleId.value || "",
    name: "",
    method: "GET",
    url_mode: defaultEnvironmentId ? "environment" : "custom",
    environment_id: defaultEnvironmentId,
    base_url: "",
    path: "",
    body_type: "json",
  };
  editorTab.value = "params";
  paramRows.value = [createKeyValueRow()];
  headerRows.value = [createKeyValueRow("Content-Type", "application/json")];
  bodyJsonText.value = "{}";
  bodyText.value = "";
  assertStatusCode.value = 200;
  assertBodyContains.value = "";
  assertJsonPath.value = "";
  assertJsonExpected.value = "";
  if (defaultEnvironmentId) fetchEnvironmentVariables(defaultEnvironmentId);
  showEditor.value = true;
}

async function openEditDrawer(id: string) {
  try {
    const res = await getApiTestApi(id);
    if (!res.success) return;
    const item = res.data;
    editingId.value = id;
    form.value = {
      module_id: item.module_id,
      name: item.name,
      method: item.method,
      url_mode: item.environment_id ? "environment" : "custom",
      environment_id: item.environment_id || "",
      base_url: item.environment_id ? "" : item.base_url || splitLegacyUrl(item.url).base_url,
      path: item.path || splitLegacyUrl(item.url).path,
      body_type: item.body_type,
    };
    editorTab.value = "params";
    if (item.environment_id) fetchEnvironmentVariables(item.environment_id);
    headerRows.value = objectToKeyValueRows(item.headers);
    paramRows.value = objectToKeyValueRows(item.query_params);
    bodyJsonText.value = stringifyJson(item.body_json ?? {});
    bodyText.value = item.body_text ?? "";
    hydrateAssertions(item);
    showEditor.value = true;
  } catch {
    message.error("获取 API 详情失败");
  }
}

function hydrateAssertions(item: ApiTestCaseDetail) {
  const status = item.assertions.find((it) => it.type === "status_code");
  const contains = item.assertions.find((it) => it.type === "body_contains");
  const jsonPath = item.assertions.find((it) => it.type === "json_path_eq");
  assertStatusCode.value = typeof status?.expected === "number" ? status.expected : null;
  assertBodyContains.value = contains?.expected ? String(contains.expected) : "";
  assertJsonPath.value = jsonPath?.path ?? "";
  assertJsonExpected.value = jsonPath ? stringifyExpected(jsonPath.expected) : "";
}

async function saveCase() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  const payload = buildPayload();
  if (!payload) return;
  saving.value = true;
  try {
    if (editingId.value) {
      await updateApiTestApi(editingId.value, payload);
      message.success("API 已更新");
    } else {
      await createApiTestApi(projectId, payload);
      message.success("API 已创建");
    }
    showEditor.value = false;
    await Promise.all([fetchCases(), fetchModules(), moduleTreeRef.value?.fetchModules()]);
  } catch {
    message.error("保存 API 失败，请确认 Base URL 是 http/https 完整地址，Path 以 / 开头");
  } finally {
    saving.value = false;
  }
}

function buildPayload() {
  if (!form.value.module_id) {
    message.warning("请选择所属模块");
    return null;
  }
  if (!form.value.name.trim()) {
    message.warning("请输入 API 名称");
    return null;
  }
  if (form.value.url_mode === "environment" && !form.value.environment_id) {
    message.warning("请选择环境 URL");
    return null;
  }
  if (form.value.url_mode === "custom" && !form.value.base_url.trim()) {
    message.warning("请输入 Base URL");
    return null;
  }
  if (!form.value.path.trim()) {
    message.warning("请输入 Path 路径");
    return null;
  }
  const headers = rowsToObject(headerRows.value, "请求头");
  if (headers === null) return null;
  const query = rowsToObject(paramRows.value, "参数");
  if (query === null) return null;
  const assertions = buildAssertions();
  const payload = {
    module_id: form.value.module_id,
    environment_id: form.value.url_mode === "environment" ? form.value.environment_id : null,
    name: form.value.name.trim(),
    method: form.value.method,
    base_url: form.value.url_mode === "custom" ? form.value.base_url.trim() : null,
    path: form.value.path.trim(),
    headers,
    query_params: query,
    body_type: form.value.body_type,
    body_json: null as unknown,
    body_text: null as string | null,
    assertions,
  };
  if (form.value.body_type === "json") {
    const body = parseAnyJson(bodyJsonText.value, "Body JSON");
    if (body === undefined) return null;
    payload.body_json = body;
  } else if (form.value.body_type === "text") {
    payload.body_text = bodyText.value;
  }
  return payload;
}

function buildAssertions(): ApiAssertion[] {
  const out: ApiAssertion[] = [];
  if (assertStatusCode.value) {
    out.push({ type: "status_code", expected: assertStatusCode.value });
  }
  if (assertBodyContains.value.trim()) {
    out.push({ type: "body_contains", expected: assertBodyContains.value.trim() });
  }
  if (assertJsonPath.value.trim()) {
    out.push({
      type: "json_path_eq",
      path: assertJsonPath.value.trim(),
      expected: parseExpected(assertJsonExpected.value),
    });
  }
  return out;
}

async function deleteCase(id: string) {
  try {
    await deleteApiTestApi(id);
    message.success("API 已删除");
    if (items.value.length === 1 && page.value > 1) page.value -= 1;
    await fetchCases();
  } catch {
    message.error("删除 API 失败");
  }
}

async function openRunModal(row: ApiTestCaseListItem) {
  await openRunModalById(row.id, row, null);
}

async function openBatchRunModal(row: ApiTestBatchRunItem) {
  await openRunModalById(row.case_id, null, row);
}

async function openRunModalById(
  caseId: string,
  fallback: ApiTestCaseListItem | null,
  snapshot: ApiTestBatchRunItem | null,
) {
  runCaseId.value = caseId;
  runTarget.value = fallback;
  runTargetDetail.value = null;
  runSnapshotRequest.value = snapshot?.rendered_request ?? null;
  runResult.value = snapshot?.run_result ?? null;
  runBaseUrlOverride.value = "";
  showRunModal.value = true;
  runDetailLoading.value = true;
  try {
    const res = await getApiTestApi(caseId);
    if (res.success) {
      runTargetDetail.value = res.data;
      runTarget.value = res.data;
    }
  } catch {
    message.error("获取接口配置失败");
  } finally {
    runDetailLoading.value = false;
  }
}

async function runSelectedCase() {
  const caseId = runTargetDetail.value?.id ?? runCaseId.value ?? runTarget.value?.id;
  if (!caseId) return;
  running.value = true;
  try {
    const res = await runApiTestApi(caseId, {
      base_url: runBaseUrlOverride.value.trim() || null,
      timeout_seconds: runTimeout.value,
    });
    if (res.success) runResult.value = res.data;
  } catch {
    message.error("接口调试失败");
  } finally {
    running.value = false;
  }
}

async function runSelectedBatch() {
  const ids = checkedRowKeys.value.map((item) => String(item));
  if (ids.length === 0) {
    message.warning("请先勾选要执行的 API");
    return;
  }
  await executeBatch({ case_ids: ids });
}

async function runCurrentModuleBatch() {
  if (!selectedModuleId.value) {
    message.warning("请先选择左侧模块");
    return;
  }
  await executeBatch({ module_id: selectedModuleId.value, include_descendants: true });
}

async function executeBatch(payload: { case_ids?: string[]; module_id?: string; include_descendants?: boolean }) {
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  batchRunning.value = true;
  try {
    const res = await runApiTestsBatchApi(projectId, {
      ...payload,
      timeout_seconds: 15,
    });
    if (res.success) {
      batchReport.value = res.data;
      showBatchReport.value = true;
      message.success(`批量执行完成：通过 ${res.data.passed}，失败 ${res.data.failed}`);
    }
  } catch {
    message.error("批量执行失败，请确认所选 API 配置完整且数量不超过限制");
  } finally {
    batchRunning.value = false;
  }
}

function downloadBatchReport() {
  if (!batchReport.value) return;
  const filename = `api-batch-report-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`;
  const csv = toCsv([
    ["API名称", "方法", "环境", "模块", "是否通过", "状态码", "耗时ms", "断言总数", "失败断言", "请求URL", "失败原因"],
    ...batchReport.value.items.map((item) => [
      item.name,
      item.method,
      item.environment_name || "自定义 URL",
      item.module_name || "",
      item.passed ? "通过" : "失败",
      item.status_code ?? "",
      item.elapsed_ms,
      item.assertion_count,
      item.failed_assertion_count,
      item.request_url,
      item.error || "",
    ]),
  ]);
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function toCsv(rows: unknown[][]): string {
  return rows
    .map((row) =>
      row
        .map((cell) => {
          const text = String(cell ?? "");
          return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
        })
        .join(","),
    )
    .join("\n");
}

function formatPercent(value: number, totalValue: number): string {
  if (!totalValue) return "0%";
  return `${((value / totalValue) * 100).toFixed(1)}%`;
}

async function copyResponseBody() {
  if (!runResult.value) return;
  const text = formattedResponseBody.value === "(empty)" ? "" : formattedResponseBody.value;
  await copyTextToClipboard(text, "响应体已复制");
}

async function copyCurlCommand() {
  if (!runTargetDetail.value) {
    message.warning("接口配置还未加载完成");
    return;
  }
  await copyTextToClipboard(
    buildCurlCommand(runTargetDetail.value, runRenderedRequest.value),
    "cURL 请求已复制",
  );
}

async function copyTextToClipboard(text: string, successText: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
    message.success(successText);
  } catch {
    message.error("复制失败，请检查浏览器剪贴板权限");
  }
}

function variableAutoOptions(value: string) {
  if (form.value.url_mode !== "environment" || !form.value.environment_id) return [];
  const text = String(value || "");
  const start = text.lastIndexOf("{{");
  if (start < 0) return [];
  if (text.indexOf("}}", start) >= 0) return [];
  const keyword = text.slice(start + 2).trim().toLowerCase();
  return activeEnvironmentVariables.value
    .filter((item) => {
      if (!keyword) return true;
      return (
        item.key.toLowerCase().includes(keyword) ||
        item.value.toLowerCase().includes(keyword) ||
        (item.description || "").toLowerCase().includes(keyword)
      );
    })
    .map((item) => ({
      label: templateVariable(item.key),
      value: `${text.slice(0, start)}${templateVariable(item.key)}`,
    }));
}

function templateVariable(key: string) {
  return `{{${key}}}`;
}

function createKeyValueRow(key = "", value = ""): KeyValueRow {
  kvRowSeed += 1;
  return { id: kvRowSeed, key, value };
}

function addKeyValueRow(rows: KeyValueRow[]) {
  rows.push(createKeyValueRow());
}

function removeKeyValueRow(rows: KeyValueRow[], index: number) {
  rows.splice(index, 1);
  if (rows.length === 0) rows.push(createKeyValueRow());
}

function objectToKeyValueRows(value: Record<string, unknown> | null | undefined) {
  const rows = Object.entries(value ?? {}).map(([key, item]) =>
    createKeyValueRow(key, stringifyKeyValue(item)),
  );
  if (rows.length > 0) return rows;
  return [createKeyValueRow()];
}

function rowsToObject(rows: KeyValueRow[], label: string): Record<string, string> | null {
  const out: Record<string, string> = {};
  const seen = new Set<string>();
  for (const row of rows) {
    const key = row.key.trim();
    const value = row.value;
    if (!key && !value.trim()) continue;
    if (!key) {
      message.warning(`${label}存在未填写 Key 的行`);
      return null;
    }
    if (seen.has(key)) {
      message.warning(`${label}存在重复 Key：${key}`);
      return null;
    }
    seen.add(key);
    out[key] = value;
  }
  return out;
}

function stringifyKeyValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function objectToPreviewRows(value: Record<string, unknown>): PreviewRow[] {
  return Object.entries(value).map(([key, item]) => ({ key, value: stringifyKeyValue(item) }));
}

function assertionPreviewRows(assertions: ApiAssertion[]): PreviewRow[] {
  return assertions.map((item) => {
    if (item.type === "status_code") return { key: "状态码", value: stringifyKeyValue(item.expected) };
    if (item.type === "body_contains") return { key: "响应包含", value: stringifyKeyValue(item.expected) };
    return {
      key: item.path ? `JSON Path ${item.path}` : "JSON Path",
      value: stringifyKeyValue(item.expected),
    };
  });
}

function formatRequestBody(item: Pick<ApiTestCaseDetail, "body_type" | "body_json" | "body_text"> | null): string {
  if (!item || item.body_type === "none") return "(无)";
  if (item.body_type === "text") return item.body_text || "";
  return stringifyJson(item.body_json ?? {});
}

function formatResponseBody(result: ApiTestRunResult | null): { code: string; language: string } {
  if (!result) return { code: "", language: "json" };
  if (result.response_json !== null && result.response_json !== undefined) {
    return { code: stringifyJson(result.response_json), language: "json" };
  }
  const raw = result.response_body || "";
  if (!raw) return { code: "(empty)", language: "text" };
  try {
    return { code: JSON.stringify(JSON.parse(raw), null, 2), language: "json" };
  } catch {
    return { code: raw, language: "text" };
  }
}

function formatAssertionValue(value: ApiAssertionResult["actual"] | ApiAssertionResult["expected"]): string {
  if (value === undefined) return "未返回";
  if (value === null) return "null";
  if (typeof value === "string") return value || '""';
  return JSON.stringify(value);
}

function buildCurlCommand(item: ApiTestCaseDetail, rendered: ApiRenderedRequestConfig | null): string {
  const request = rendered ?? item;
  const parts = ["curl", "-X", shellQuote(item.method), shellQuote(buildCurlUrl(item, rendered))];
  for (const [key, value] of Object.entries(request.headers ?? {})) {
    if (!key.trim()) continue;
    parts.push("-H", shellQuote(`${key}: ${stringifyKeyValue(value)}`));
  }
  if (request.body_type === "json") {
    parts.push("--data-raw", shellQuote(JSON.stringify(request.body_json ?? {})));
  } else if (request.body_type === "text" && request.body_text) {
    parts.push("--data-raw", shellQuote(request.body_text));
  }
  return parts.map((part, index) => (index === 0 ? part : `  ${part}`)).join(" \\\n");
}

function buildCurlUrl(item: ApiTestCaseDetail, rendered: ApiRenderedRequestConfig | null): string {
  const queryParams = rendered?.query_params ?? item.query_params;
  const rawUrl = (rendered?.path || item.path || item.url).trim();
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    const base = runBaseUrlOverride.value.trim() || rendered?.base_url || item.base_url || "";
    if (!base) return appendQueryParams(rawUrl, queryParams);
    url = new URL(rawUrl.replace(/^\/+/, ""), ensureTrailingSlash(base));
  }
  for (const [key, value] of Object.entries(queryParams ?? {})) {
    if (!key.trim()) continue;
    url.searchParams.set(key, stringifyKeyValue(value));
  }
  return url.toString();
}

function splitLegacyUrl(raw: string): { base_url: string; path: string } {
  try {
    const url = new URL(raw);
    return {
      base_url: `${url.protocol}//${url.host}`,
      path: `${url.pathname || "/"}${url.search}`,
    };
  } catch {
    return { base_url: "", path: raw || "" };
  }
}

function appendQueryParams(rawUrl: string, params: Record<string, unknown>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (!key.trim()) continue;
    query.set(key, stringifyKeyValue(value));
  }
  if (!query.toString()) return rawUrl;
  return `${rawUrl}${rawUrl.includes("?") ? "&" : "?"}${query.toString()}`;
}

function ensureTrailingSlash(value: string): string {
  return value.endsWith("/") ? value : `${value}/`;
}

function shellQuote(value: string): string {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function parseAnyJson(text: string, label: string): unknown | undefined {
  const raw = text.trim();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    try {
      return JSON.parse(normalizeJsonTemplatePlaceholders(raw));
    } catch {
      message.warning(`${label} 格式不正确`);
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

function parseExpected(text: string): unknown {
  const raw = text.trim();
  if (!raw) return "";
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function stringifyExpected(value: unknown): string {
  return typeof value === "string" ? value : stringifyJson(value);
}

function stringifyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function flattenModules(nodes: ApiTestModuleTreeNode[], prefix = ""): SelectOption[] {
  const out: SelectOption[] = [];
  for (const node of nodes) {
    const label = prefix ? `${prefix} / ${node.name}` : node.name;
    out.push({ label, value: node.id });
    out.push(...flattenModules(node.children, label));
  }
  return out;
}

watch(() => projectStore.currentProjectId, async () => {
  selectedModuleId.value = null;
  environmentVariables.value = {};
  page.value = 1;
  await Promise.all([fetchModules(), fetchEnvironments(), fetchCases()]);
}, { immediate: true });

watch(
  () => form.value.environment_id,
  (environmentId) => {
    if (environmentId) fetchEnvironmentVariables(environmentId);
  },
);

onMounted(() => {
  fetchModules();
  fetchEnvironments();
});
</script>

<style scoped>
.api-test-page {
  height: 100%;
}

.api-test-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
  min-height: calc(100vh - 170px);
}

.api-test-layout--side-collapsed {
  grid-template-columns: 52px minmax(0, 1fr);
}

.api-test-layout__side,
.api-test-layout__main {
  min-width: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--bg-card);
}

.api-test-layout__side {
  overflow: hidden;
}

.api-test-layout__side--collapsed {
  min-width: 52px;
}

.api-test-layout__side-header,
.api-test-toolbar,
.api-test-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
}

.api-test-layout__side-rail {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 8px;
}

.api-test-layout__side-title,
.api-test-layout__side-actions,
.api-test-run-result__summary,
.api-test-run-result__assertion {
  display: flex;
  align-items: center;
  gap: 8px;
}

.api-test-layout__side-body {
  padding: 10px;
}

.api-test-layout__main {
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.api-test-toolbar__search {
  width: min(360px, 50vw);
}

.api-test-toolbar__actions {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.api-test-table {
  min-width: 0;
  flex: 1;
  padding: 12px;
  overflow: hidden;
}

.api-test-data-table {
  max-width: 100%;
}

.api-test-pager {
  border-top: 1px solid var(--border-subtle);
  border-bottom: 0;
}

.api-test-page :deep(.api-test-name-text) {
  min-width: 0;
  max-width: 100%;
  display: inline-block;
  padding: 0;
  border: 0;
  color: var(--text-primary);
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-weight: 500;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition:
    color var(--duration-fast) var(--easing-standard);
}

.api-test-page :deep(.api-test-name-text:hover),
.api-test-page :deep(.api-test-name-text:focus-visible) {
  color: var(--brand-primary);
  outline: none;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.api-test-form-grid {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 12px;
}

.api-test-editor-tabs {
  margin-bottom: 16px;
}

.api-test-kv-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.api-test-kv-list__head,
.api-test-kv-row {
  display: grid;
  grid-template-columns: minmax(120px, 0.8fr) minmax(160px, 1.2fr) 36px;
  gap: 8px;
  align-items: center;
}

.api-test-kv-list__head {
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 600;
}

.api-test-assertions {
  border-top: 1px solid var(--border-subtle);
  padding-top: 14px;
}

.api-test-assertions__title {
  font-weight: 600;
  margin-bottom: 10px;
}

.api-test-run-modal {
  width: min(1040px, 94vw);
}

.api-test-batch-report-modal {
  width: min(1180px, 96vw);
}

.api-test-batch-report {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.api-test-batch-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.api-test-batch-summary div {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--bg-page-soft);
}

.api-test-batch-summary span {
  display: block;
  color: var(--text-tertiary);
  font-size: 12px;
}

.api-test-batch-summary strong {
  display: block;
  margin-top: 4px;
  font-size: 18px;
}

.api-test-batch-summary .text-success {
  color: var(--color-success, #16a34a);
}

.api-test-batch-summary .text-error {
  color: var(--error-color, #d03050);
}

.api-test-batch-actions {
  display: flex;
  justify-content: flex-end;
}

.api-test-page :deep(.api-test-batch-report-row) {
  cursor: pointer;
}

.api-test-page :deep(.api-test-batch-report-row:hover td) {
  background: var(--bg-page-soft);
}

.api-test-run-content,
.api-test-run-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.api-test-run-content {
  max-height: 78vh;
  overflow: auto;
  padding-right: 4px;
}

.api-test-run-section {
  padding: 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--bg-card);
}

.api-test-run-section__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-weight: 600;
}

.api-test-run-meta,
.api-test-run-controls,
.api-test-run-config-grid {
  display: grid;
  gap: 12px;
}

.api-test-run-meta {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.api-test-run-meta div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.api-test-run-meta span,
.api-test-preview-block__title {
  color: var(--text-tertiary);
  font-size: 12px;
}

.api-test-run-meta strong {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 13px;
}

.api-test-run-config-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.api-test-run-controls {
  grid-template-columns: minmax(0, 1fr) 140px;
}

.api-test-preview-block {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--bg-page-soft);
}

.api-test-preview-block--wide {
  grid-column: 1 / -1;
}

.api-test-preview-table {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}

.api-test-preview-row {
  display: grid;
  grid-template-columns: minmax(120px, 0.7fr) minmax(0, 1.3fr);
  gap: 10px;
  align-items: start;
}

.api-test-preview-row span {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text-secondary);
}

.api-test-preview-row code {
  min-width: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.api-test-run-waiting {
  min-height: 96px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
}

.api-test-run-result {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.api-test-run-result__summary {
  color: var(--text-secondary);
}

.api-test-run-result__assertions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.api-test-run-result__assertion {
  align-items: flex-start;
}

.api-test-run-result__assertion-body {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.api-test-run-result__assertion-values {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.api-test-run-result__assertion-values code {
  color: var(--text-primary);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 900px) {
  .api-test-layout {
    grid-template-columns: 1fr;
  }

  .api-test-form-grid {
    grid-template-columns: 1fr;
  }

  .api-test-kv-list__head,
  .api-test-kv-row,
  .api-test-batch-summary,
  .api-test-run-meta,
  .api-test-run-controls,
  .api-test-run-config-grid,
  .api-test-preview-row {
    grid-template-columns: 1fr;
  }

  .api-test-kv-list__head span:last-child {
    display: none;
  }
}
</style>
