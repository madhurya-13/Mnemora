export type HealthResponse = { status: string; application: string; version: string };
export type ChatHealthResponse = { status: "ready" | "not_configured"; configured: boolean; model: string };

const apiUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

function errorMessage(data: unknown, fallback: string): string {
  if (typeof data === "object" && data !== null) {
    const value = data as { detail?: unknown; error?: { message?: unknown } };
    if (typeof value.detail === "string") return value.detail;
    if (typeof value.error?.message === "string") return value.error.message;
  }
  return fallback;
}

export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    const headers = new Headers(init.headers);
    if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    response = await fetch(`${apiUrl}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Can’t reach MNEMORA’s backend. Check that it is running and try again.", 0);
  }

  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(errorMessage(data, `Request failed (${response.status}).`), response.status);
  return data as T;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/v1/health");
}

export function getChatHealth(): Promise<ChatHealthResponse> {
  return requestJson<ChatHealthResponse>("/api/v1/chat/health");
}

export function getApiUrl(): string {
  return apiUrl;
}
