import { ref, computed } from "vue";
import {
  chatSystemEventsUrl,
  createSessionApi,
  deleteSessionApi,
  getPendingTaskSummaryApi,
  getSessionDetailApi,
  getSessionsApi,
  startChatTaskApi,
  updateSessionApi,
  uploadFileApi,
} from "@/services/chat";
import type {
  ChatMessage,
  ChatSession,
  FileUploadResult,
  PendingTaskSummary,
} from "@/services/chat";
import type { SkillActivatedEvent } from "@/services/skills";
import type {
  ExecutionPlanCard,
  TaskBadgeMeta,
} from "@/components/skills/types";
import {
  applyTaskBadgePatch,
  transformPlanMessageToTaskBadge,
} from "./useExecutionPlan";
import { refreshAllTaskBadges } from "./useTaskBadgeAutoRefresh";
import { useSSE } from "./useSSE";

export interface PendingFile {
  id: string;
  file: File;
  status: "uploading" | "done" | "error";
  result?: FileUploadResult;
  error?: string;
}

/** 单个会话当前正在生成中的内容快照。 */
export interface StreamingState {
  /** 触发本次流的会话 id；用于切换会话时按 sessionId 区分。 */
  sessionId: string;
  /** 模型正文增量（markdown 原文）。 */
  content: string;
  /** 模型思考链增量（reasoning_content）。 */
  reasoning: string;
  /** 状态/提示信息（联网中、生成中…），按顺序追加。 */
  infos: string[];
  /** action 事件携带的结构化业务 meta（如 fix_action）。 */
  meta: Record<string, unknown> | null;
}

const EMPTY_STREAM: StreamingState = {
  sessionId: "",
  content: "",
  reasoning: "",
  infos: [],
  meta: null,
};

const SESSION_PAGE_SIZE = 50;

function emptyStream(sessionId = ""): StreamingState {
  return { sessionId, content: "", reasoning: "", infos: [], meta: null };
}

