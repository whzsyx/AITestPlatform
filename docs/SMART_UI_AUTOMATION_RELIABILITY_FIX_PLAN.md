# 智能 UI 自动化可靠性修复计划（Phase 15）

> 立项依据：基于近 30 天 117 条用例 / 257 条步骤的真实执行数据，对 Phase 14
> 已落地的"轻量混合模式"做**可靠性闭环修复**。本期目标不是再造架构，而是
> 把当前架构里**已经被数据证明会反复翻车**的 7 类问题分批修掉，把步骤通过
> 率从 56.4% 拉到 75%+，平均 tokens/execution 从 33 万 → 12 万左右。
>
> 与 [`SMART_UI_AUTOMATION_OPTIMIZATION_PLAN.md`](./SMART_UI_AUTOMATION_OPTIMIZATION_PLAN.md)
> 的关系：那是 Phase 14 的"DSL + 规则编译 + 确定性 Runner"骨架；本计划是 Phase 15
> 的"骨架已具备但仍不可靠"的修复增量，**不重写、不替换、只补漏**。

---

## 0. 现状画像（30 天数据基线）

落地前（口径：`ui_step_results.created_at > NOW() - 30 days`，对应 `source='catalog'`）：

| 指标 | 值 |
|---|---|
| 用例总数 / 业务通过率 | 117 / **39%** |
| 步骤总数 / 通过率 | 257 / **56.4%** |
| 平均执行时长 / 平均 tokens | **7.6 分钟** / **33.2 万** |
| 步骤路径 deterministic 通过率 | 53.9%（69 / 128） |
| 步骤路径 ai_fallback 通过率 | **6.7%**（2 / 30）|
| 步骤路径 ai_step_runner 通过率 | 60%（9 / 15） |
| 同一用例近 4 次全失败 | 5 条 |

> 完整数据查询见 §6。每个 task 完工后都要按同一口径采样对比。

---

## 1. 设计原则与不变量

为避免本期修复又陷入"加了一堆补丁、可靠性更复杂"的反模式，所有 task 都必须遵守：

1. **AI fence 必须收紧**：模型 reasoning 文本只用于审计与日志，**不**作为
   AssertionJudge 的判定输入；动作必须由实际 `tool_call` 派发，不能从
   reasoning 推断。
2. **每条 task 单独可灰度、可回滚**：通过 `execution_strategy` /
   配置开关 / 数据库列默认值切换，避免"一个补丁强行覆盖所有历史行为"。
3. **数据驱动**：每条 task 在 §3 都明确写"修复哪类历史失败"，验收时按
   §4 的口径量化对比。
4. **验证回归不可降级**：本期所有 task 都必须先跑完整 `pytest` 与 docker-smoke，
   不允许"因为加了新逻辑、旧逻辑测试自然过不了"这种隐性退化。
5. **不引入新基础设施**：不上 Redis、不上向量库、不新增容器；只在现有表上
   加列 / 现有模块上加方法。
6. **危险动作护栏不放宽**：删除 / 提交 / 支付 / 发布 / 清空类动作的现有保护
   不能被任何修复绕开。

---

## 2. 落地顺序总览

工作量符号：🟢 S ≈ < 1 天，🟡 M ≈ 1-2 天，🟠 L ≈ 2-3 天。

| Task | 标题 | 工时 | 风险 | 直接修复 | 期望净值 |
|---|---|---|---|---|---|
| 15.1 | 主仓库基线整改 + 步骤诊断字段补全 | 🟢 S | 低 | 防止已落地能力丢失；可观测奠基 | 后续 task 可量化对比 |
| 15.2 | StepRunner reasoning 幻觉防护 | 🟠 L | 中 | 8 个零工具长耗时失败步 | 节省 ~143 万 tokens；步骤通过率 +3pp |
| 15.3 | 动作后等待 + 表格断言 polling | 🟠 L | 低 | 16 个"点击查询无结果"类失败 | 步骤通过率 +5pp |
| 15.4a | AI fallback 默认关闭 + 收敛触发条件 | 🟡 M | 中 | 28 个 fallback 失败步骤 | 节省 ~30-80 万 tokens / 失败步；步骤通过率 +5pp |
| 15.4b | AI fallback 接通真实自愈循环 | 🟠 L | 中 | 把 fallback 通过率从 6.7% 提到 30%+ | 步骤通过率再 +2pp |
| 15.5 | 占位符严格模式 + 用例质量校验 | 🟡 M | 中 | 5 个占位符泄漏失败步 + 防新增 | 步骤通过率 +2pp；早期阻断坏用例 |
| 15.6 | locator 候选增强 + assert_text 三级降级 | 🟡 M | 低 | 22 个 locator + 9 个 assert_text 失败 | 步骤通过率 +5pp |
| 15.7 | 单步动态预算 + 循环 early-stop | 🟡 M | 中 | 单步 22-toolcall 暴走防护 | 单步上限 ≤ 5 分钟；防最坏体验 |
| 15.8 | 反爬命中早停 + 失败稳定度看板 | 🟢 S | 低 | 5 条 demo 用例 16 次必败 | 每周节省 ~2.5h / 30 万 tokens |
| 15.9 | 成功 locator 持久化与复用（可选） | 🟠 L | 低 | 重复执行的稳定性 | 长期把成熟用例步骤通过率拉到 90%+ |
| 15.10 | 前端执行诊断字段可视化 | 🟢 S | 低 | 横切：调试体验 | 把"看不出 deterministic 失败原因"修掉 |

依赖图（→ 表示推荐前置）：

```
15.1 → 15.2 → 15.3 → 15.4a → 15.4b
                ↘                ↗
                  15.5 → 15.6 → 15.7
                                  ↘
                                   15.8
                                    ↘
                                     15.9 (可选)
                                      ↘
                                       15.10
```

每个 task 都按 [`SMART_UI_AUTOMATION_OPTIMIZATION_PLAN.md`](./SMART_UI_AUTOMATION_OPTIMIZATION_PLAN.md)
的体例：目标 / 建议文件 / 实现要点 / 验收标准 / 风险与回退。


---

## 3. Task 拆分

### Task 15.1 — 主仓库基线整改 + 步骤诊断字段补全 🟢 S

**目标**：把当前已落地但**未纳入 git 跟踪**的能力（含 `failure_triage.py`、
`api_stats.py`、相关测试）合入主分支，并给 `ui_step_results` 加几个轻量诊断字段，
为后续 task 提供"before/after 可量化"的基线。

**前置**：无。这是其它 task 的地基。

**建议文件 / 改动**：

- 把 untracked 的以下文件 git add + 提交：
  - `backend/app/modules/ui_automation/failure_triage.py`
  - `backend/tests/ui_automation/test_failure_triage.py`
  - `backend/app/modules/dashboard/api_stats.py`
  - `backend/tests/dashboard/test_api_stats.py`
  - `backend/tests/ui_automation/test_execution_strategy.py`
  - `backend/tests/llm/test_testcase_generation_prompt.py`
- 同时审查 main 上 modified 文件（`execution_engine.py / plan_compiler.py`
  等）是否需要分开提交还是合并提交（建议按"功能聚类"切 2-3 个 commit）。
- 新增 alembic 迁移：给 `ui_step_results` 加 4 列（全部可空、不破坏旧记录）：
  - `execution_path TEXT`：deterministic / ai_fallback / ai_step_runner / unknown
  - `fallback_reason TEXT`：来自 deterministic_runner 的 `error_kind` 或 reason
  - `loop_break_reason TEXT`：StepRunner 退出原因（normal / max_iter / budget /
    duplicate_tool / snapshot_unchanged / reasoning_drift / ...）
  - `assertion_method TEXT`：deterministic / rule / llm / triage_external / ...
- 现有 `tool_calls` 里的 `execution_meta` 节点继续保留，但**关键诊断字段以列
  形式落库**便于 SQL 聚合（前端展示见 15.10）。
- `persistence.flush_step` 写入新字段；旧调用点不传时默认 None。
- 加索引：`(execution_path, status)` 联合索引，便于后续 task 做对比统计。

**实现要点**：

- 不改业务逻辑，只动 schema + 落库层。
- alembic 迁移要 idempotent：判断列存在再 add，方便回滚。
- 配套 `backend/tests/ui_automation/test_persistence.py` 加 1-2 条断言。
- 提交 message 模板：`feat(ui-automation): 把 failure_triage/api_stats 等基线
  能力纳入主仓库 + 步骤诊断字段补齐（Phase 15.1）`。

**验收标准**：

