import { request } from "./request";
import type { ApiResponse } from "./auth";

export type ApiMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type ApiBodyType = "none" | "json" | "text";
export type ApiAssertionType = "status_code" | "body_contains" | "json_path_eq";

export interface ApiTestModuleTreeNode {
  id: string;
  name: string;
  parent_id: string | null;
  order_index: number;
  case_count: number;
  children: ApiTestModuleTreeNode[];
}

export interface ApiTestModuleInfo {
  id: string;
  project_id: string;
  parent_id: string | null;
  name: string;
  order_index: number;
  created_at: string;
  updated_at: string;
}

export interface ApiTestEnvironment {
  id: string;
  project_id: string;
  name: string;
  base_url: string;
  description: string | null;
  order_index: number;
  created_at: string;
  updated_at: string;
}

export interface ApiTestEnvironmentVariable {
  id: string;
  project_id: string;
  environment_id: string;
  key: string;
  value: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiAssertion {
  type: ApiAssertionType;
  expected: unknown;
  path?: string | null;
}

export interface ApiAssertionResult extends ApiAssertion {
  passed: boolean;
  reason: string;
  actual?: unknown;
}

export interface ApiTestCaseListItem {
  id: string;
  project_id: string;
  module_id: string;
  module_name: string | null;
  environment_id: string | null;
  environment_name: string | null;
  name: string;
  method: ApiMethod;
  url: string;
  base_url: string | null;
  path: string | null;
  created_by: string;
  creator_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiRenderedRequestConfig {
  url: string;
  base_url: string | null;
  path: string;
  headers: Record<string, string>;
  query_params: Record<string, unknown>;
  body_type: ApiBodyType;
  body_json: unknown;
  body_text: string | null;
  assertions: ApiAssertion[];
}

export interface ApiTestCaseDetail extends ApiTestCaseListItem {
  headers: Record<string, unknown>;
  query_params: Record<string, unknown>;
  body_type: ApiBodyType;
  body_json: unknown;
  body_text: string | null;
  assertions: ApiAssertion[];
  rendered_request: ApiRenderedRequestConfig | null;
}

export interface ApiTestCasePayload {
  module_id: string;
  environment_id?: string | null;
  name: string;
  method: ApiMethod;
  url?: string | null;
  base_url?: string | null;
  path?: string | null;
  headers?: Record<string, unknown>;
  query_params?: Record<string, unknown>;
  body_type?: ApiBodyType;
  body_json?: unknown;
  body_text?: string | null;
  assertions?: ApiAssertion[];
}

export interface PaginatedApiTests {
  items: ApiTestCaseListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApiTestRunResult {
  passed: boolean;
  status_code: number | null;
  elapsed_ms: number;
  request_url: string;
  response_headers: Record<string, string>;
  response_body: string;
  response_json: unknown;
  assertions: ApiAssertionResult[];
  error: string | null;
}

export interface ApiTestBatchRunItem {
  case_id: string;
  name: string;
  method: ApiMethod;
  module_id: string;
  module_name: string | null;
  environment_id: string | null;
  environment_name: string | null;
  request_url: string;
  passed: boolean;
  status_code: number | null;
  elapsed_ms: number;
  assertion_count: number;
  failed_assertion_count: number;
  error: string | null;
  rendered_request: ApiRenderedRequestConfig | null;
  run_result: ApiTestRunResult | null;
}

export interface ApiTestBatchRunResult {
  total: number;
  passed: number;
  failed: number;
  elapsed_ms: number;
  scope: "selected" | "module";
  items: ApiTestBatchRunItem[];
}

export type ApiAutomationScheduleType = "manual" | "interval" | "daily";
export type ApiAutomationTriggerType = "manual" | "schedule";
export type ApiAutomationRunStatus = "running" | "passed" | "failed";
export type ApiAutomationStepStatus = ApiAutomationRunStatus | "skipped";
export type ApiAutomationExtractorSource =
  | "response_json"
  | "response_header"
  | "response_text"
  | "status_code";

export interface ApiAutomationExtractor {
  name: string;
  source: ApiAutomationExtractorSource;
  path?: string | null;
  header?: string | null;
}

export interface ApiAutomationStepPayload {
  id?: string | null;
  api_case_id: string;
  name?: string | null;
  order_index: number;
  enabled: boolean;
  request_overrides: Record<string, unknown>;
  extractors: ApiAutomationExtractor[];
}

export interface ApiAutomationStep extends ApiAutomationStepPayload {
  id: string;
  task_id: string;
  api_name: string | null;
  method: ApiMethod | null;
  path: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiAutomationTaskListItem {
  id: string;
  project_id: string;
  environment_id: string | null;
  environment_name: string | null;
  name: string;
  description: string | null;
  enabled: boolean;
  schedule_type: ApiAutomationScheduleType;
  interval_minutes: number | null;
  daily_time: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  timeout_seconds: number;
  stop_on_failure: boolean;
  step_count: number;
  last_status: string | null;
  created_by: string;
  creator_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiAutomationTaskDetail extends ApiAutomationTaskListItem {
  steps: ApiAutomationStep[];
}

export interface ApiAutomationTaskPayload {
  name: string;
  description?: string | null;
  environment_id?: string | null;
  enabled?: boolean;
  schedule_type?: ApiAutomationScheduleType;
  interval_minutes?: number | null;
  daily_time?: string | null;
  timeout_seconds?: number;
  stop_on_failure?: boolean;
  steps?: ApiAutomationStepPayload[];
}

export interface PaginatedApiAutomationTasks {
  items: ApiAutomationTaskListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApiAutomationRunStep {
  id: string;
  run_id: string;
  task_step_id: string | null;
  api_case_id: string | null;
  name: string;
  method: ApiMethod | null;
  order_index: number;
  status: ApiAutomationStepStatus;
  request_url: string | null;
  status_code: number | null;
  elapsed_ms: number;
  request_snapshot: ApiRenderedRequestConfig | null;
  response_snapshot: ApiTestRunResult | null;
  assertion_results: ApiAssertionResult[];
  extracted_values: Record<string, unknown>;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiAutomationRunResult {
  id: string;
  task_id: string;
  task_name: string | null;
  project_id: string;
  trigger_type: ApiAutomationTriggerType;
  status: ApiAutomationRunStatus;
  started_at: string;
  completed_at: string | null;
  total_steps: number;
  passed_steps: number;
  failed_steps: number;
  skipped_steps: number;
  elapsed_ms: number;
  runtime_data: Record<string, unknown>;
  error: string | null;
  steps: ApiAutomationRunStep[];
}

export interface PaginatedApiAutomationRuns {
  items: ApiAutomationRunResult[];
  total: number;
  page: number;
  page_size: number;
}

export function getApiTestModuleTreeApi(projectId: string) {
  return request<ApiResponse<ApiTestModuleTreeNode[]>>(
    `/projects/${projectId}/api-test-modules`,
  );
}

export function createApiTestModuleApi(
  projectId: string,
  data: { name: string; parent_id?: string | null; order_index?: number },
) {
  return request<ApiResponse<ApiTestModuleInfo>>(
    `/projects/${projectId}/api-test-modules`,
    { method: "POST", body: data },
  );
}

export function updateApiTestModuleApi(
  moduleId: string,
  data: { name?: string; parent_id?: string | null; order_index?: number },
) {
  return request<ApiResponse<ApiTestModuleInfo>>(`/api-test-modules/${moduleId}`, {
    method: "PATCH",
    body: data,
  });
}

export function deleteApiTestModuleApi(moduleId: string) {
  return request<ApiResponse<null>>(`/api-test-modules/${moduleId}`, { method: "DELETE" });
}

export function listApiTestEnvironmentsApi(projectId: string) {
  return request<ApiResponse<ApiTestEnvironment[]>>(
    `/projects/${projectId}/api-test-environments`,
  );
}

export function createApiTestEnvironmentApi(
  projectId: string,
  payload: {
    name: string;
    base_url: string;
    description?: string | null;
    order_index?: number;
  },
) {
  return request<ApiResponse<ApiTestEnvironment>>(
    `/projects/${projectId}/api-test-environments`,
    { method: "POST", body: payload },
  );
}

export function updateApiTestEnvironmentApi(
  environmentId: string,
  payload: {
    name?: string;
    base_url?: string;
    description?: string | null;
    order_index?: number;
  },
) {
  return request<ApiResponse<ApiTestEnvironment>>(
    `/api-test-environments/${environmentId}`,
    { method: "PATCH", body: payload },
  );
}

export function deleteApiTestEnvironmentApi(environmentId: string) {
  return request<ApiResponse<null>>(`/api-test-environments/${environmentId}`, {
    method: "DELETE",
  });
}

export function listApiTestEnvironmentVariablesApi(environmentId: string) {
  return request<ApiResponse<ApiTestEnvironmentVariable[]>>(
    `/api-test-environments/${environmentId}/variables`,
  );
}

export function createApiTestEnvironmentVariableApi(
  environmentId: string,
  payload: { key: string; value: string; description?: string | null },
) {
  return request<ApiResponse<ApiTestEnvironmentVariable>>(
    `/api-test-environments/${environmentId}/variables`,
    { method: "POST", body: payload },
  );
}

export function updateApiTestEnvironmentVariableApi(
  variableId: string,
  payload: { key?: string; value?: string; description?: string | null },
) {
  return request<ApiResponse<ApiTestEnvironmentVariable>>(
    `/api-test-environment-variables/${variableId}`,
    { method: "PATCH", body: payload },
  );
}

export function deleteApiTestEnvironmentVariableApi(variableId: string) {
  return request<ApiResponse<null>>(`/api-test-environment-variables/${variableId}`, {
    method: "DELETE",
  });
}

export function listApiTestsApi(
  projectId: string,
  params: { page?: number; page_size?: number; module_id?: string | null; search?: string } = {},
) {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  if (params.module_id) q.set("module_id", params.module_id);
  if (params.search) q.set("search", params.search);
  return request<ApiResponse<PaginatedApiTests>>(
    `/projects/${projectId}/api-tests${q.toString() ? `?${q}` : ""}`,
  );
}

export function createApiTestApi(projectId: string, payload: ApiTestCasePayload) {
  return request<ApiResponse<ApiTestCaseDetail>>(`/projects/${projectId}/api-tests`, {
    method: "POST",
    body: payload,
  });
}

export function getApiTestApi(caseId: string) {
  return request<ApiResponse<ApiTestCaseDetail>>(`/api-tests/${caseId}`);
}

export function updateApiTestApi(caseId: string, payload: Partial<ApiTestCasePayload>) {
  return request<ApiResponse<ApiTestCaseDetail>>(`/api-tests/${caseId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function deleteApiTestApi(caseId: string) {
  return request<ApiResponse<null>>(`/api-tests/${caseId}`, { method: "DELETE" });
}

export function runApiTestApi(
  caseId: string,
  payload: { base_url?: string | null; timeout_seconds?: number } = {},
) {
  return request<ApiResponse<ApiTestRunResult>>(`/api-tests/${caseId}/run`, {
    method: "POST",
    body: payload,
  });
}

export function runApiTestsBatchApi(
  projectId: string,
  payload: {
    case_ids?: string[];
    module_id?: string | null;
    include_descendants?: boolean;
    base_url?: string | null;
    timeout_seconds?: number;
  },
) {
  return request<ApiResponse<ApiTestBatchRunResult>>(
    `/projects/${projectId}/api-tests/run-batch`,
    {
      method: "POST",
      body: payload,
    },
  );
}

export function listApiAutomationTasksApi(
  projectId: string,
  params: { page?: number; page_size?: number; search?: string } = {},
) {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  if (params.search) q.set("search", params.search);
  return request<ApiResponse<PaginatedApiAutomationTasks>>(
    `/projects/${projectId}/api-automation-tasks${q.toString() ? `?${q}` : ""}`,
  );
}

export function createApiAutomationTaskApi(projectId: string, payload: ApiAutomationTaskPayload) {
  return request<ApiResponse<ApiAutomationTaskDetail>>(
    `/projects/${projectId}/api-automation-tasks`,
    { method: "POST", body: payload },
  );
}

export function getApiAutomationTaskApi(taskId: string) {
  return request<ApiResponse<ApiAutomationTaskDetail>>(`/api-automation-tasks/${taskId}`);
}

export function updateApiAutomationTaskApi(
  taskId: string,
  payload: Partial<ApiAutomationTaskPayload>,
) {
  return request<ApiResponse<ApiAutomationTaskDetail>>(`/api-automation-tasks/${taskId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function deleteApiAutomationTaskApi(taskId: string) {
  return request<ApiResponse<null>>(`/api-automation-tasks/${taskId}`, { method: "DELETE" });
}

export function runApiAutomationTaskApi(taskId: string) {
  return request<ApiResponse<ApiAutomationRunResult>>(`/api-automation-tasks/${taskId}/run`, {
    method: "POST",
    body: { trigger_type: "manual" },
  });
}

export function listApiAutomationRunsApi(
  taskId: string,
  params: { page?: number; page_size?: number } = {},
) {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  return request<ApiResponse<PaginatedApiAutomationRuns>>(
    `/api-automation-tasks/${taskId}/runs${q.toString() ? `?${q}` : ""}`,
  );
}

export function getApiAutomationRunApi(runId: string) {
  return request<ApiResponse<ApiAutomationRunResult>>(`/api-automation-runs/${runId}`);
}