export function useChat() {
  const sessions = ref<ChatSession[]>([]);
  const currentSessionId = ref<string | null>(null);
  /**
   * 每个会话独立保存自己的消息列表，切回去能立刻复用、不需要重新 fetch；
   * 也避免会话 A 还在流式生成时，切到会话 B 再切回 A 看到"答案丢失"。
   */
  const messagesBySession = ref<Record<string, ChatMessage[]>>({});
  /**
   * Phase 12 / Task 12.6 — 最近一条 skill_activated SSE 事件。
   * 仅当当前会话产生时才会被赋值；ChatView 把它 watch 给 SkillActivationHint。
   */
  const latestSkillActivation = ref<SkillActivatedEvent | null>(null);
  /** 各会话独立的流式中间态：切到 B 再切回 A 时还能看到 A 正在生成的内容。 */
  const streamsBySession = ref<Record<string, StreamingState>>({});
  /** 各会话独立的"是否在流式中"，用于停止按钮和"是否要在会话列表上显示动画"。 */
  const streamingSessions = ref<Record<string, boolean>>({});
  const isLoadingSessions = ref(false);
  const isLoadingMoreSessions = ref(false);
  const sessionPage = ref(1);
  const sessionTotal = ref(0);
  const isLoadingMessages = ref(false);
  const pendingFiles = ref<PendingFile[]>([]);

  const { fetchSSE } = useSSE();

  /** 每个会话当前的中断句柄；切到别的会话不再 abort，让上一路自然跑完。 */
  const abortHandles: Record<string, () => void> = {};

  // ─── Phase 13 / Task 13.3 — 系统事件流 / pending 汇总 ───────────────────
  /** 各会话当前的 system-events SSE 中断句柄。 */
  const systemEventAborts: Record<string, () => void> = {};
  /** 首屏顶部"你离开期间完成 N 个任务"汇总。null = 未加载 / 不需展示。 */
  const pendingSummary = ref<PendingTaskSummary | null>(null);
  /** 顶栏小铃铛未读计数；execution_event 来一条 +1，用户点开列表后清零。 */
  const unreadEvents = ref(0);

  const currentSession = computed(() =>
    sessions.value.find((s) => s.id === currentSessionId.value) ?? null,
  );

  const hasMoreSessions = computed(
    () => sessions.value.length > 0 && sessions.value.length < sessionTotal.value,
  );

  const messages = computed<ChatMessage[]>(() =>
    currentSessionId.value
      ? messagesBySession.value[currentSessionId.value] || []
      : [],
  );

  /** 当前会话当前的流式快照（无流时是空对象，渲染层据此判断是否显示"正在生成"气泡）。 */
  const streaming = computed<StreamingState>(() => {
    const sid = currentSessionId.value;
    if (!sid) return { ...EMPTY_STREAM };
    return streamsBySession.value[sid] || { ...EMPTY_STREAM };
  });

  /** 当前会话是否处于流式中（用于禁用输入框/显示停止按钮）。 */
  const isStreaming = computed<boolean>(() => {
    const sid = currentSessionId.value;
    if (!sid) return false;
    return !!streamingSessions.value[sid];
  });

  /** 兼容老调用：当前可见的正文增量。 */
  const streamingContent = computed(() => streaming.value.content);

  function _setStream(sessionId: string, patch: Partial<StreamingState>) {
    const cur =
      streamsBySession.value[sessionId] || emptyStream(sessionId);
    streamsBySession.value = {
      ...streamsBySession.value,
      [sessionId]: { ...cur, sessionId, ...patch },
    };
  }

  function _clearStream(sessionId: string) {
    if (sessionId in streamsBySession.value) {
      const next = { ...streamsBySession.value };
      delete next[sessionId];
      streamsBySession.value = next;
    }
  }

  function _setStreamingFlag(sessionId: string, value: boolean) {
    const next = { ...streamingSessions.value };
    if (value) next[sessionId] = true;
    else delete next[sessionId];
    streamingSessions.value = next;
  }

  function _appendMessage(sessionId: string, msg: ChatMessage) {
    const cur = messagesBySession.value[sessionId] || [];
    messagesBySession.value = {
      ...messagesBySession.value,
      [sessionId]: [...cur, msg],
    };
  }

  /**
   * 把 assistant 消息插入到指定位置；越界 / 未提供时回退到末尾追加。
   *
   * 用于 resumeIfStreaming 续订完成后, 把占位 streaming 消息按原始位置塞回
   * 列表 —— 否则当生成期间 skill_card / execution_event 等 kind 消息已经
   * 在它后面落库时, 简单 append 会让 AI 答案排到系统消息之后, 时间线错乱。
   */
  function _insertOrAppendMessage(
    sessionId: string,
    msg: ChatMessage,
    insertAt?: number,
  ) {
    const cur = messagesBySession.value[sessionId] || [];
    let next: ChatMessage[];
    if (typeof insertAt === "number" && insertAt >= 0 && insertAt <= cur.length) {
      next = [...cur.slice(0, insertAt), msg, ...cur.slice(insertAt)];
    } else {
      next = [...cur, msg];
    }
    messagesBySession.value = {
      ...messagesBySession.value,
      [sessionId]: next,
    };
  }

  function _setMessages(sessionId: string, list: ChatMessage[]) {
    messagesBySession.value = {
      ...messagesBySession.value,
      [sessionId]: list,
    };
  }

  // ─── Phase 13 / Task 13.3 — message kind 操作 ───────────────────────────

  /**
   * ConfirmationCard "确认执行"成功后调用：把同一条 skill_card 消息原地变身
   * 为 task_badge（同 message_id），输入框立即可用，用户能继续聊别的；后台
   * 任务通过 system-events SSE 增量更新进度，完成时另起一条 execution_event
   * 在末尾追加。
   */
  function applyPlanConfirmation(
    sessionId: string,
    payload: {
      messageId: string;
      taskId: string;
      plan: ExecutionPlanCard;
    },
  ) {
    const list = messagesBySession.value[sessionId] || [];
    const next = transformPlanMessageToTaskBadge(list, payload);
    _setMessages(sessionId, next);
  }

  /** ConfirmationCard 取消折叠：本地标记 meta_data.cancelled=true，UI 上隐藏按钮即可。 */
  function applyPlanCancel(sessionId: string, messageId: string) {
    const list = messagesBySession.value[sessionId] || [];
    const next = list.map((m) =>
      m.id === messageId
        ? {
            ...m,
            meta_data: { ...(m.meta_data || {}), cancelled: true },
          }
        : m,
    );
    _setMessages(sessionId, next);
  }

  /** TaskBadge 自身刷新成功后回写 meta（status / 进度 / 耗时）。 */
  function applyTaskBadgePatchByMessage(
    sessionId: string,
    messageId: string,
    patch: Partial<TaskBadgeMeta>,
  ) {
    const list = messagesBySession.value[sessionId] || [];
    const next = list.map((m) => {
      if (m.id !== messageId) return m;
      return {
        ...m,
        meta_data: { ...(m.meta_data || {}), ...patch },
      };
    });
    _setMessages(sessionId, next);
  }

  /** SSE task_status / 离线刷新拿到进度后按 task_id 批量更新。 */
  function patchTaskBadgeByTaskId(
    sessionId: string,
    taskId: string,
    patch: Partial<TaskBadgeMeta>,
  ) {
    const list = messagesBySession.value[sessionId] || [];
    const next = applyTaskBadgePatch(list, taskId, patch);
    if (next !== list) {
      _setMessages(sessionId, next);
    }
  }

  async function loadSessions(projectId?: string) {
    isLoadingSessions.value = true;
    let sessionToSelect: string | null = null;
    try {
      const res = await getSessionsApi(projectId, 1, SESSION_PAGE_SIZE);
      if (res.success) {
        sessions.value = res.data.items;
        sessionPage.value = res.data.page;
        sessionTotal.value = res.data.total;
        const currentStillExists =
          currentSessionId.value &&
          sessions.value.some((s) => s.id === currentSessionId.value);
        if (!currentStillExists) {
          const latest = sessions.value[0];
          if (latest) {
            sessionToSelect = latest.id;
          } else {
            currentSessionId.value = null;
          }
        } else if (currentSessionId.value) {
          // 路由切出去再切回来 / 组件 remount 时，currentSessionId 可能还在
          // （pinia / composable 保留），但消息列表也早就在本地缓存里。
          // 这种情况 selectSession 不会再跑，需要我们手动检查一下：
          // 如果最后一条 assistant 还在 streaming，就把它续上。
          if (!messagesBySession.value[currentSessionId.value]?.length) {
            // 消息没缓存（例如 pinia 保留了 id 但首次拉 list）——拉一次详情。
            sessionToSelect = currentSessionId.value;
          } else {
            resumeIfStreaming(currentSessionId.value);
          }
        }
      }
    } finally {
      isLoadingSessions.value = false;
    }
    if (sessionToSelect) {
      await selectSession(sessionToSelect, { force: true });
    }
  }

  async function loadMoreSessions(projectId?: string) {
    if (isLoadingMoreSessions.value || !hasMoreSessions.value) return;
    isLoadingMoreSessions.value = true;
    try {
      const nextPage = sessionPage.value + 1;
      const res = await getSessionsApi(projectId, nextPage, SESSION_PAGE_SIZE);
      if (res.success) {
        const seen = new Set(sessions.value.map((s) => s.id));
        const nextItems = res.data.items.filter((s) => !seen.has(s.id));
        sessions.value = [...sessions.value, ...nextItems];
        sessionPage.value = res.data.page;
        sessionTotal.value = res.data.total;
      }
    } finally {
      isLoadingMoreSessions.value = false;
    }
  }

  async function selectSession(sessionId: string, options?: { force?: boolean }) {
    if (currentSessionId.value === sessionId && !options?.force) return;
    // 关键：不要中断流也不要清掉旧会话的 streaming/messages，
    // 这样切回去还能看到上次正在写的内容。
    currentSessionId.value = sessionId;

    // 已经有缓存就不重新拉了，避免覆盖正在 push 的本地消息
    if (messagesBySession.value[sessionId]?.length) {
      // 已有本地缓存时，仍然尝试 resume（比如刷新后第一次从 SPA 内切回来）。
      resumeIfStreaming(sessionId);
      return;
    }

    isLoadingMessages.value = true;
    try {
      const res = await getSessionDetailApi(sessionId);
      if (res.success) {
        _setMessages(sessionId, res.data.messages);
        // 刷新 / 首次���载后：若最后一条 assistant 还是 streaming 状态，
        // 直接把后台任务续订回前端。
        resumeIfStreaming(sessionId);
      }
    } finally {
      isLoadingMessages.value = false;
    }
  }

  async function createNewSession(llmConfigId?: string, projectId?: string, systemPrompt?: string) {
    const res = await createSessionApi({
      llm_config_id: llmConfigId,
      project_id: projectId,
      system_prompt: systemPrompt,
    });
    if (res.success) {
      sessions.value.unshift(res.data);
      _setMessages(res.data.id, []);
      await selectSession(res.data.id);
      return res.data;
    }
    return null;
  }

  async function deleteSession(sessionId: string) {
    const res = await deleteSessionApi(sessionId);
    if (res.success) {
      sessions.value = sessions.value.filter((s) => s.id !== sessionId);
      if (streamingSessions.value[sessionId]) {
        abortHandles[sessionId]?.();
      }
      delete abortHandles[sessionId];
      unsubscribeSystemEvents(sessionId);
      _setStreamingFlag(sessionId, false);
      _clearStream(sessionId);
      const next = { ...messagesBySession.value };
      delete next[sessionId];
      messagesBySession.value = next;
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = null;
      }
    }
  }

  async function renameSession(sessionId: string, title: string) {
    const res = await updateSessionApi(sessionId, { title });
    if (res.success) {
      const idx = sessions.value.findIndex((s) => s.id === sessionId);
      if (idx >= 0) sessions.value[idx] = { ...sessions.value[idx], ...res.data };
    }
  }

  /** 将一段已渲染的 system prompt 同步到当前会话；切换 prompt 后应立即生效。 */
  async function applySystemPrompt(systemPrompt: string | null) {
    if (!currentSessionId.value) return;
    const res = await updateSessionApi(currentSessionId.value, {
      system_prompt: systemPrompt ?? "",
    });
    if (res.success) {
      const idx = sessions.value.findIndex((s) => s.id === currentSessionId.value);
      if (idx >= 0) sessions.value[idx] = { ...sessions.value[idx], ...res.data };
    }
  }

  async function addFile(file: File) {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const pending: PendingFile = { id, file, status: "uploading" };
    pendingFiles.value.push(pending);

    try {
      const res = await uploadFileApi(file);
      if (res.success) {
        pending.status = "done";
        pending.result = res.data;
      } else {
        pending.status = "error";
        pending.error = "上传失败";
      }
    } catch (err: unknown) {
      pending.status = "error";
      pending.error =
        err instanceof Error ? err.message : "上传失败";
    }
  }

  function removeFile(id: string) {
    pendingFiles.value = pendingFiles.value.filter((f) => f.id !== id);
  }

  function clearFiles() {
    pendingFiles.value = [];
  }

  function _buildContent(text: string): string {
    const doneFiles = pendingFiles.value.filter(
      (f) => f.status === "done" && f.result,
    );
    if (doneFiles.length === 0) return text;

    const parts: string[] = [];
    for (const f of doneFiles) {
      if (f.result!.type === "document" && f.result!.text) {
        parts.push(
          `[附件: ${f.result!.filename}]\n\`\`\`\n${f.result!.text.slice(0, 15000)}\n\`\`\``,
        );
      } else if (f.result!.type === "image") {
        parts.push(`[图片: ${f.result!.filename}]`);
      }
    }

    if (parts.length > 0) {
      return `${parts.join("\n\n")}\n\n${text}`;
    }
    return text;
  }

  /**
   * 订阅某条 assistant 消息的生成流；断开 / 切页 / 刷新后重新调用同样的 id
   * 就能接着拿到后续事件 + 最终内容。
   *
   * 关键设计：
   *   - 订阅过程不再"创建消息"，它只是"看已经在后台跑的那条"。
   *   - abort() 仅断开当前 HTTP 连接，不影响后台任务。
   *   - 订阅结束（done / error / abort）后，才把累积的 content 落成正式
   *     assistant 消息，合并进 messagesBySession。
   */
  function _subscribeAssistantMessage(opts: {
    sessionId: string;
    assistantMsgId: string;
    /** 用于 streaming 期间在会话列表上显示更新时间 / 预览标题。 */
    userText: string;
    /** 订阅前已经累积的 content（从已保存的占位消息里拿到的）。 */
    initialContent?: string;
    initialReasoning?: string;
    /**
     * resumeIfStreaming 把 streaming 占位摘掉时记录的原始下标; finalize 后
     * 按此位置塞回列表, 避免 append 到末尾打乱时间线。未提供则按末尾追加。
     */
    insertAt?: number;
  }) {
    const {
      sessionId,
      assistantMsgId,
      userText,
      initialContent,
      initialReasoning,
      insertAt,
    } = opts;

    _setStreamingFlag(sessionId, true);
    _setStream(sessionId, {
      content: initialContent || "",
      reasoning: initialReasoning || "",
      infos: [],
      meta: null,
    });

    let finished = false;
    const finalize = (errorMsg?: string) => {
      if (finished) return;
      finished = true;

      const stream =
        streamsBySession.value[sessionId] || emptyStream(sessionId);
      const meta: Record<string, unknown> = { ...(stream.meta || {}) };
      if (stream.reasoning) meta.reasoning = stream.reasoning;
      const metaData = Object.keys(meta).length ? meta : null;

      if (stream.content) {
        const trailingError = errorMsg ? `\n\n> ⚠️ ${errorMsg}` : "";
        _insertOrAppendMessage(
          sessionId,
          {
            id: assistantMsgId,
            session_id: sessionId,
            role: "assistant",
            content: stream.content + trailingError,
            tokens_used: null,
            model_used: null,
            meta_data: metaData,
            created_at: new Date().toISOString(),
          },
          insertAt,
        );
      } else if (errorMsg) {
        _insertOrAppendMessage(
          sessionId,
          {
            id: assistantMsgId,
            session_id: sessionId,
            role: "assistant",
            content: `> ⚠️ ${errorMsg}`,
            tokens_used: null,
            model_used: null,
            meta_data: null,
            created_at: new Date().toISOString(),
          },
          insertAt,
        );
      }

      const idx = sessions.value.findIndex((s) => s.id === sessionId);
      if (idx >= 0) {
        const session = sessions.value[idx];
        sessions.value[idx] = {
          ...session,
          updated_at: new Date().toISOString(),
          title:
            session.title === "新对话" && userText
              ? userText.slice(0, 50) || "新对话"
              : session.title,
        };
        const [updated] = sessions.value.splice(idx, 1);
        sessions.value.unshift(updated);
      }

      _setStreamingFlag(sessionId, false);
      _clearStream(sessionId);
    };

    const handle = fetchSSE(
      `/api/chat/messages/${assistantMsgId}/stream`,
      null,
      {
        onDelta(delta) {
          const cur = streamsBySession.value[sessionId] || emptyStream(sessionId);
          _setStream(sessionId, { content: cur.content + delta });
        },
        onReasoning(reason) {
          const cur = streamsBySession.value[sessionId] || emptyStream(sessionId);
          _setStream(sessionId, { reasoning: cur.reasoning + reason });
        },
        onInfo(message) {
          const cur = streamsBySession.value[sessionId] || emptyStream(sessionId);
          _setStream(sessionId, { infos: [...cur.infos, message] });
        },
        onAction(actionContent, meta) {
          // action 事件 content 是该轮意图的最终内容，覆盖（而不是追加）。
          _setStream(sessionId, { content: actionContent, meta });
        },
        onEvent(event) {
          // Task 12.6 — 后端推 ``skill_activated`` 事件时，仅当对应是当前
          // 可见会话时再亮出 banner，避免后台另一会话的激活提示干扰用户。
          if (
            event.type === "skill_activated" &&
            sessionId === currentSessionId.value
          ) {
            const skillId = String(event.skill_id ?? "");
            const slug = String(event.slug ?? "");
            const name = String(event.name ?? "");
            const reason = String(event.activation_reason ?? "manual") as
              SkillActivatedEvent["activation_reason"];
            if (skillId && slug && name) {
              latestSkillActivation.value = {
                skill_id: skillId,
                slug,
                name,
                activation_reason: reason,
                matched_trigger:
                  typeof event.matched_trigger === "string"
                    ? event.matched_trigger
                    : null,
              };
            }
          }
        },
        onError(msg) {
          finalize(msg);
        },
        onDone() {
          finalize();
        },
      },
      { method: "GET" },
    );
    abortHandles[sessionId] = handle.abort;
    void handle.promise.finally(() => {
      if (abortHandles[sessionId] === handle.abort) {
        delete abortHandles[sessionId];
      }
    });
    return handle;
  }

  async function sendMessage(text: string, llmConfigId?: string) {
    if (!currentSessionId.value) return;
    const sessionId = currentSessionId.value;
    if (streamingSessions.value[sessionId]) return;

    const content = _buildContent(text);
    clearFiles();

    // 乐观更新用户消息（正式 id 由 start API 返回，这里先占位）。
    const optimisticUserId = `temp-${Date.now()}`;
    const userMsg: ChatMessage = {
      id: optimisticUserId,
      session_id: sessionId,
      role: "user",
      content,
      tokens_used: null,
      model_used: null,
      meta_data: null,
      created_at: new Date().toISOString(),
    };
    _appendMessage(sessionId, userMsg);

    let startResp;
    try {
      startResp = await startChatTaskApi(sessionId, {
        content,
        llm_config_id: llmConfigId,
      });
    } catch (err: unknown) {
      _appendMessage(sessionId, {
        id: `err-${Date.now()}`,
        session_id: sessionId,
        role: "assistant",
        content: `> ⚠️ ${err instanceof Error ? err.message : "发起对话失败"}`,
        tokens_used: null,
        model_used: null,
        meta_data: null,
        created_at: new Date().toISOString(),
      });
      return;
    }

    if (!startResp?.success || !startResp.data?.assistant_message_id) {
      _appendMessage(sessionId, {
        id: `err-${Date.now()}`,
        session_id: sessionId,
        role: "assistant",
        content: `> ⚠️ ${startResp?.message || "发起对话失败"}`,
        tokens_used: null,
        model_used: null,
        meta_data: null,
        created_at: new Date().toISOString(),
      });
      return;
    }

    // 用后端返回的正式 id 替换占位 user 消息（保证后续加载不会重复）。
    const list = messagesBySession.value[sessionId] || [];
    const patched = list.map((m) =>
      m.id === optimisticUserId
        ? { ...m, id: startResp!.data.user_message_id }
        : m,
    );
    _setMessages(sessionId, patched);

    // 更新会话卡片 message_count：用户 + 占位 assistant = +2。
    const sidx = sessions.value.findIndex((s) => s.id === sessionId);
    if (sidx >= 0) {
      sessions.value[sidx] = {
        ...sessions.value[sidx],
        message_count: (sessions.value[sidx].message_count || 0) + 2,
      };
    }

    _subscribeAssistantMessage({
      sessionId,
      assistantMsgId: startResp.data.assistant_message_id,
      userText: text,
    });
  }

  /**
   * 加载会话消息后调用：若存在某条 ``meta_data.status === "streaming"`` 的
   * assistant 占位消息，说明上一次发送时后台任务仍在跑（路由切走 / 刷新 /
   * 切会话都可能导致前端连接断开但后台 task 仍活），直接把它 resubscribe
   * 回来，让用户切回来还能看到完整流式输出。
   *
   * 关键修复（之前只看 ``list[length - 1]``）：若生成期间 LLM 调用了
   * ``propose_execution_plan`` 等会落 ``kind=skill_card`` /
   * ``execution_event`` 系统消息的工具，新消息 created_at 比占位更晚，会把
   * 占位"挤"到中间。仅看末尾会漏掉占位、续不上流，用户感知就是切回来后
   * AI 输出突然中断。改为反向遍历 + ``insertAt`` 维持原顺序。
   */
  function resumeIfStreaming(sessionId: string) {
    const list = messagesBySession.value[sessionId] || [];
    if (list.length === 0) return;
    if (streamingSessions.value[sessionId]) return;

    let streamingMsg: ChatMessage | null = null;
    let streamingIdx = -1;
    for (let i = list.length - 1; i >= 0; i--) {
      const m = list[i];
      if (m.role !== "assistant") continue;
      const meta = (m.meta_data || {}) as Record<string, unknown>;
      if (meta.status === "streaming") {
        streamingMsg = m;
        streamingIdx = i;
        break;
      }
    }
    if (!streamingMsg) return;

    // 找到占位之前最近的一条 user 消息，用它作为标题兜底。
    const prevUser = [...list.slice(0, streamingIdx)]
      .reverse()
      .find((m) => m.role === "user");
    const userText = prevUser?.content || "";
    const meta = (streamingMsg.meta_data || {}) as Record<string, unknown>;

    // 把占位先摘掉, finalize 时按 insertAt 塞回原位置, 避免 UI 上同时
    // 出现"streaming 气泡 + 占位空气泡"两条。
    _setMessages(
      sessionId,
      list.filter((m) => m.id !== streamingMsg!.id),
    );

    _subscribeAssistantMessage({
      sessionId,
      assistantMsgId: streamingMsg.id,
      userText,
      initialContent:
        typeof streamingMsg.content === "string" ? streamingMsg.content : "",
      initialReasoning:
        typeof meta.reasoning === "string" ? (meta.reasoning as string) : "",
      insertAt: streamingIdx,
    });
  }

  // ─── Phase 13 / Task 13.3 — 系统事件 SSE & pending 汇总 ─────────────────

  /**
   * 订阅会话级系统事件流；每个 session 独立一根 SSE，切换 session 时**保留**
   * 老连接（与 chat 主流的设计一致），允许后台任务的事件在用户切走时仍然
   * 被消费——任务完成时即便用户在别的 session，未读铃铛能 +1 提醒。
   *
   * `force=true` 时会先 abort 旧连接再起新的（重连 / 错误恢复用）。
   */
  function subscribeSystemEvents(sessionId: string, force = false) {
    if (!sessionId) return;
    if (!force && systemEventAborts[sessionId]) return;
    if (force && systemEventAborts[sessionId]) {
      systemEventAborts[sessionId]();
      delete systemEventAborts[sessionId];
    }

    const handle = fetchSSE(
      chatSystemEventsUrl(sessionId),
      null,
      {
        onEvent(event) {
          const kind = String(event.type || "");
          if (kind === "skill_card") {
            const msg = _systemEventToMessage(event, "skill_card");
            if (msg) _appendMessageIfMissing(sessionId, msg);
          } else if (kind === "execution_event") {
            const msg = _systemEventToMessage(event, "execution_event");
            if (msg) {
              _appendMessageIfMissing(sessionId, msg);
              if (sessionId !== currentSessionId.value) {
                unreadEvents.value += 1;
              }
            }
          } else if (kind === "task_status") {
            const taskId = String(event.task_id || "");
            const status = typeof event.status === "string" ? event.status : "";
            const progress = (event.progress as Record<string, unknown>) || {};
            if (taskId) {
              patchTaskBadgeByTaskId(sessionId, taskId, {
                status,
                total_cases: typeof progress.total_cases === "number"
                  ? progress.total_cases
                  : undefined,
                passed_cases: typeof progress.passed_cases === "number"
                  ? progress.passed_cases
                  : undefined,
                failed_cases: typeof progress.failed_cases === "number"
                  ? progress.failed_cases
                  : undefined,
                skipped_cases: typeof progress.skipped_cases === "number"
                  ? progress.skipped_cases
                  : undefined,
              });
            }
          }
        },
        onError() {
          // 错误兜底：清掉 abort handle，调用方可在断网回来时重订阅。
          delete systemEventAborts[sessionId];
        },
        onDone() {
          delete systemEventAborts[sessionId];
        },
      },
      { method: "GET" },
    );
    systemEventAborts[sessionId] = handle.abort;
  }

  function unsubscribeSystemEvents(sessionId: string) {
    if (!sessionId) return;
    systemEventAborts[sessionId]?.();
    delete systemEventAborts[sessionId];
  }

  function _appendMessageIfMissing(sessionId: string, msg: ChatMessage) {
    const list = messagesBySession.value[sessionId] || [];
    if (list.some((m) => m.id === msg.id)) return;
    _appendMessage(sessionId, msg);
  }

  /** 把 SSE 推过来的 skill_card / execution_event 事件还原成 ChatMessage。 */
  function _systemEventToMessage(
    event: Record<string, unknown>,
    kind: "skill_card" | "execution_event",
  ): ChatMessage | null {
    const messageId = String(event.message_id || "");
    if (!messageId) return null;
    const sessionId = String(event.session_id || "");
    if (!sessionId) return null;
    const meta: Record<string, unknown> =
      kind === "skill_card"
        ? {
            action_type: "skill_card",
            plan_id: event.plan_id,
            plan: event.plan,
          }
        : {
            action_type: "execution_event",
            task_id: event.task_id,
            result: event.result,
          };
    const created = String(event.created_at || new Date().toISOString());
    return {
      id: messageId,
      session_id: sessionId,
      role: "assistant",
      content: typeof event.content === "string" ? (event.content as string) : "",
      tokens_used: null,
      model_used: null,
      meta_data: meta,
      kind,
      created_at: created,
    };
  }

  /** 加载首屏顶部 "你离开期间完成 N 个任务" 汇总卡数据；count==0 时 banner 不渲染。 */
  async function loadPendingSummary(sessionId: string) {
    try {
      const res = await getPendingTaskSummaryApi(sessionId);
      if (res.success) {
        pendingSummary.value = res.data;
      }
    } catch {
      pendingSummary.value = null;
    }
  }

  function clearPendingSummary() {
    pendingSummary.value = null;
    unreadEvents.value = 0;
  }

  /** 切换会话 / 重连后调用：把所有非终态 TaskBadge 状态拉一次到最新。 */
  async function refreshTaskBadgesForSession(sessionId: string) {
    const list = messagesBySession.value[sessionId] || [];
    const next = await refreshAllTaskBadges(list);
    if (next !== list) {
      _setMessages(sessionId, next);
    }
  }

  function stopGeneration() {
    const sid = currentSessionId.value;
    if (!sid) return;
    // 只 abort 当前这条 HTTP 订阅；后台任务自己会继续跑完并落盘，
    // 下次刷新/切回这条会话时 resumeIfStreaming 会把它续上。
    abortHandles[sid]?.();
  }

  /**
   * 路由切走时（ChatView onBeforeUnmount）调用：abort 所有还在跑的 message
   * stream HTTP 订阅。后台 task 不受影响, 切回 chat 视图后 resumeIfStreaming
   * 会用同一 ``assistant_msg_id`` 重新订阅, 从 hub 重放完整事件。
   *
   * 没有这一步的话, 旧 useChat 实例的 fetch 会变成孤儿一直读流, 既浪费带宽,
   * 也会在后端 hub 累积无人消费的 zombie subscriber。
   */
  function abortAllStreams() {
    for (const sid of Object.keys(abortHandles)) {
      try {
        abortHandles[sid]?.();
      } catch {
        // ignore
      }
    }
  }

  return {
    sessions,
    currentSessionId,
    currentSession,
    messages,
    streaming,
    streamingContent,
    isStreaming,
    streamingSessions,
    isLoadingSessions,
    isLoadingMoreSessions,
    hasMoreSessions,
    isLoadingMessages,
    pendingFiles,
    latestSkillActivation,
    loadSessions,
    loadMoreSessions,
    selectSession,
    createNewSession,
    deleteSession,
    renameSession,
    applySystemPrompt,
    sendMessage,
    resumeIfStreaming,
    stopGeneration,
    abortAllStreams,
    addFile,
    removeFile,
    clearFiles,
    // Phase 13 / Task 13.3 — message kind helpers + system events SSE
    applyPlanConfirmation,
    applyPlanCancel,
    applyTaskBadgePatchByMessage,
    subscribeSystemEvents,
    unsubscribeSystemEvents,
    pendingSummary,
    unreadEvents,
    loadPendingSummary,
    clearPendingSummary,
    refreshTaskBadgesForSession,
  };
}
