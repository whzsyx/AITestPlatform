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
}

export interface ApiTestBatchRunResult {
  total: number;
  passed: number;
  failed: number;
  elapsed_ms: number;
  scope: "selected" | "module";
  items: ApiTestBatchRunItem[];
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
