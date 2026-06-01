<template>
  <n-drawer v-model:show="visible" :width="620" placement="right">
    <n-drawer-content :title="drawerTitle" closable>
      <n-spin :show="loadingDetail">
        <n-alert
          v-if="qualityWarnings.length > 0"
          type="warning"
          class="mb-3"
          :title="`步骤质量提示（${qualityWarnings.length} 条），用例已保存`"
        >
          <n-collapse>
            <n-collapse-item
              :title="`展开查看（按步骤号 / 类型分组）`"
              name="warnings"
            >
              <ul class="quality-warning-list">
                <li
                  v-for="(w, i) in qualityWarnings"
                  :key="i"
                  class="quality-warning-item"
                >
                  <n-tag size="small" type="warning" :bordered="false">
                    步骤 {{ w.step_number }} · {{ warningKindLabels[w.kind] || w.kind }}
                  </n-tag>
                  <span class="ml-2">{{ w.message }}</span>
                </li>
              </ul>
            </n-collapse-item>
          </n-collapse>
          <div class="mt-2 flex gap-2">
            <n-button size="small" @click="dismissWarningsAndClose">
              知道了，关闭
            </n-button>
            <n-button size="small" tertiary @click="qualityWarnings = []">
              继续编辑
            </n-button>
          </div>
        </n-alert>

        <n-form ref="formRef" :model="form" :rules="rules" label-placement="top">
          <n-form-item label="用例标题" path="title">
            <n-input
              v-model:value="form.title"
              placeholder="请输入用例标题"
              :maxlength="500"
            />
          </n-form-item>

          <div class="flex gap-4">
            <n-form-item label="优先级" path="priority" class="flex-1">
              <n-select
                v-model:value="form.priority"
                :options="priorityOptions"
              />
            </n-form-item>
            <n-form-item v-if="!isNew" label="状态" path="status" class="flex-1">
              <n-select
                v-model:value="form.status"
                :options="statusOptions"
              />
            </n-form-item>
            <n-form-item label="所属模块" class="flex-1">
              <n-tree-select
                v-model:value="form.module_id"
                :options="moduleTreeOptions"
                placeholder="选择模块（可选）"
                clearable
                default-expand-all
              />
            </n-form-item>
          </div>

          <n-form-item label="前置条件">
            <n-input
              v-model:value="form.precondition"
              type="textarea"
              placeholder="用例执行前需要满足的条件"
              :rows="2"
            />
          </n-form-item>

          <n-form-item v-if="hasTestDataPerm">
            <template #label>
              <span>
                默认物料集
                <n-tooltip>
                  <template #trigger>
                    <span
                      class="i-carbon-information-square ml-1 inline-block align-middle"
                    />
                  </template>
                  执行该用例时自动加载的物料集。与环境级 / 项目级 / 个人级 / 执行级按顺序合并；后面的覆盖前面的。Task 9.1 消费。
                </n-tooltip>
              </span>
            </template>
            <set-selector
              v-if="projectStore.currentProjectId"
              v-model="form.default_data_set_ids"
              :project-id="projectStore.currentProjectId"
              :testcase-ids="props.testcaseId ? [props.testcaseId] : undefined"
            />
            <n-alert v-else type="warning" :bordered="false" size="small">
              请先在顶栏选择项目
            </n-alert>
          </n-form-item>

          <n-form-item v-if="hasTestDataPerm">
            <template #label>
              <span>
                语义物料依赖
                <n-tooltip>
                  <template #trigger>
                    <span
                      class="i-carbon-information-square ml-1 inline-block align-middle"
                    />
                  </template>
                  描述该用例执行时需要的物料语义。实际执行仍按默认物料集和执行级选择合并，不会读取敏感值。
                </n-tooltip>
              </span>
            </template>
            <div class="required-data-editor">
              <div
                v-for="(item, idx) in form.required_test_data"
                :key="idx"
                class="required-data-row"
              >
                <n-select
                  v-model:value="item.semantic"
                  :options="semanticOptions"
                  filterable
                  tag
                  clearable
                  placeholder="语义，如 login_username"
                  class="required-data-row__semantic"
                />
                <n-checkbox v-model:checked="item.required">
                  必需
                </n-checkbox>
                <n-input
                  v-model:value="item.fallback"
                  clearable
                  placeholder="兜底（可选）"
                  class="required-data-row__fallback"
                />
                <n-input
                  v-model:value="item.description"
                  clearable
                  placeholder="说明（可选）"
                  class="required-data-row__desc"
                />
                <n-button
                  size="tiny"
                  quaternary
                  type="error"
                  @click="removeRequiredData(idx)"
                >
                  <template #icon><span class="i-carbon-close" /></template>
                </n-button>
              </div>
              <n-button size="tiny" @click="addRequiredData">
                <template #icon><span class="i-carbon-add" /></template>
                添加语义依赖
              </n-button>
            </div>
          </n-form-item>

          <!-- Steps -->
          <div class="mb-4">
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium">测试步骤</span>
              <n-button size="tiny" @click="addStep">
                <template #icon><span class="i-carbon-add" /></template>
                添加步骤
              </n-button>
            </div>

            <div v-if="form.steps.length === 0" class="text-center py-4 text-gray-400 text-sm">
              暂无步骤，点击"添加步骤"开始编写
            </div>

            <div v-for="(step, idx) in form.steps" :key="idx" class="mb-3 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
              <div class="flex items-center justify-between mb-2">
                <n-tag size="small" :bordered="false">步骤 {{ idx + 1 }}</n-tag>
                <n-button size="tiny" type="error" quaternary @click="removeStep(idx)">
                  <template #icon><span class="i-carbon-close" /></template>
                </n-button>
              </div>
              <n-input
                v-model:value="step.action"
                type="textarea"
                placeholder="操作步骤描述"
                :rows="2"
                class="mb-2"
              />
              <n-input
                v-model:value="step.expected_result"
                type="textarea"
                placeholder="预期结果（可选）"
                :rows="2"
              />
            </div>
          </div>
        </n-form>
      </n-spin>

      <template #footer>
        <div class="flex justify-end gap-2">
          <n-button @click="visible = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="handleSave">
            {{ isNew ? "创建" : "保存" }}
          </n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from "vue";
