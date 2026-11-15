import { ApiError, getApiUrl } from "@/lib/api";
import type { ChatResponse } from "@/lib/chat";

export type VoiceSettingsResponse = {
  voice_enabled: boolean;
  tts_enabled: boolean;
  image_input_enabled: boolean;
  default_voice: string;
  available_voices: string[];
  stt_provider: string;
  tts_provider: string;
  openai_stt_model: string;
  openai_tts_model: string;
  openai_vision_model: string;
  gemini_stt_model: string;
  gemini_tts_model: string;
  gemini_tts_voice: string;
  max_audio_upload_mb: number;
  max_image_upload_mb: number;
};

export type TranscriptionResult = {
  text: string;
  filename?: string;
  detected_format?: string;
};

function getErrorMessage(data: unknown, fallback: string): string {
  if (typeof data === "object" && data !== null) {
    const value = data as { detail?: unknown; error?: { message?: unknown } };
    if (typeof value.detail === "string") return value.detail;
    if (typeof value.error?.message === "string") return value.error.message;
  }
  return fallback;
}

async function voiceFetch(path: string, init: RequestInit, unreachable: string): Promise<Response> {
  try {
    return await fetch(`${getApiUrl()}${path}`, { ...init, credentials: "include" });
  } catch {
    throw new ApiError(unreachable, 0);
  }
}

export async function transcribeAudio(audioBlob: Blob, filename = "recording.webm"): Promise<string> {
  const formData = new FormData();
  formData.append("audio", audioBlob, filename);

  const response = await voiceFetch(
    "/api/v1/voice/transcribe",
    { method: "POST", body: formData },
    "Can't reach MNEMORA's backend to transcribe audio. Check that it is running and try again.",
  );

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(getErrorMessage(data, `Transcription failed (${response.status})`), response.status);
  }
  return (data as TranscriptionResult).text;
}

export async function transcribeUpload(file: File): Promise<string> {
  const formData = new FormData();
  formData.append("file", file, file.name);

  const response = await voiceFetch(
    "/api/v1/voice/transcribe-upload",
    { method: "POST", body: formData },
    "Can't reach MNEMORA's backend to transcribe this file. Check that it is running and try again.",
  );

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(getErrorMessage(data, `Audio upload transcription failed (${response.status})`), response.status);
  }
  return (data as TranscriptionResult).text;
}

export async function synthesizeSpeech(text: string, voice?: string): Promise<Blob> {
  const response = await voiceFetch(
    "/api/v1/voice/speak",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice }),
    },
    "Can't reach MNEMORA's backend to generate speech. Check that it is running and try again.",
  );

  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(getErrorMessage(data, `Speech synthesis failed (${response.status})`), response.status);
  }

  return response.blob();
}

export async function getVoiceSettings(): Promise<VoiceSettingsResponse> {
  const response = await voiceFetch(
    "/api/v1/voice/settings",
    { method: "GET" },
    "Can't reach MNEMORA's backend to load voice settings.",
  );
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(getErrorMessage(data, "Failed to load voice settings"), response.status);
  }
  return data as VoiceSettingsResponse;
}

export async function updateVoiceSettings(
  update: Partial<VoiceSettingsResponse>,
): Promise<VoiceSettingsResponse> {
  const response = await voiceFetch(
    "/api/v1/voice/settings",
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    },
    "Can't reach MNEMORA's backend to save voice settings.",
  );
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(getErrorMessage(data, "Failed to update voice settings"), response.status);
  }
  return data as VoiceSettingsResponse;
}

export async function sendMessageWithImage(
  conversationId: string,
  message: string,
  imageFile: File,
): Promise<ChatResponse> {
  const formData = new FormData();
  formData.append("message", message);
  formData.append("image", imageFile, imageFile.name);

  const target = conversationId || "new";
  const response = await voiceFetch(
    `/api/v1/chat/${encodeURIComponent(target)}/message-with-image`,
    { method: "POST", body: formData },
    "Can't reach MNEMORA's backend to send this image.",
  );

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(getErrorMessage(data, `Failed to send image message (${response.status})`), response.status);
  }
  return data as ChatResponse;
}

export async function sendMessageWithAudio(
  conversationId: string,
  audioBlob: Blob,
  filename = "speech.webm",
): Promise<ChatResponse> {
  const formData = new FormData();
  formData.append("audio", audioBlob, filename);

  const target = conversationId || "new";
  const response = await voiceFetch(
    `/api/v1/chat/${encodeURIComponent(target)}/message-with-audio`,
    { method: "POST", body: formData },
    "Can't reach MNEMORA's backend to send this voice message.",
  );

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(getErrorMessage(data, `Failed to process voice message (${response.status})`), response.status);
  }
  return data as ChatResponse;
}
