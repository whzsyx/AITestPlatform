/**
 * Task 11.1 — Dashboard 项目维度 UI 自动化统计 API。
 *
 * 后端口径见 ``app/modules/dashboard/ui_stats.py``：业务通过率分母会自动排除
 * "data_failure" 用例，跟 ExecutionDetail / ExecutionHistory 同源。
 * 用例级口径同时返回，前端切换 view 时不需要重新请求：
 * - business（用例视角，排除缺料失败）
 * - execution（用例视角，原始通过率）
 * 后端也保留 task_pass_rate 作为辅助字段（已完成执行数 / 全部终态执行数）。
 */
import { request } from "./request";
import type { ApiResponse } from "./auth";

export type UIStatsView = "business" | "execution";

export interface UIStatsConfidenceDistribution {
  reliable: number;
  synthesized: number;
  data_failure: number;
}

export interface UIStatsTopKey {
  key: string;
  count: number;
}

export interface UIStatsRecentExecution {
  id: string;
  status: string;
  mode: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  skipped_cases: number;
  duration_ms: number | null;
  tokens_total: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  business_pass_rate: number;
  execution_pass_rate: number;
  data_failure_cases: number;
  synthesized_cases: number;
  reliable_cases: number;
}

export interface UIStatsData {
  view: UIStatsView;
  /** 跟 view 一致的用例级口径 —— 方便前端透传；独立字段也会同时附在下方。 */
  pass_rate: number;
  business_pass_rate: number;
  execution_pass_rate: number;
  /** 任务级通过率：completed 执行数 / 全部终态执行数。 */
  task_pass_rate: number;
  /** 「completed」状态的执行数（前置步骤失败 / 浏览器异常 / 中止都不算）。 */
  succeeded_exec_count: number;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  skipped_cases: number;
  excluded_data_failure_cases: number;
  confidence_distribution: UIStatsConfidenceDistribution;
  top_synthesized_keys: UIStatsTopKey[];
  execution_count: number;
  total_tokens: number;
  avg_duration_ms: number | null;
  recent_executions: UIStatsRecentExecution[];
}

export function getProjectUIStatsApi(
  projectId: string,
  params: { view?: UIStatsView; recent_limit?: number } = {},
) {
  const q = new URLSearchParams();
  q.set("view", params.view ?? "business");
  if (params.recent_limit) q.set("recent_limit", String(params.recent_limit));
  return request<ApiResponse<UIStatsData>>(
    `/projects/${projectId}/ui-stats?${q.toString()}`,
  );
}

// ─── Phase 15.8: 高频失败用例 (unstable cases) ──────────────────────────
// 后端口径见 ``app/modules/dashboard/ui_stats.py::get_project_unstable_cases``,
// 默认最近 5 次 + 失败率 ≥ 70%; 前端展示为列表卡片 (testcase_title / 失败率 /
// 最近 3 次状态点 / 最近一次错误摘要), 不做"自动移出回归集"破坏性操作.

export interface UnstableCaseRecentRun {
  status: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface UnstableCaseItem {
  testcase_id: string;
  testcase_title: string;
  total_runs: number;
  failed_runs: number;
  failure_rate: number;
  recent_runs: UnstableCaseRecentRun[];
}

export interface UnstableCasesData {
  items: UnstableCaseItem[];
  lookback: number;
  failure_ratio: number;
}

export function getProjectUnstableCasesApi(
  projectId: string,
  params: { lookback?: number; failure_ratio?: number } = {},
) {
  const q = new URLSearchParams();
  if (params.lookback) q.set("lookback", String(params.lookback));
  if (params.failure_ratio !== undefined)
    q.set("failure_ratio", String(params.failure_ratio));
  const qs = q.toString();
  return request<ApiResponse<UnstableCasesData>>(
    `/projects/${projectId}/ui-stats/unstable-cases${qs ? `?${qs}` : ""}`,
  );
}
