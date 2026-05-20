import { ofetch, type FetchOptions, type FetchRequest, type ResponseType } from "ofetch";

let refreshPromise: Promise<boolean> | null = null;

function getAccessToken() {
  return localStorage.getItem("access_token") || "";
}

function getRefreshToken() {
  return localStorage.getItem("refresh_token") || "";
}

function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}

function redirectToLogin() {
  clearTokens();
  if (window.location.pathname !== "/login") {
    window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
  }
}

function getErrorStatus(err: unknown): number | undefined {
  if (!err || typeof err !== "object") return undefined;
  const maybe = err as {
    status?: number;
    statusCode?: number;
    response?: { status?: number };
  };
  return maybe.response?.status ?? maybe.status ?? maybe.statusCode;
}

async function doRefresh(): Promise<boolean> {
  const rt = getRefreshToken();
  if (!rt) return false;
  try {
    const res = await ofetch<{
      success: boolean;
      data: { access_token: string; refresh_token: string };
    }>("/api/auth/refresh", {
      method: "POST",
      body: { refresh_token: rt },
    });
    if (res.success) {
      localStorage.setItem("access_token", res.data.access_token);
      localStorage.setItem("refresh_token", res.data.refresh_token);
      return true;
    }
  } catch {
    /* refresh failed */
  }
  return false;
}

function refreshOnce(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = doRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

const apiFetch = ofetch.create({
  baseURL: "/api",

  onRequest({ options }) {
    const token = getAccessToken();
    if (token) {
      const headers = new Headers(options.headers as HeadersInit);
      headers.set("Authorization", `Bearer ${token}`);
      options.headers = headers;
    }
  },
});

export async function request<T = unknown, R extends ResponseType = "json">(
  url: FetchRequest,
  options?: FetchOptions<R>,
) {
  try {
    return await apiFetch<T, R>(url, options);
  } catch (err) {
    if (getErrorStatus(err) !== 401) {
      throw err;
    }

    const ok = await refreshOnce();
    if (!ok) {
      redirectToLogin();
      throw err;
    }

    return apiFetch<T, R>(url, options);
  }
}