- `git status` 显示 working tree clean，`failure_triage.py` 等文件已被跟踪。
- `alembic upgrade head` 在新建 DB 与已有 DB 上都能跑通；列存在性幂等。
- 新建一次 UI 自动化执行，`ui_step_results` 行能看到 4 个新字段被填值。
- 现有 117 条历史用例数据不受影响（旧记录新列为 NULL 是合预期）。
- 全部测试 pass：`./run.sh test backend/tests/ui_automation/`、`./run.sh
  test backend/tests/dashboard/`。

**风险与回退**：

- 风险：alembic 迁移如果加错列约束会让历史数据无法读。回退：迁移 `downgrade`
  仅删新加的 4 列，不动既有 schema。

---

### Task 15.2 — StepRunner reasoning 幻觉与零工具防护 🟠 L

**目标**：修复"模型在 reasoning 文本里完整模拟操作但没真调任何工具，导致
断言阶段拿到错误快照"这一**当前最贵也最隐蔽**的失败模式。

**前置**：15.1。

**对应历史问题**：8 次 `tc_count<=1 + duration>30s + tokens>15w` 的零工具
长耗时失败步骤，光这 8 步就烧了 143 万 tokens；典型现场 id `316a3dc9-01ea-4d8a-bd65-22d3ec272fdf`。

**建议文件**：

- 修改 `backend/app/modules/ui_automation/step_runner.py`
- 修改 `backend/app/modules/ui_automation/assertion_judge.py`
- 修改 `backend/app/modules/ui_automation/prompts/step_runner_system.py`
- 新增 `backend/tests/ui_automation/test_step_reasoning_drift.py`

**实现要点**：

1. **首轮 0 toolcall + reasoning 含动作词时强制重试**：
   - 在 `step_runner.run_one` 的循环中，第 1 次 round 若 `tool_calls=[]`
     **且** reasoning/content 命中 `_ACTION_INTENT_PATTERN`（如 `点击|输入|
     提交|navigate|click|type|fill|press`），不要 break；追加一条 user
     message：「你在思考里描述了若干浏览器动作但本轮没真正调用工具。请基于
     当前页面状态用 browser_* 工具实际完成这些动作。」并将 `tool_choice="required"`
     再跑一轮。
   - 仅允许此机制触发**一次**，避免死循环。触发后 `loop_break_reason="reasoning_drift_recovered"`
     落库。
   - 如果二次也 0 toolcall，则 `loop_break_reason="reasoning_drift_unrecoverable"`
     退出，但**保留这次空 round 的 reasoning 给审计**。

2. **AssertionJudge 不再吃 reasoning**：
   - `_build_assertion_context`（execution_engine.py 内）已经把
     `run_result.reasoning` 拼进去做语义兜底；改为：默认**不**注入 reasoning，
     只用 `last_snapshot_text + tool_call results + structured_evidence`；
     仅当 `verdict.method='llm'` 兜底且无任何结构化证据时才允许传 reasoning，
     **且加显式标记** `<ai_reasoning_advisory>` 让 LLM 知道这只是参考信息。

3. **prompt 收紧**：
   - `_BASE_SYSTEM_PROMPT` 在"行为约束"段加一行强调："请用真实
     `browser_*` 工具调用替代 reasoning 文字描述；reasoning 中描述的动作
     如未对应工具调用，将被平台视为未执行。"

4. **可观测**：每次 reasoning_drift 触发都 emit 一个 SSE 事件
   `step_drift_detected`，前端在执行详情时间线显式标红"模型已尝试虚拟操作，
   平台已强制注入工具调用"。

**验收标准**：

- 单元测试覆盖 4 个分支：(a) 正常首轮 toolcall；(b) 首轮 0 tc + 无动作词 → 走原 break；
  (c) 首轮 0 tc + 含动作词 → 触发强制重试 → 第二轮 tc 正常；
  (d) 强制重试后仍 0 tc → 标记 unrecoverable。
- 真实回归：手工挑选 `316a3dc9-...` 同形态的"确认下架"用例重跑，能看到
  `step_drift_detected` 事件并最终 passed。
- AssertionJudge 单测：构造一条只有 `reasoning="我点击了 X"` 但
  `last_snapshot_text` 不含相应文本的样本，验证 verdict 不再被 reasoning 误导。

**风险与回退**：

- 风险：某些 thinking 模型把动作意图天然写在 reasoning 里，强制再跑一轮可能
  让短任务失败率升高。
- 回退：`reasoning_drift_recovery_enabled` 配置开关，环境变量
  `UI_REASONING_DRIFT_RECOVERY=false` 关闭新逻辑，回到原 break 行为。
- 默认值：开启。


---

### Task 15.3 — 动作后等待与表格断言 polling 升级 🟠 L

**目标**：彻底修掉"点击查询/搜索/确定按钮 → 后端 ajax 还在飞 → 立即拿快照
→ 断言说『未提供查询结果』"这一类伪失败。

**前置**：15.1。可与 15.2 并行。

**对应历史问题**：「点击「查询」按钮」27 次中失败 16 次（59%），其中 14/16
是同一原因「快照仅显示点击操作成功，未提供查询结果数据」。

**建议文件**：

- 修改 `backend/app/modules/ui_automation/deterministic_runner.py`
- 修改 `backend/app/modules/ui_automation/action_plan.py`（加 `expects_data_refresh` 字段）
- 修改 `backend/app/modules/ui_automation/plan_compiler.py`（编译时识别）
- 修改 `backend/app/modules/ui_automation/assertion_rules.py`（表格断言加 polling）
- 新增 `backend/tests/ui_automation/test_post_action_wait.py`

**实现要点**：

1. **`UIActionStep` 新增字段**（保持向后兼容）：
   - `expects_data_refresh: bool = False`：动作触发数据加载（点击查询/搜索/
     刷新/确定/提交/导入/导出 等）。
   - `wait_strategy: str | None = None`：可选枚举 `quick / network_idle /
     loading_indicator / data_refresh`。

2. **plan_compiler 编译时自动识别**：
   - `_compile_click` 命中按钮名包含 `查询|搜索|刷新|确定|确认|提交|登录|
     导入|导出|应用|过滤` 时置 `expects_data_refresh=True`。
   - `_compile_press_key` 命中 `Enter` 时置 `expects_data_refresh=True`。

3. **`_wait_after_action` 升级**：
   ```text
   等待级别（按 expects_data_refresh 决定）：
   - false（默认）：现有 1.5s domcontentloaded + 300ms timeout
   - true：依次 race
       (a) wait_for_load_state("networkidle", 3000ms)
       (b) 监听 page.expect_response 短窗口（800ms）—— 若动作触发了 XHR/fetch，
           等到首个相关 response 完成或 3s 超时
       (c) 等待 .ant-table-loading / .el-loading-mask / [aria-busy='true'] /
           [role='status'][aria-live] 这类 loading 指示器**消失**，最多 5s
       (d) 上界 8s 兜底
   ```
   - 注意：每一步都用 `try/except` 包住，失败回退继续走，**不能让等待变成新
     的失败源**。
   - 全部用 Playwright 内置 API，不要 `time.sleep`、不要 `asyncio.sleep` 的固定
     长等待。

4. **`assert_table_rows` / `assert_table_columns` 加 polling**：
   - `EvidenceCollector.collect_table_rows` / `collect_table_schema` 接受
     `polling_ms: int = 0` 参数。
   - 调用方在断言失败首次时（`evidence.ok=False` 或 `rows=[]`）启动 polling：
     间隔 500ms、上限 6s；命中 `aria-busy=false` 且至少 1 行后立即返回。
   - 这条命中后步骤重新 `assert`，不命中再 fail。

5. **`assert_text` 也接 polling**：动作刚结束时 text 可能还没渲染，给 2s 短
   窗口探活。

**验收标准**：

- 单元测试用 fake page mock 验证 4 种等待级别都能正确触发；fake page 模拟
  loading mask 后消失，验证 polling 能等到。
- 回放历史失败用例（"点击查询按钮 → 验证创作者列表" 类，testcase_id
  `dd82a693`、`a1e1ea8c` 等）：**步骤通过率从 ~40% → 80%+**。
- 等待新机制平均增加单步耗时不超过 1.5s（用 fake 页面 quick path 测）。

**风险与回退**：

- 风险：过度等待让本来快的动作变慢；某些极端 SPA loading 指示器永不消失。
- 回退：环境变量 `UI_POST_ACTION_WAIT_MAX_MS` 配置上限（默认 8000，调到 1500
  即等同旧行为）；plan_compiler 的 `expects_data_refresh` 识别规则可在
  config 里关闭。

