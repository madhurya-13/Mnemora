import { ApiError, getApiUrl, requestJson } from "@/lib/api";

export type MessageRole = "user" | "assistant";
export type ChatMessage = { role: MessageRole; content: string; created_at: string };
export type ChatRequest = { conversation_id: string; message: string; regenerate?: boolean };
export type ChatResponse = { conversation_id: string; response: string; role: "assistant" };
export type ConversationSummary = { conversation_id: string; title: string; updated_at: string; message_count: number };
export type ConversationDetail = ConversationSummary & { messages: ChatMessage[] };
export type StreamEvent =
  | { event: "conversation"; data: { conversation_id: string } }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: { conversation_id: string; role: "assistant" } }
  | { event: "error"; data: { message: string; retryable: boolean } };

export const listConversations = () => requestJson<ConversationSummary[]>("/api/v1/chat/conversations");
export const createConversation = (title = "New chat") => requestJson<ConversationDetail>("/api/v1/chat/conversations", {
  method: "POST", body: JSON.stringify({ title }),
});
export const getConversation = (id: string) => requestJson<ConversationDetail>(`/api/v1/chat/conversations/${encodeURIComponent(id)}`);
export const renameConversation = (id: string, title: string) => requestJson<ConversationSummary>(`/api/v1/chat/conversations/${encodeURIComponent(id)}`, {
  method: "PATCH", body: JSON.stringify({ title }),
});
export const clearConversation = (id: string) => requestJson<ConversationDetail>(`/api/v1/chat/conversations/${encodeURIComponent(id)}/messages`, {
  method: "DELETE",
});
export const deleteConversation = (id: string) => requestJson<void>(`/api/v1/chat/conversations/${encodeURIComponent(id)}`, {
  method: "DELETE",
});

function decodeEvent(frame: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator < 0 ? line : line.slice(0, separator);
    const value = separator < 0 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "event") event = value;
    if (field === "data") dataLines.push(value);
  }
  if (!dataLines.length) return null;
  const text = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(text) as unknown };
  } catch {
    throw new Error("The backend sent an invalid streaming response.");
  }
}

export async function streamChat(
  request: ChatRequest,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${getApiUrl()}/api/v1/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(request),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("The connection to MNEMORA was interrupted. Please retry your message.", 0);
  }

  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    throw new ApiError(
      typeof data === "object" && data !== null && "detail" in data && typeof data.detail === "string"
        ? data.detail
        : `Request failed (${response.status}).`,
      response.status,
    );
  }
  if (!response.body) throw new ApiError("Streaming is unavailable in this browser. Please retry.", response.status);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  let failed = false;
  const dispatch = (frame: string) => {
    const decoded = decodeEvent(frame);
    if (!decoded) return;
    if (decoded.event === "conversation" && typeof decoded.data === "object" && decoded.data !== null && "conversation_id" in decoded.data && typeof decoded.data.conversation_id === "string") {
      onEvent({ event: "conversation", data: { conversation_id: decoded.data.conversation_id } });
    } else if (decoded.event === "token" && typeof decoded.data === "object" && decoded.data !== null && "text" in decoded.data && typeof decoded.data.text === "string") {
      onEvent({ event: "token", data: { text: decoded.data.text } });
    } else if (decoded.event === "done" && typeof decoded.data === "object" && decoded.data !== null && "conversation_id" in decoded.data && typeof decoded.data.conversation_id === "string") {
      finished = true;
      onEvent({ event: "done", data: { conversation_id: decoded.data.conversation_id, role: "assistant" } });
    } else if (decoded.event === "error" && typeof decoded.data === "object" && decoded.data !== null && "message" in decoded.data && typeof decoded.data.message === "string") {
      failed = true;
      onEvent({ event: "error", data: { message: decoded.data.message, retryable: "retryable" in decoded.data && decoded.data.retryable === true } });
    } else if (!["conversation", "token", "done", "error"].includes(decoded.event)) {
      // Ignore extension events so the stream can evolve without breaking this client.
      return;
    } else {
      throw new Error("The backend sent a malformed streaming event.");
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      frames.forEach(dispatch);
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
    if (!finished && !failed) throw new ApiError("The response stream ended before the assistant finished. Please retry.", 0);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("The response stream was interrupted. Please retry your message.", 0);
  } finally {
    reader.releaseLock();
  }
}