import {
  NAlert,
  NButton,
  NCheckbox,
  NCollapse,
  NCollapseItem,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NSpin,
  NTag,
  NTooltip,
  NTreeSelect,
  useMessage,
} from "naive-ui";
import type { FormRules, SelectOption, TreeSelectOption } from "naive-ui";
import {
  getTestcaseApi,
  createTestcaseApi,
  updateTestcaseApi,
  getModuleTreeApi,
} from "@/services/testcases";
import type { ModuleTreeNode, RequiredTestDataItem } from "@/services/testcases";
import { getSemanticCatalogApi } from "@/services/testData";
import { useProjectStore } from "@/stores/project";
import { usePermission } from "@/composables/usePermission";
import SetSelector from "@/components/test-data/SetSelector.vue";

const props = defineProps<{
  testcaseId: string | null;
}>();

const emit = defineEmits<{
  (e: "saved"): void;
}>();

const visible = defineModel<boolean>("show", { default: false });
const message = useMessage();
const projectStore = useProjectStore();
const { has } = usePermission();

const hasTestDataPerm = computed(() => has("test_data:view"));

const isNew = computed(() => !props.testcaseId);
const loadingDetail = ref(false);
const saving = ref(false);
const formRef = ref();
const currentDisplayId = ref<string>("");
const semanticOptions = ref<SelectOption[]>([]);

// Phase 15.5：保存接口返回的步骤质量警告（含未解析占位符 / 探索性词汇 /
// 过长复合步骤 / 公共反爬 host）。保存成功但有警告时，drawer 不立即关闭，
// 在顶部展开折叠区让作者看到具体哪一步该改。
type StepQualityWarning = {
  step_number: number;
  kind: string;
  message: string;
};
const qualityWarnings = ref<StepQualityWarning[]>([]);
const warningKindLabels: Record<string, string> = {
  unresolved_placeholder: "未解析占位符",
  exploratory_phrasing: "探索性词汇",
  step_too_long: "步骤过长",
  external_anti_bot_host: "公共反爬域名",
  empty_action: "动作为空",
};

const drawerTitle = computed(() => {
  if (isNew.value) return "新建测试用例";
  return currentDisplayId.value
    ? `编辑测试用例 · ${currentDisplayId.value}`
    : "编辑测试用例";
});

const form = reactive({
  title: "",
  priority: "medium",
  status: "active",
  module_id: null as string | null,
  precondition: "",
  steps: [] as Array<{ action: string; expected_result: string }>,
  default_data_set_ids: [] as string[],
  required_test_data: [] as RequiredTestDataItem[],
});

const rules: FormRules = {
  title: { required: true, message: "请输入用例标题", trigger: "blur" },
};

const priorityOptions = [
  { label: "高", value: "high" },
  { label: "中", value: "medium" },
  { label: "低", value: "low" },
];

const statusOptions = [
  { label: "有效", value: "active" },
  { label: "草稿", value: "draft" },
  { label: "废弃", value: "deprecated" },
];

const moduleTree = ref<ModuleTreeNode[]>([]);

function buildTreeSelectOptions(nodes: ModuleTreeNode[]): TreeSelectOption[] {
  return nodes.map((n) => ({
    key: n.id,
    label: n.name,
    children: n.children.length > 0 ? buildTreeSelectOptions(n.children) : undefined,
  }));
}

const moduleTreeOptions = computed(() => buildTreeSelectOptions(moduleTree.value));

async function fetchModuleTree() {
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  try {
    const res = await getModuleTreeApi(projectId);
    if (res.success) {
      moduleTree.value = res.data;
    }
  } catch {
    /* ignore */
  }
}

async function fetchSemanticCatalog() {
  if (!hasTestDataPerm.value) return;
  try {
    const res = await getSemanticCatalogApi();
    if (res.success) {
      semanticOptions.value = res.data.item_semantics.map((item) => ({
        label: `${item.label} · ${item.value}`,
        value: item.value,
      }));
    }
  } catch {
    semanticOptions.value = [];
  }
}