---

### Task 15.4a — AI fallback 默认关闭 + 触发条件收敛 🟡 M

**目标**：把当前正在变成"token 焚化炉"的 ai_fallback 路径止血——默认关闭
fallback，仅保留**有数据证据**支撑会真正变好的 case 走 fallback。

**前置**：15.1（要先有 `execution_path / fallback_reason` 字段做 before/after 对比）。

**对应历史问题**：ai_fallback 路径 30 次只通过 2 次（**6.7%**），平均一次失败
步耗时 226-472 秒、tokens 16-87 万；fallback 输出实际**没被二次执行**，相当于
"再读一遍页面写报告"。

**建议文件**：

- 修改 `backend/app/modules/ui_automation/execution_engine.py`（`_run_step_with_strategy`、
  `_ai_fallback_allowed`）
- 修改 `backend/app/modules/ui_automation/schemas.py`（新增策略枚举）
- 新增 `backend/tests/ui_automation/test_fallback_gating.py`

**实现要点**：

1. **execution_strategy 拆三态**：
   - `ai_step_runner`：旧的全 AI 模式（保留以备回退）。
   - `hybrid_lightweight`：当前默认；本期**不再触发 AI fallback**。
   - `hybrid_lightweight_with_fallback`：显式手动开启 fallback；只在 task 15.4b
     落地后才推荐。

2. **`_ai_fallback_allowed` 收紧**：
   - 仅当下列**全部**满足时返回 True：
     - `compiled_step.kind in {CLICK, FILL}`（断言类不进 fallback）
     - `compiled_step.risk_level != "high"`
     - `deterministic_result.evidence.error_kind == "locator_not_found"`
     - **新增**：步骤 source_text 显式包含目标元素描述（"点击 X 按钮" /
       "在 X 输入框输入"）；探索性步骤（含"若有 / 尝试 / 可能 / 如果"等
       hedging 词）一律不允许 fallback。
   - 其余情况一律走 deterministic verdict 直接落地，不再调 LLM。

3. **fallback 独立预算**：
   - 即使开启 fallback，每个 step 的 fallback budget 独立上限
     `STEP_FALLBACK_TOKEN_BUDGET=50000`（之前共享全局 budget）；超额直接
     `error_kind="fallback_budget_exceeded"` 退出。

4. **default 切换**：保持默认 `hybrid_lightweight`（即默认关闭 fallback）；
   在前端 ExecuteDialog 高级选项里**保留**手动选 `hybrid_lightweight_with_fallback`，
   但加红色提示说明"该模式 token 消耗显著、当前通过率 < 10%，建议仅诊断使用"。

**验收标准**：

- 单元测试覆盖：探索性步骤 / 断言步骤 / 高风险步骤 / locator_ambiguous 都
  **不**触发 fallback；只有"明确点击/填写 + locator_not_found"才触发（且仅在
  fallback 显式开启的策略下）。
- 真实回放：用 30 天历史失败步骤复跑（mock 模型），能看到 `ai_fallback`
  路径计数从 30 → 0（默认策略下），节省的 token 在 step 级 metric 中体现。
- 不影响 `ai_step_runner` 旧策略。

**风险与回退**：

- 风险：之前依赖 fallback 的某些边界场景会暴露 deterministic 缺陷。这正是
  暴露真问题的好机会；用 15.6 解决 locator 增强，比让 fallback 兜更划算。
- 回退：用户可在执行弹窗手动选 `hybrid_lightweight_with_fallback`。

---

### Task 15.4b — AI fallback 接通真实自愈循环 🟠 L

**目标**：把 fallback 从"昂贵的失败说明生成器"升级为"建议 locator → Runner
二次验证执行"的真实自愈机制。

**前置**：15.4a + 15.6（自愈循环依赖 locator 增强后的 Runner）。

**建议文件**：

- 修改 `backend/app/modules/ui_automation/execution_engine.py`
- 修改 `backend/app/modules/ui_automation/step_runner.py`（fallback 模式）
- 修改 `backend/app/modules/ui_automation/prompts/step_runner_system.py`
- 修改 `backend/app/modules/ui_automation/deterministic_runner.py`（接受外部 locator）
- 新增 `backend/tests/ui_automation/test_fallback_self_heal.py`

**实现要点**：

1. **fallback 输出协议**：把 prompt 改为**强约束 strict JSON**：
   ```json
   {
     "decision": "retry_with_locator | mark_unsupported | confirm_external_blocked | wait_and_retry",
     "candidate_locators": [
       {"strategy": "role|text|css|xpath", "value": "...", "rationale": "..."}
     ],
     "rationale": "为什么这样判断（依据用例步骤 X，结合证据 Y）"
   }
   ```
   - 强制 `tool_choice="none"`；不允许 fallback 阶段调任何工具（连只读都不行）。
   - JSON 解析失败 → `decision="mark_unsupported"` 兜底。

2. **engine 接通自愈**：
   - `decision="retry_with_locator"` → 调用 `DeterministicRunner.run_step` 时
     传入 candidate_locators 作为额外候选；**Runner 用同一套严格匹配规则验证**，
     count==1 才执行；多个候选按顺序尝试；全部失败回到原 deterministic verdict。
   - `decision="wait_and_retry"` → sleep 1.5s 重新尝试 deterministic 一次。
   - `decision="confirm_external_blocked"` → 改 verdict.method=`triage_external`，
     不再走断言。
   - `decision="mark_unsupported"` → 直接落 deterministic verdict。

3. **DeterministicRunner 扩展**：
   - `run_step(page, step, extra_locator_candidates=None)`：把 AI 候选并入
     `_build_locator_candidates` **末尾**（保持稳定 locator 优先）。
   - 不允许 AI 候选包含 `evaluate / runJavaScript`；strategy 只接受
     `role | text | css | xpath` 4 种白名单。
   - SecurityGuard 仍然作用于二次验证后的真实点击/输入。

4. **可观测**：`fallback_reason` 落库写明 decision；前端展示自愈过程：
   `deterministic 失败 → AI 建议 css="..." → Runner 验证 count=1 → 二次执行成功`。

**验收标准**：

- 自愈成功率：在 mock 测试下，给出错误 locator 提示 + 正确候选时，能
  100% 自愈。
- 自愈失败兜底：AI 给坏 css（count=0 或 count>1）时不执行，verdict 回到
  deterministic 原结果。
- 真实回放：选 5 条历史 `locator_not_found` 失败用例（`fill` 类居多）跑
  fallback，期望至少 2 条能自愈通过。
- 安全：SecurityGuard 拦截测试不破坏；危险动作仍被拒。

**风险与回退**：

- 风险：AI 给的 css/xpath 命中错误元素却 count==1。
- 缓解：candidate_locators 必须叠加 `step.target` 的语义校验（如 click 步骤
  目标含「按钮」时，验证元素 `tagName`/`role` 是否合理）。
- 回退：开关 `UI_AI_FALLBACK_SELF_HEAL=false` 退化为 15.4a 行为。


---

### Task 15.5 — 占位符严格模式 + 用例质量校验 🟡 M

**目标**：彻底封堵"`{{xxx}}` 占位符没替换就被拼到步骤/断言里"的数据噪音。

**前置**：15.1。可与 15.2/15.3/15.4 并行。

**对应历史问题**：

- 步骤描述里出现整段未替换：`在「创作者名称」输入框输入 ... {{name_keyword}} ...`
- 断言失败：`表格列缺失：{{existing_creator_id}}` / `未找到 输入框值显示={{xxx}} 的表格行`
- 458 条 testcase_steps 里 15 条仍含 `{{}}`，12 条带"若有/尝试"探索性词汇。

**建议文件**：

- 修改 `backend/app/modules/ui_automation/plan_compiler.py`（接 data_resolver）
- 修改 `backend/app/modules/ui_automation/preflight.py`（strict 默认值）
- 修改 `backend/app/modules/ui_automation/execution_service.py`（执行入参把
  unknown placeholder 列为前置告警）
- 修改 `backend/app/modules/testcases/router.py`（保存接口加质量校验）
- 修改 `backend/app/modules/testcases/schemas.py`（warning 列表回传）
- 修改 `frontend/src/views/testcases/TestcaseEditor.vue`（保存时显示警告）
- 新增 `backend/tests/testcases/test_step_quality.py`
- 新增 `backend/tests/ui_automation/test_placeholder_strict.py`

**实现要点**：

1. **plan_compiler 接 data_resolver**：
   - `compile_action_plan(testcase, *, module_entry_path, data_resolver=None)`
   - 编译每个 step 之前先用 `data_resolver.render_template(step.action)`；
     `original_source_text` 保留模板原文用于审计，`source_text` 是 render 后文本。
   - 渲染后仍含 `{{...}}` 的步骤标 `unsupported_reason="unresolved_placeholder"`，
     列出缺失 key。

2. **preflight strict 默认开**：
   - `preflight_data_check` 现有 `strict_data_mode` 参数默认 false → 改为 **true**。
   - 旧调用兼容：在 `execution_service.create_execution` 处显式传
     `strict_data_mode=inputs.strict_data_mode`，UI 默认勾选 strict。
   - strict 模式下：unknown placeholder → execution 直接 reject（status=`failed`，
     error_message 列出缺失 key），不进 engine。

3. **用例保存时质量校验**：
   - 在 `testcases/router.py` 的 create / update 路径上加 `validate_step_quality`：
     ```text
     warnings:
     - 步骤 N: 含未解析占位符 {{xxx}}（保存允许，执行时会被 strict 拦截）
     - 步骤 N: 长度超过 80 字 + 包含 ≥2 次「输入」/「;」 → 建议拆步骤
     - 步骤 N: 包含「若有 / 尝试 / 可能 / 如果存在」等探索性词汇 → 建议改为明确动作
     - 步骤 N: 含百度/google/cloudflare 等公共反爬 host → 建议改为受控环境
     ```
   - **不阻断保存**，只把 warnings 数组随响应返回；前端展示一段折叠警告区。

4. **占位符 unknown 列前端展示**：
   - 执行历史详情页：缺失占位符以红色徽章列出（来自 execution.config_snapshot
     的 preflight_warnings 字段）。

**验收标准**：

- 单元测试：构造一条含 `{{unknown_key}}` 的 testcase，执行接口直接 422 / 400，
  并返回缺失 key 列表。
- 用例编辑：粘贴 1 条带嵌套占位符的步骤，保存能成功，但响应里看到 3 条 warning。
- 回归：现有正常 testcase（无 `{{}}` 或都已替换）保存与执行**不受影响**。
- 历史 5 条占位符泄漏失败步骤复跑，全部在 preflight 阶段被拦截。

**风险与回退**：

- 风险：strict 默认开会让"少量物料缺漏的执行"失败；但这本就该失败。
- 回退：UI 上"严格物料模式"开关用户可勾选；命令行/旧脚本如果直接调
  `create_execution` 而不传 strict_data_mode 参数，按显式传 false 兼容旧
  行为，仅 UI 层默认勾选。

---

### Task 15.6 — locator 候选增强 + assert_text 三级降级 🟡 M

**目标**：把 deterministic 在 fill / click / assert_text 三类高频失败上的
通过率显著提升。

**前置**：15.1。可与 15.2/15.3/15.4a/15.5 并行。

**对应历史问题**：

- deterministic 失败 43 次中 16 次 `locator_not_found` + 6 次 `locator_ambiguous`，
  主要发生在 fill(17) / click(5)。
- assert_text 失败 9 次，主因是 `exact=True` 对带前后空白/嵌套节点不友好。

**建议文件**：

- 修改 `backend/app/modules/ui_automation/deterministic_runner.py`
- 新增 `backend/app/modules/ui_automation/locator_candidates.py`（把
  `_build_locator_candidates` 拆出独立模块便于扩展和测试）
- 新增 `backend/tests/ui_automation/test_locator_candidates.py`
- 新增 `backend/tests/ui_automation/test_assert_text_degrade.py`

**实现要点**：

1. **anchor-based input 候选**：
   - 在 `target.label` 分支末尾加：
     - `page.get_by_text(label, exact=True)` → `.locator(":scope ~ * input:not([type='hidden']), :scope + * input:not([type='hidden'])").first`
     - 适用 `<label>创作者ID</label><input ...>` 这种 sibling 结构。
   - 验证生成的 locator 经过 `_best_visible_editable_locator` 评分。

2. **`locator_ambiguous` 接评分降级**：
   - `_resolve_locator_once` 中 click 类多匹配的分支当前直接 fail；改为**先调
     `_best_visible_editable_locator`**（已有这个 helper，只是 click 没用）；
     仍 ambiguous 才 fail。

3. **同义词扩展（轻量版）**：
   - 内置一份 `_DEFAULT_LABEL_ALIASES`：
     ```python
     {
       "ID": ["编号", "id"],
       "名称": ["名字", "title", "name"],
       "搜索": ["查询", "查找", "Search"],
       ...
     }
     ```
   - locator 候选生成时把 alias 加入 candidate（最低优先级，count==1 时才命中）。
   - **不**做项目级 alias 表（避免复杂化）；后续如确有需要再加。

4. **assert_text 三级降级**：
   - Level 1: `page.get_by_text(text, exact=True).count()` → 命中即过。
   - Level 2: `page.get_by_text(text, exact=False).count()` → 命中即过；
     在 evidence.details 标 `match_strategy="contains"`。
   - Level 3: `page.locator(f":text-is('{text}')").or_(page.locator(f":has-text('{text}')")).count()`
     → 命中即过；标 `match_strategy="loose"`。
   - 三级都为 0 才 fail；在 message 里显式说明用了哪一级。

5. **失败 `attempts` 完整落库**：
   - `_resolve_locator_once` 现已收集 `attempts`，但只在 fail 时写入。改为：
     无论成功失败都把 attempts 写入 evidence（成功时只保留命中的那一条 + 跳过条数），
     便于 15.10 前端可视化。

**验收标准**：

- 单元测试：mock page 验证 4 种结构的 fill 都能定位（`<label for=>` / `<label>+input`
  sibling / placeholder 提示 / aria-label）。
- assert_text 单测：3 个 fixture（exact 命中 / contains 命中 / loose 命中），
  每级都能正确返回。
- 真实回放：选 17 个 `fill + locator_not_found` 历史失败步骤复跑，期望
  **至少 10 个**通过；assert_text 9 个失败步骤期望至少 6 个通过。
- 评分 helper 不会让原本能 1 个命中的步骤变成多个。

**风险与回退**：

- 风险：assert_text 太宽松导致假阳性。
- 缓解：每级都标 `match_strategy`，前端展示；用户能识别"宽松命中"。
- 回退：环境变量 `UI_ASSERT_TEXT_DEGRADE_LEVEL=1` 强制只用严格匹配；
  `UI_LOCATOR_ANCHOR_BASED=false` 关闭 anchor 候选。

---

### Task 15.7 — 单步动态 token 预算 + 循环检测 early-stop 🟡 M

**目标**：防止 AI 在反爬 / 404 / 探索性步骤里"原地刨坑"22 个工具调用、
燃烧 80 万 tokens、单步耗时 7-8 分钟的暴走场景。

**前置**：15.1。建议在 15.2 之后做（避免和 reasoning_drift 重试机制冲突）。

**对应历史问题**：

- 单步 22 tool_calls / 472 秒 / 86 万 tokens 的极端样本。
- "尝试通过行编辑功能（若有）查看新增列" 5 次 / 平均 271 秒 / 12.6 toolcall。
- `MAX_STEP_TOOL_CALL_ROUNDS=20` 太宽松。

**建议文件**：

- 修改 `backend/app/modules/ui_automation/step_runner.py`
- 修改 `backend/app/modules/ui_automation/security.py`（TokenBudget 加 step 维度）
- 新增 `backend/tests/ui_automation/test_step_loop_guard.py`

**实现要点**：

1. **`MAX_STEP_TOOL_CALL_ROUNDS` 调整为可配 + 默认 8**（环境变量
   `UI_MAX_STEP_TOOL_ROUNDS`，向后兼容旧 20）。

2. **三种 early-stop 信号**（任一命中立即跳出循环 + `loop_break_reason` 落库）：

   a. **同名工具同参数连续重复 ≥ 2 次**：维护 `recent_tool_signatures` 列表
      （含工具名 + 关键参数 hash），命中即停。理由：循环往复、模型卡死。

   b. **快照 diff 几乎为零**：连续 3 轮工具调用后 `last_clipped` 与上轮 diff
      不超过 5%（用 `snapshot_clipper` 现有 diff 计数）。理由：页面没在动，
      继续也是空转。

   c. **单步 token 软上限**：
      ```text
      step_token_budget = max(20_000, total_budget * 1.5 / max(estimated_steps, 5))
      ```
      `estimated_steps` 取自 `len(testcase.steps)`，没拿到时按 5；超过即停。
      区别于 `total_budget`：它是单条步骤独立的"温和"上限，超额仍可让其它步骤
      继续；total_budget 是整个执行的硬上限。