function resetForm() {
  form.title = "";
  form.priority = "medium";
  form.status = "active";
  form.module_id = null;
  form.precondition = "";
  form.steps = [];
  form.default_data_set_ids = [];
  form.required_test_data = [];
  currentDisplayId.value = "";
}

async function loadDetail(id: string) {
  loadingDetail.value = true;
  try {
    const res = await getTestcaseApi(id);
    if (res.success) {
      const tc = res.data;
      form.title = tc.title;
      form.priority = tc.priority;
      form.status = tc.status;
      form.module_id = tc.module_id;
      form.precondition = tc.precondition || "";
      form.steps = tc.steps.map((s) => ({
        action: s.action,
        expected_result: s.expected_result || "",
      }));
      form.default_data_set_ids = [...(tc.default_data_set_ids ?? [])];
      form.required_test_data = [...(tc.required_test_data ?? [])];
      currentDisplayId.value =
        tc.display_id ||
        (tc.case_no ? `TC-${String(tc.case_no).padStart(4, "0")}` : "");
    }
  } catch {
    message.error("获取用例详情失败");
  } finally {
    loadingDetail.value = false;
  }
}

function addStep() {
  form.steps.push({ action: "", expected_result: "" });
}

function removeStep(idx: number) {
  form.steps.splice(idx, 1);
}

function addRequiredData() {
  form.required_test_data.push({
    semantic: "",
    required: true,
    fallback: null,
    description: null,
  });
}

function removeRequiredData(idx: number) {
  form.required_test_data.splice(idx, 1);
}

function sanitizeRequiredTestData(): RequiredTestDataItem[] {
  const seen = new Set<string>();
  return form.required_test_data
    .map((item) => ({
      semantic: item.semantic.trim(),
      required: item.required !== false,
      fallback: item.fallback?.trim() || null,
      description: item.description?.trim() || null,
    }))
    .filter((item) => {
      if (!item.semantic || seen.has(item.semantic)) return false;
      seen.add(item.semantic);
      return true;
    });
}

async function handleSave() {
  try {
    await formRef.value?.validate();
  } catch {
    return;
  }

  const projectId = projectStore.currentProjectId;
  if (!projectId) {
    message.warning("请先选择项目");
    return;
  }

  const stepsPayload = form.steps
    .filter((s) => s.action.trim())
    .map((s, i) => ({
      step_number: i + 1,
      action: s.action,
      expected_result: s.expected_result || null,
    }));

  saving.value = true;
  try {
    let res;
    if (isNew.value) {
      res = await createTestcaseApi(projectId, {
        title: form.title,
        priority: form.priority,
        module_id: form.module_id,
        precondition: form.precondition || null,
        steps: stepsPayload,
        default_data_set_ids: form.default_data_set_ids,
        required_test_data: sanitizeRequiredTestData(),
      });
    } else {
      res = await updateTestcaseApi(props.testcaseId!, {
        title: form.title,
        priority: form.priority,
        status: form.status,
        module_id: form.module_id,
        precondition: form.precondition || null,
        steps: stepsPayload,
        default_data_set_ids: form.default_data_set_ids,
        required_test_data: sanitizeRequiredTestData(),
      });
    }
    if (res?.success) {
      // Phase 15.5：保存成功后接口返回 warnings 数组，有内容则不立即关闭抽屉，
      // 让作者在顶部折叠区里看到具体哪条 step 含占位符 / 探索性词汇等。
      const warnings = (res.data as { warnings?: StepQualityWarning[] } | undefined)?.warnings ?? [];
      if (warnings.length > 0) {
        qualityWarnings.value = warnings;
        message.warning(
          `${isNew.value ? "用例已创建" : "用例已保存"}，发现 ${warnings.length} 条步骤质量提示`,
        );
        emit("saved");
      } else {
        qualityWarnings.value = [];
        message.success(isNew.value ? "用例创建成功" : "用例更新成功");
        visible.value = false;
        emit("saved");
      }
    }
  } catch {
    message.error(isNew.value ? "创建失败" : "保存失败");
  } finally {
    saving.value = false;
  }
}

function dismissWarningsAndClose() {
  qualityWarnings.value = [];
  visible.value = false;
}

watch(visible, (val) => {
  if (val) {
    fetchModuleTree();
    fetchSemanticCatalog();
    qualityWarnings.value = [];
    if (props.testcaseId) {
      loadDetail(props.testcaseId);
    } else {
      resetForm();
    }
  }
});
</script>

<style scoped>
.required-data-editor {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.required-data-row {
  display: grid;
  grid-template-columns: minmax(160px, 1.2fr) 64px minmax(120px, 0.8fr) minmax(140px, 1fr) 32px;
  gap: 8px;
  align-items: center;
}

.required-data-row__semantic,
.required-data-row__fallback,
.required-data-row__desc {
  min-width: 0;
}

@media (max-width: 720px) {
  .required-data-row {
    grid-template-columns: 1fr;
  }
}

.quality-warning-list {
  margin: 0;
  padding-left: 1.1em;
  font-size: 13px;
  line-height: 1.65;
}

.quality-warning-item {
  margin-bottom: 4px;
}
</style>