3. **early-stop 也要 emit auto-finalize snapshot**：保留现有
   `_auto_finalize_snapshot` 逻辑，避免 AssertionJudge 拿不到操作后页面。

4. **可观测**：`tool_calls` 末尾追加一个 `_meta_loop_guard` 节点，记录
   `break_reason / signature_history / snapshot_diff_pct`，前端时间线给一段
   橙色提示"AI 卡死，已自动结束"。

**验收标准**：

- 单元测试覆盖 3 种 early-stop 信号都能稳定触发；正常多轮 toolcall 不被误伤。
- 真实回放百度反爬步骤（`tc_count=22 / 472s` 那条），重跑后单步耗时
  **≤ 5 分钟**且 break_reason 为 `repeated_tool_signature` 或
  `snapshot_unchanged`；该步骤仍判 failed（被 failure_triage 后续标
  `external_verification`）。
- 复杂表单填写（要 5-6 轮 toolcall 才能完成）不被 8 轮上限误终止。

**风险与回退**：

- 风险：极少数复杂步骤需要 > 8 轮且页面变化不显著。
- 回退：单步级别可由调用方传 `max_iterations` 覆盖默认；环境变量调高
  `UI_MAX_STEP_TOOL_ROUNDS=20` 退回旧行为。
- early-stop 信号都可单独由 env flag 关闭（如 `UI_LOOP_GUARD_DUP_TOOL=false`）。


---

### Task 15.8 — 反爬命中早停 + 失败稳定度看板 🟢 S

**目标**：把"已知必败 demo 用例"从默认回归集里隔离出来，并在 dashboard
上显式标记。

**前置**：15.1（依赖步骤诊断字段），15.2（reasoning 修复）。

**对应历史问题**：

- 5 条百度搜索类 demo 用例近 4 周累计 16 次执行 100% 失败。
- 22 个 captcha 阻断步骤全部来自这 5 条用例。

**建议文件**：

- 修改 `backend/app/modules/ui_automation/failure_triage.py`（命中 captcha 时
  emit `early_terminate_case` 信号）
- 修改 `backend/app/modules/ui_automation/execution_engine.py`（接住信号、跳过
  剩余步骤、置 `data_confidence='data_failure'`）
- 修改 `backend/app/modules/ui_automation/plan_compiler.py`（preflight 阶段
  识别 public anti-bot host）
- 修改 `backend/app/modules/dashboard/router.py`（新增"用例稳定度"端点）
- 修改 `frontend/src/views/dashboard/DashboardView.vue`（新增"高频失败用例"卡片）
- 新增 `backend/tests/ui_automation/test_early_terminate_captcha.py`
- 新增 `backend/tests/dashboard/test_case_stability.py`

**实现要点**：

1. **`failure_triage` 增强**：
   - 命中 `_EXTERNAL_VERIFICATION_TERMS` 时返回 verdict 同时带一个
     `early_terminate=True` 标志（在 verdict.evidence 里塞 metadata）。

2. **engine 接住信号**：
   - 在用例步骤循环内若收到 early_terminate，把剩余步骤批量 mark 为 `skipped`
     + reason `case_terminated_by_external_verification`，置 case
     `data_confidence='data_failure'`、`status='failed'`，立即结束本用例。

3. **plan_compiler preflight 识别**：
   - testcase 任意 step 的 `action` / `expected` / module entry url 命中
     `baidu.com|google.com|cloudflare-challenge|hcaptcha` 关键字时，整条用例标
     `unsupported_reason="public_anti_bot_target"`，preflight 阶段直接拒绝
     执行（execution status=failed，error_message 提示替换为内网受控环境）。

4. **dashboard 用例稳定度**：
   - 新增 `/api/projects/{id}/ui-stats/unstable-cases` 端点：返回最近 N 次
     执行里失败率 ≥ 70% 的 testcase 列表，带最近 3 次的 verdict 摘要。
   - 前端 dashboard 一个"高频失败用例"折叠卡片，显示用例标题 + 一键跳转用例
     编辑器（不直接做"自动移出回归集"，避免越权）。

**验收标准**：

- 单元测试：构造 captcha 触发场景，case 提前结束，剩余 step 标 skipped。
- preflight：对包含 baidu host 的 testcase 直接拒绝；error_message 包含
  "public_anti_bot_target" 关键字。
- dashboard：手工构造 4 次失败 1 次通过的 testcase，在"高频失败用例"卡片可见。
- 不影响普通用例的执行流程。

**风险与回退**：

- 风险：误判（公司内网用了"verify" 字样的合法功能页）。
- 缓解：preflight 关键字仅匹配 public host（baidu.com / google.com / cloudflare），
  内网 host 不命中；命中后用户可通过 environment 配置 allowed_hosts 显式放行。
- 回退：`UI_EARLY_TERMINATE_ON_CAPTCHA=false` 环境变量回到原"步骤级判失败但
  继续执行剩余步骤"行为。

---

### Task 15.9 — 成功 locator 持久化与复用（可选） 🟠 L

**目标**：让"重复执行同一用例"的稳定性渐进式提升——把上次成功的 locator
作为本次的首选候选。

**前置**：15.6（locator 候选模块化拆分后接入更顺）。

**说明**：本期可选；如果 15.1-15.8 落地后通过率已达 75%+，可推迟到 Phase 16。

**建议文件**：

- 新增 alembic 迁移：`ui_case_results.successful_locators jsonb`
- 修改 `backend/app/modules/ui_automation/persistence.py`
- 修改 `backend/app/modules/ui_automation/plan_compiler.py`
- 修改 `backend/app/modules/ui_automation/locator_candidates.py`（接受 preferred）
- 新增 `backend/tests/ui_automation/test_locator_memory.py`

**实现要点**：

1. **持久化**：
   - 每个 step 成功执行后，把命中的 locator strategy + value（脱敏后）写入
     `ui_case_results.successful_locators[step_number]`。
   - 仅保留 role/text/css/xpath 4 种白名单字段。

2. **下次执行复用**：
   - plan_compiler 编译同一 testcase 时，从最近 N 次成功执行中读
     `successful_locators`；只有"最近 3 次都用同一 locator 命中"才信任。
   - 命中信任 locator → 加到候选最前；其它候选作为兜底。

3. **失效自愈**：
   - 复用 locator 失败时，自动降级到"原候选生成"逻辑；标记本次复用 miss，
     连续 2 次 miss 后清掉记忆。

**验收标准**：

- 单元测试：3 次成功后第 4 次执行能直接命中记忆 locator；记忆失效后回退正常。
- 不影响首次执行（`successful_locators` 为空即按原候选执行）。
- 历史 4 次以上重跑的 9 条 testcase（数据见 §6 查询 5）在第 5+ 次执行时
  **总耗时下降 ≥ 20%**。

**风险与回退**：

- 风险：页面 DOM 变更导致旧 locator 不再有效但 miss 阈值还没到。
- 缓解：复用 locator 经过同一套 strict 验证（count==1）才执行，没命中即降级。
- 回退：`UI_LOCATOR_MEMORY=false` 环境变量直接关闭。

---

### Task 15.10 — 前端执行诊断字段可视化 🟢 S

**目标**：把本期新增的诊断字段（execution_path / fallback_reason /
loop_break_reason / locator attempts / match_strategy 等）展示到执行详情页，
让用户能自助判断"用例失败到底是哪一层的问题"。

**前置**：15.1（字段落库前提），15.6（attempts 落库），15.7（loop_break）。

**建议文件**：

- 修改 `frontend/src/views/ui-automation/ExecutionDetail.vue`
- 修改 `frontend/src/services/uiAutomation.ts`（响应类型补 4 个新字段）
- 新增 `frontend/src/components/ui-automation/StepDiagnosisPanel.vue`
- 修改 `backend/app/modules/ui_automation/router.py`（响应包含新字段）
- 修改 `backend/app/modules/ui_automation/schemas.py`

**实现要点**：

1. **步骤详情时间线增强**：
   - 在每条 step 旁边加 4 个徽章：
     - execution_path: 灰=deterministic / 蓝=ai_step_runner / 紫=ai_fallback
     - assertion_method: 绿=deterministic / 蓝=rule / 紫=llm / 橙=triage_external
     - loop_break_reason（仅 ai_step_runner）: 出现时显示
     - match_strategy（仅 assert_text）: exact / contains / loose
   - 鼠标悬浮显示完整字段含义（用 NTooltip）。

2. **locator attempts 折叠展示**：
   - deterministic 失败步骤展开后，显示 `attempts` 列表：每条用例尝试过的
     strategy + count，让用户一眼看出"locator 是因为 0 命中还是 5 命中"。

3. **execution overall 概览卡片**：
   - 增加一行"执行路径分布"：deterministic X / ai_fallback Y / ai_only Z；
     "总 LLM 调用次数"和"总 token 消耗"按路径拆分。

4. **历史对比**：
   - 同一 testcase 过去 N 次执行的步骤通过率折线图；颜色标"deterministic vs
     ai 路径"占比。本期保持简单：直接 SVG sparkline，不引入 charting 库。

**验收标准**：

- 执行详情页能看到所有 4 个新徽章；旧记录字段为 null 时不显示徽章（不报错）。
- locator attempts 折叠区在 fail 步骤上能展开看到 4-5 种策略尝试结果。
- 不影响现有"实时画面"和"视频/trace 下载"功能。
- 中文显示正确，移动端 viewport 也能看（NDescriptions 自适应）。

**风险与回退**：

- 风险：前端新组件引入额外 import 漏掉（NaiveUI 显式 import 模式）。
- 回退：组件逐项加 v-if 判断，字段为 null/undefined 时不渲染该区块即可。


---

## 4. 验收口径与监控

### 4.1 量化指标

每个 task 落地后采样最近 7 天数据，对比 §0 基线：

| 指标 | 基线 | 15.2 | 15.3 | 15.4a | 15.5 | 15.6 | 15.7 | 累计 |
|---|---|---|---|---|---|---|---|---|
| 步骤通过率 | 56.4% | +3pp | +5pp | +5pp | +2pp | +5pp | 0pp | **≥75%** |
| 用例业务通过率 | 39% | +2pp | +4pp | +3pp | +1pp | +3pp | 0pp | **≥55%** |
| 平均 tokens/execution | 33.2w | -8% | -10% | -50% | -2% | 0% | -10% | **≤14w** |
| 平均时长/execution | 7.6 min | -5% | -5% | -10% | -2% | -3% | -15% | **≤4 min** |
| 单步骤 ≥ 5 min 占比 | ~12% | -50% | 0% | 0% | 0% | 0% | -80% | **≤2%** |

> 上述每条都是"独立增量"的估计；累计列已扣除部分重叠（同一失败可能被多个 task
> 覆盖，不重复计算）。

### 4.2 必跑回归

每个 task 完成后必须跑：

```bash
./run.sh test backend/tests/ui_automation/
./run.sh test backend/tests/dashboard/
./run.sh lint && ./run.sh typecheck
./run.sh docker-smoke           # 视情况，特别是 15.1 / 15.7 / 15.10 必跑
```

### 4.3 数据快照存档

每个 task 在 commit message 末尾贴一行快照（用 §6 SQL 查询出来的 4 个数字）：

```text
metrics-before: passes=145/257 (56.4%) avg_tokens=332077 avg_dur=456s
metrics-after:  passes=170/280 (60.7%) avg_tokens=298410 avg_dur=412s
```

便于 review 时直接看到效果。

---

## 5. 不在本期范围

明确**不**做以下事，避免 task 失焦：

- 不引入向量库 / RAG / 长期记忆。
- 不引入 Selenium Grid / 浏览器云。
- 不重写 plan_compiler 为"AI 全量生成 plan"——本期只补规则编译漏洞。
- 不做视觉坐标点击 / OCR 主路径。
- 不动 BrowserBundle / MCP 桥接 / X11/noVNC 这层基础设施。
- 不提供"根据失败自动改用例"的写回功能（数据风险大）。
- 不做跨 testcase 学习的 skill 自动生成。

---

## 6. 数据查询参考（§0 基线）

> 都是只读 SQL；任何 task 验收时按相同口径执行后对比即可。

```sql
-- 查询 1：执行总体（与 §0 表格对应）
SELECT 
  COUNT(*) AS total_executions,
  SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
  SUM(total_cases) AS sum_cases,
  SUM(passed_cases) AS sum_passed,
  SUM(failed_cases) AS sum_failed,
  ROUND(AVG(duration_ms)/1000.0, 1) AS avg_dur_s,
  ROUND(AVG(tokens_total)::numeric, 0) AS avg_tokens
FROM ui_executions
WHERE created_at > NOW() - INTERVAL '30 days';

-- 查询 2：步骤级失败原因聚合
SELECT COUNT(*) AS cnt, LEFT(assertion_reason, 120) AS reason
FROM ui_step_results
WHERE assertion_passed=false AND created_at > NOW() - INTERVAL '30 days'
GROUP BY reason ORDER BY cnt DESC LIMIT 20;

-- 查询 3：执行路径分布（依赖 15.1 落库的 execution_path 字段）
SELECT 
  execution_path,
  status,
  COUNT(*) AS cnt
FROM ui_step_results
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY execution_path, status
ORDER BY execution_path, cnt DESC;

-- 查询 4：高频失败步骤（按 description 聚合）
SELECT 
  LEFT(description, 80) AS step_desc,
  COUNT(*) AS attempts,
  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
  ROUND(100.0 * SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) / COUNT(*), 0) AS fail_pct,
  ROUND(AVG(duration_ms)/1000.0, 1) AS avg_dur_s,
  ROUND(AVG(jsonb_array_length(tool_calls::jsonb))::numeric, 1) AS avg_toolcalls
FROM ui_step_results
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY step_desc HAVING COUNT(*) >= 3
ORDER BY failed DESC, fail_pct DESC LIMIT 15;

-- 查询 5：高频失败用例（同一 testcase 重跑稳定度）
SELECT 
  testcase_id,
  COUNT(*) AS attempts,
  SUM(CASE WHEN status='passed' THEN 1 ELSE 0 END) AS passed,
  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
FROM ui_case_results
WHERE created_at > NOW() - INTERVAL '30 days'
  AND testcase_id IS NOT NULL
GROUP BY testcase_id
HAVING COUNT(*) >= 2
ORDER BY attempts DESC LIMIT 20;

-- 查询 6：零工具长耗时失败（reasoning 幻觉征兆）
SELECT id, description, duration_ms, tokens_used,
       jsonb_array_length(tool_calls::jsonb) AS tc_count,
       LEFT(assertion_reason, 100) AS reason
FROM ui_step_results
WHERE status='failed'
  AND duration_ms > 30000
  AND jsonb_array_length(tool_calls::jsonb) <= 2
  AND created_at > NOW() - INTERVAL '7 days'
ORDER BY duration_ms DESC LIMIT 20;
```

---

## 7. 进度追踪

每个 task 落地后请在此表打勾，并在右侧记录关键数据点。

| Task | 状态 | PR / Commit | 落地日期 | metrics-after 摘要 |
|---|---|---|---|---|
| 15.1 | ✅ | 主分支待提交 | 2026-05-29 | 主仓基线整改 + `ui_step_results` 加 4 列诊断字段 (`execution_path` / `fallback_reason` / `loop_break_reason` / `assertion_method`)；alembic `15a1d100c4b1` |
| 15.2 | ✅ | 主分支待提交 | 2026-05-29 | StepRunner reasoning 漂移恢复（`UI_REASONING_DRIFT_RECOVERY`），`tests/ui_automation/test_step_reasoning_drift.py` |
| 15.3 | ✅ | 主分支待提交 | 2026-05-29 | 动作后等待 + 表格断言 polling（`UI_POST_ACTION_WAIT_MAX_MS`），`tests/ui_automation/test_post_action_wait.py` |
| 15.4a | ✅ | 主分支待提交 | 2026-05-29 | `hybrid_lightweight` 不再隐式回退 AI；`hybrid_lightweight_with_fallback` 显式启用，`tests/ui_automation/test_fallback_gating.py` |
| 15.4b | ✅ | 主分支待提交 | 2026-05-29 | strict-JSON `decide_self_heal_action` 自愈循环（`UI_AI_FALLBACK_SELF_HEAL`），`tests/ui_automation/test_self_heal_loop.py` |
| 15.5 | ✅ | 主分支待提交 | 2026-05-29 | 占位符严格模式 + 用例质量校验（plan_compiler 未解析占位符编为 `UNSUPPORTED`） |
| 15.6 | ✅ | 主分支待提交 | 2026-05-29 | locator anchor-based + label 同义词 + assert_text 三级降级（`UI_LOCATOR_ANCHOR_BASED` / `UI_ASSERT_TEXT_DEGRADE_LEVEL`），`test_assert_text_degrade.py` / `test_locator_candidates.py` |
| 15.7 | ✅ | 主分支待提交 | 2026-05-29 | 单步 token 软上限 + 三个早停信号（`UI_LOOP_GUARD_*`），`tests/ui_automation/test_step_loop_guard.py` |
| 15.8 | ✅ | 主分支待提交 | 2026-05-29 | 反爬命中早停（`UI_EARLY_TERMINATE_ON_CAPTCHA`）+ Dashboard 高频失败用例卡（`UI_UNSTABLE_CASE_*`），`tests/dashboard/test_case_stability.py` |
| 15.9 | ✅ | 主分支待提交 | 2026-05-29 | 新增 `successful_locators` jsonb；engine 读最近 N 次成功 case 交集 + miss 累计自愈；`UI_LOCATOR_MEMORY` 默认 ON。`tests/ui_automation/test_locator_memory.py` 21 个用例全过；ui_automation 全套 752 通过 |
| 15.10 | ✅ | 主分支待提交 | 2026-05-29 | 后端补 `loop_break_reason` / `assertion_method` schema；前端新增 `StepDiagnosisPanel.vue` 渲染 4 徽章 + locator attempts 折叠；执行详情新增执行路径分布条；vue-tsc / 后端 975 全过 |
| 15.11 | ✅ | fix/15.11-replan-after-synth | 2026-06-01 | 占位符自造后重编 plan：`_materialize_missing_case_placeholders` 之后再调一次 `_compile_hybrid_plan_steps`，把原本因动态 key 缺失而被编为 `UNSUPPORTED` 的 fill/click step 升级回 deterministic；新增 `_merge_replanned_compiled_steps` 合并函数（仅覆盖 UNSUPPORTED，不动已识别 step）+ `tests/ui_automation/test_replan_after_synth.py` 4 个用例；ui_automation 756 全过 |
| 15.12 | ✅ | fix/15.12-field-match | 2026-06-01 | 修复 `_find_referenced_field` 把"语义兜底"和"精确 token 子串"混在同一遍循环导致 input 字段被错误命中的 bug（现场 #c5332835 case 4 step 2 — expected="创作者名称输入框值显示为 测试" 取到 placeholder=创作者ID 字段的 evidence "创作者ID=571222"）；改为两轮：精确 label/placeholder/name 子串优先，语义匹配只在精确全 miss 时兜底；排序 key 加上 placeholder 长度避免文档顺序退化；`tests/ui_automation/test_assertion_rules.py` 新增 3 个单测；ui_automation 759 全过 |
| 15.13 | ✅ | fix/15.13-expected-columns | 2026-06-01 | 修复 `_extract_expected_columns` 尾从句切分白名单只覆盖"顺序/位置/样式/显示"等关键词导致"且 / 同时 / 并 / 以及"等连接词从句被 `_SPLIT_RE` 当成第 N+1 个伪列名（现场 #60ec5996 case 2 step 2 报"表格列缺失：且这7列均位于「创建时间」列之前"假阳性）；扩展切分白名单 + `_clean_expected_column_label` 加第二道防线丢弃含"位于/之前/之后/这N列"等位置短语 + 长度>12 含子句词的内容；`tests/ui_automation/test_assertion_rules.py` 新增 4 个单测；ui_automation 763 全过 |

---

## 8. Phase 15.11 — 占位符自造后重编 plan（后置补丁）

### 15.11.1 背景：批次 #85134af4 验收暴露的根因

执行批次 `85134af4-02d4-4b14-b23b-28f1e4e71f33` 的现场:

| Case | 状态 | 路径 | 步数 | tokens | 耗时 |
|---|---|---|---|---|---|
| 54cf61b2 (无占位符) | passed | deterministic 全程 | 1 | 0 | 3.5s |
| 5601aae6 (`{{existing_creator_id}}`) | failed | **全程 ai_only** | 2 | 78 969 | 80s |
| dd82a693 (`{{creator_id_1/2}}`) | passed (synthesized) | **全程 ai_only** | 2 | 57 045 | 53s |
| 1e97e64e (`{{creator_id_combined}}` `{{name_keyword}}`) | failed | **全程 ai_only** | 3 | 63 141 | 80s |

执行流分析定位到：

1. `_compile_hybrid_plan_steps()` 在 case 启动**最早期**调用，此时占位符尚未自造，
   含 `{{xxx}}` 的 step 被 `_maybe_render_step` 标记为 `UNSUPPORTED("unresolved_placeholder: ...")`；
2. 紧接着 `_materialize_missing_case_placeholders()` 用 `DataSynthesizer` 把缺失 key
   写回 `case_resolver.data`；
3. **但 `hybrid_steps_by_number` 已经定型不会重编**，每个 step 进入
   `_run_step_with_strategy` 时 `compiled_step.kind == UNSUPPORTED`，直接走
   `ai_step_runner`；
4. ai_only 路径下 LLM 通过 a11y snapshot 看不到 input value，反复尝试 →
   `repeated_tool_signature` 早停 → 单步消耗 60k+ token + 断言失败概率高。

> "deterministic→ai_only 大降级"、"token 飙到 200k"、"input value 看不见反复打脸"、
> "LLM 网关空响应"四个症状是同一根因衍生出的连锁反应。

### 15.11.2 改动

**核心**：`_materialize_missing_case_placeholders()` 之后**重编一次 plan**，
合并升级原本 UNSUPPORTED 的 step。

```python
# execution_engine.py — _run_one_case 内
await _materialize_missing_case_placeholders(...)
if deterministic_runner is not None:
    deterministic_runner.variables = _deterministic_variables_from_resolver(...)
    # Phase 15.11: 占位符自造后重编 plan
    _, hybrid_steps_by_number_v2 = _compile_hybrid_plan_steps(
        tc=tc,
        module_entry_url=target_url,
        data_resolver=case_resolver,
    )
    upgraded = _merge_replanned_compiled_steps(
        base=hybrid_steps_by_number,
        fresh=hybrid_steps_by_number_v2,
    )
```

新增辅助函数 `_merge_replanned_compiled_steps()` 合并策略：

- 只覆盖原 UNSUPPORTED 的 step（避免误覆盖已识别成功的判定）
- 新结果仍是 UNSUPPORTED 的不入合并（保留首轮 reason 方便审计）
- `base` 中没有但 `fresh` 中有的新 step 直接添加（兼容 plan 结构变化）
- 任何异常都记 warning 静默退化为旧行为，不让重编机制把执行链路打挂

### 15.11.3 验收

- 单测 `tests/ui_automation/test_replan_after_synth.py` 4 用例覆盖:
  - 双次 compile_action_plan 的升级链路
  - merge 函数：仅覆盖 UNSUPPORTED / 跳过仍 UNSUPPORTED / 添加新增 step
- ui_automation 全量回归 **756 passed, 1 skipped**
- ruff 0 错

### 15.11.4 预期收益（按 #85134af4 case 推算）

| 维度 | 修前 | 修后预期 |
|---|---|---|
| 4 case 总 token | 199 155 | < 5 000 (deterministic 0 token) |
| 4 case 总耗时 | 237.6s | < 30s |
| ai_only step 占比 | 7/8 (87.5%) | 0/8 |
| 由 a11y snapshot 看不见 input value 引发的误判 | 频发 | 消失（deterministic 用 form_fields 结构化证据） |

> 可观测：`tc=<id> upgraded steps=[1,2,...]` 的 INFO 日志，能直接核对哪些 step
> 在重编时被升级。

---

## 9. Phase 15.12 — 表单字段匹配错绑修复（精准命中 vs 语义兜底优先级）

### 9.1 现场 #c5332835 case 4 step 2

Phase 15.11 修复后的首次回归批次：4 case 共 21s / 0 token, 全部 deterministic
路径。但仍有一条 case 失败：

| 字段 | 内容 |
|---|---|
| description | `在「创作者名称」输入框输入 测试` |
| expected | `创作者名称输入框值显示为 测试` |
| assertion_method | `text_search` |
| assertion_passed | `false` |
| assertion_reason | `输入框值不匹配` |
| **assertion_evidence** | **`创作者ID=571222`** ← 严重错对字段 |

`form_fields` 数据本身完全正确：

```text
fields[0]: placeholder=创作者ID,   value=571222   (step 1 填进去的)
fields[1]: placeholder=创作者名称, value=测试     (step 2 刚填进去的)
```

但断言时 `_find_referenced_field` 取出的是 `fields[0]` (创作者ID)，
拿它的 value=571222 跟期望 "测试" 比对，结果当然不一致。

### 9.2 根因

`backend/app/modules/ui_automation/assertion_rules.py:_find_referenced_field`
旧实现把"具体 label/placeholder/name 子串匹配"和"语义兜底匹配
(`_field_matches_semantic_reference`)" **写在同一遍循环里**：

```python
for field in candidates:
    for token in (field.label, field.name, field.placeholder):
        if token and _normalize_text(token) in normalized_expected:
            return field
    if _field_matches_semantic_reference(field, normalized_expected):
        return field
return None
```

`_field_matches_semantic_reference` 在 expected 含 "输入框" 时退化成
"任何 input 类元素都匹中"。第一个字段 (placeholder=创作者ID) 因为是 input
立刻被语义匹配命中并 return，第二个字段 (placeholder=创作者名称) 即使有更精确
的 placeholder 子串命中也再没机会被检查。

附加问题：排序 key `len(field.label or field.name)` 忽略了 placeholder 长度，
中后台表单很多 input 没有 label/name 全靠 placeholder 区分时排序退化为
文档顺序，进一步加剧误绑。

### 9.3 改动

`_find_referenced_field` 重写为两轮：

```python
def _find_referenced_field(expected: str, evidence: FormFieldsEvidence):
    candidates = sorted(
        evidence.fields,
        key=lambda field: len(field.label or field.placeholder or field.name or ""),
        reverse=True,
    )
    normalized_expected = _normalize_text(expected)

    # 第一轮: 精确 token 子串匹配 (label / placeholder / name)
    for field in candidates:
        for token in (field.label, field.placeholder, field.name):
            if token and _normalize_text(token) in normalized_expected:
                return field

    # 第二轮: 精确全 miss 后才用语义兜底
    for field in candidates:
        if _field_matches_semantic_reference(field, normalized_expected):
            return field
    return None
```

### 9.4 验收

- `tests/ui_automation/test_assertion_rules.py` 新增 3 个用例：
  - `does_not_misroute_to_first_input_when_placeholder_is_specific` — 现场复现
    回归
  - `does_not_misroute_creator_id_to_creator_name` — 反向不回归 (expected
    指 ID 字段时不应被名称字段抢走)
  - `falls_back_to_semantic_reference_when_no_token_match` — 语义兜底仍可用
    (expected="搜索框值显示为 北京" 命中 type=search 字段)
- ui_automation **759 passed / 1 skipped** (+3 来自 15.12)
- ruff 0 错

### 9.5 影响面

- 修复后 #c5332835 case 4 应能跑通 (step 2 命中 `placeholder=创作者名称` 字段
  返回 evidence `创作者名称=测试`，断言通过；step 3 因为 step 2 不再卡死
  也能正常进入查询)
- 所有依赖 `_find_referenced_field` 的下游：`assert_form_values` 的多个分支
  (空值校验 / display_value / readonly / input_value / column_value) 均自动
  受益，不会再被语义兜底强占第一个 input 字段

---

## 10. Phase 15.13 — 表格列名提取剔除尾从句噪音

### 10.1 现场 #60ec5996 case 2 step 2

| 字段 | 内容 |
|---|---|
| description | `观察「店铺列表」表格的列头从左到右顺序` |
| expected | `表格列名包含：提现银行账户、（分录）科目编码、（分录）科目名称、（分录）商户号编码、（分录）商户号名称、（分录）部门编码、（分录）部门名称，且这7列均位于「创建时间」列之前` |
| assertion_reason | **`表格列缺失：且这7列均位于「创建时间」列之前`** |
| evidence | `表格列 34 个：ID、公司主体、电商平台、店铺ID、店铺名称、登录账户、登录密码、账户状态...` |

实际 actual 列里 7 个新增列**全部都在**, 但断言报"列缺失：且这7列均位于「创建时间」列之前"
— 显然把 expected 的尾从句当成列名了。

### 10.2 根因

`_extract_expected_columns` 走两步:

1. 先用 `re.split(r"[，,；;。]\s*(?:括号及文字|无歧义|顺序|位置|样式|显示|展示)\S*", ...)`
   切尾从句，只保留主体列举部分。
2. 再用 `_SPLIT_RE = re.compile(r"[、,，;；/\n]+")` 把主体按"、/，"切成单列。

第 1 步白名单只覆盖"顺序/位置/样式/显示/展示/括号及文字/无歧义"等关键词起头的从句，
"**且**这7列均位于「创建时间」列之前"以**连接词"且"**起头，没匹中白名单 → 不切。

第 2 步把"（分录）部门名称**，**且这7列均位于..."沿"，"切成两段：

```text
（分录）部门名称
且这7列均位于「创建时间」列之前    ← 被当成第 8 个伪列名
```

最终 `assert_table_columns` 比对：前 7 个真实列名都在 actual 里，第 8 个"且这7列均位于..."
不在 → 走 missing 分支，输出 `表格列缺失：且这7列均位于「创建时间」列之前`。

### 10.3 改动

两层防线（assertion_rules.py）：

**防线 1 — 切分白名单扩展**

```python
raw = re.split(
    r"[，,；;。]\s*"
    r"(?:括号及文字|无歧义|顺序|位置|样式|显示|展示"
    r"|且|同时|并|以及|而且|另外|此外|其中)"   # 新增连接词
    r"\S*",
    match.group("cols"),
    maxsplit=1,
)[0]
```

**防线 2 — `_clean_expected_column_label` 单元清洗增强**

```python
# 即便上游切分漏过, 这里识别"看起来是描述句而非列名"的内容直接丢:
if re.search(r"位于|之前|之后|这\d+列|^且|均位于", cleaned):
    return ""
if len(cleaned) > 12 and re.search(
    r"且|均|包含|完整|可见|对齐|无遮挡|未截断", cleaned
):
    return ""
```

真实列名罕见包含"位于/之前/之后/均/这\d+列"等位置/数量短语；列名极少超 12 字、
即便有也不会同时含子句连接词。

### 10.4 验收

`tests/ui_automation/test_assertion_rules.py` 新增 4 个单测：

- `test_extract_expected_columns_strips_position_clause_with_qie_connector` —
  现场 #60ec5996 字面回归，期望取出 7 个干净列名
- `test_extract_expected_columns_strips_other_connector_clauses` — 覆盖"同时
  / 并且 / 以及 / 此外"四种连接词变体
- `test_extract_expected_columns_keeps_simple_listing_unchanged` — 反向不
  回归：普通列举式不能被新规则误伤
- `test_assert_table_columns_passes_after_phase_15_13_fix` — 端到端：现场
  expected 配真实表头 → 断言应通过

`ui_automation` 全量回归 **763 passed / 1 skipped** (+4 来自 15.13)，ruff 0 错。

### 10.5 影响面

- `#60ec5996` case 2 step 2 应直接由 failed → passed
- 同类用例（"...，且/同时/并/以及 ... 之前/之后/位于..."）此前都会假阳性，
  现在统一走主体列举比对
- 任何 expected 文本里残留的"看起来是子句"的伪列名会被防线 2 兜底丢弃，
  避免下次再出现一个新连接词又复发

### 10.6 同批次其他失败的诊断（不在本次修复范围）

| Case / Step | 失败类型 | 性质 | 对策建议 |
|---|---|---|---|
| case 2 sort=2 / step 3 — 右键菜单 | LLM 写"未捕获到右击后的上下文菜单, 无法判断" | 用例语义"无 X 出现"的负面验证；AI 路径下 LLM 偏保守 | 后续可在 prompt 里强调"未观测到对应入口即视为符合预期" |
| case 3 sort=2 / step 2 — 横向滚动 | `assertion_method=llm_unavailable` LLM 网关空响应 | 基础设施故障 + 步骤含"如果...就..."条件性表述 | 网关重试策略；plan_compiler 可考虑识别"如果"开头的步骤为可跳过 |

这两类不属于本次"表达式解析"性 bug，留作后续单独评估。

---

## 11. 下一步建议

按 §2 顺序，**下一次开发会话从 Task 15.1 开始**：把当前 untracked 的
`failure_triage.py` / `api_stats.py` 等成果合入主仓库，并加 4 列步骤诊断字段，
为后续所有 task 建立可量化的对比基线。15.1 风险最低（不动业务逻辑），但
**它是其它所有 task 的前置条件**——没有这些诊断字段落库，后面任何 task 完工
后都无法量化"修了多少"。

15.1 完成后建议并行推进 15.2 / 15.3 / 15.5 / 15.6（彼此独立、能拆 subagent
worktree 并行落地）；15.4a / 15.4b / 15.7 因为依赖前几个的产出，建议串行
推进。
