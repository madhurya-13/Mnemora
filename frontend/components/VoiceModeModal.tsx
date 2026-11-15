"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Mic,
  Pause,
  RotateCcw,
  Sparkles,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { synthesizeSpeech, transcribeAudio } from "@/lib/voice";

type VoiceState = "idle" | "listening" | "processing" | "speaking";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  conversationId: string | null;
  onMessageSent: (transcription: string) => Promise<string | null>;
  initialVoice?: string;
};

const AVAILABLE_VOICES = [
  { id: "alloy", name: "Alloy (Neutral & Balanced)" },
  { id: "echo", name: "Echo (Warm & Clear)" },
  { id: "fable", name: "Fable (Expressive & British)" },
  { id: "onyx", name: "Onyx (Deep & Authoritative)" },
  { id: "nova", name: "Nova (Energetic & Friendly)" },
  { id: "shimmer", name: "Shimmer (Soft & Gentle)" },
];

export default function VoiceModeModal({
  isOpen,
  onClose,
  conversationId,
  onMessageSent,
  initialVoice = "alloy",
}: Props) {
  const [state, setState] = useState<VoiceState>("idle");
  const [userTranscript, setUserTranscript] = useState<string>("");
  const [assistantText, setAssistantText] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [voiceName, setVoiceName] = useState<string>(initialVoice);
  const [autoListen, setAutoListen] = useState<boolean>(true);
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [recordSeconds, setRecordSeconds] = useState<number>(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const recordTimerRef = useRef<NodeJS.Timeout | null>(null);
  const activeStreamRef = useRef<MediaStream | null>(null);
  const autoListenTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Monotonic id for the active turn; stale async work is ignored after a new turn. */
  const turnTokenRef = useRef(0);

  const isOpenRef = useRef(isOpen);
  const autoListenRef = useRef(autoListen);
  const isMutedRef = useRef(isMuted);
  const voiceNameRef = useRef(voiceName);

  useEffect(() => {
    isOpenRef.current = isOpen;
    if (!isOpen) stopAllAudio();
    // stopAllAudio only reads refs; it is intentionally not in the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  useEffect(() => {
    autoListenRef.current = autoListen;
  }, [autoListen]);

  useEffect(() => {
    isMutedRef.current = isMuted;
  }, [isMuted]);

  useEffect(() => {
    voiceNameRef.current = voiceName;
  }, [voiceName]);

  useEffect(() => {
    return () => {
      stopAllAudio();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (state === "listening") {
      recordTimerRef.current = setInterval(() => {
        setRecordSeconds((s) => s + 1);
      }, 1000);
    } else if (recordTimerRef.current) {
      clearInterval(recordTimerRef.current);
      recordTimerRef.current = null;
    }
    return () => {
      if (recordTimerRef.current) {
        clearInterval(recordTimerRef.current);
        recordTimerRef.current = null;
      }
    };
  }, [state]);

  function clearAutoListenTimer() {
    if (autoListenTimeoutRef.current) {
      clearTimeout(autoListenTimeoutRef.current);
      autoListenTimeoutRef.current = null;
    }
  }

  function stopPlayback() {
    clearAutoListenTimer();
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    if (audioElementRef.current) {
      audioElementRef.current.onended = null;
      audioElementRef.current.onerror = null;
      audioElementRef.current.pause();
      audioElementRef.current.src = "";
      audioElementRef.current = null;
    }
  }

  /** Stop every active stream/playback and invalidate any in-flight turn. */
  function stopAllAudio() {
    turnTokenRef.current += 1;

    const recorder = mediaRecorderRef.current;
    mediaRecorderRef.current = null;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      if (recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch {
          /* ignore */
        }
      }
      recorder.stream?.getTracks().forEach((track) => track.stop());
    }

    if (activeStreamRef.current) {
      activeStreamRef.current.getTracks().forEach((track) => track.stop());
      activeStreamRef.current = null;
    }

    stopPlayback();
  }

  function handleCloseModal() {
    stopAllAudio();
    setState("idle");
    setUserTranscript("");
    setAssistantText("");
    setErrorMessage(null);
    setRecordSeconds(0);
    onClose();
  }

  function cleanTextForSpeech(text: string): string {
    return text
      .replace(/```[\s\S]*?```/g, "")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/[#*_~>]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  // --- Voice Turn: User Speaks -> Transcribe -> Chat Pipeline -> Synthesize -> Playback ---
  async function startListening() {
    if (!isOpenRef.current) return;

    stopAllAudio();
    const token = turnTokenRef.current;
    setErrorMessage(null);
    setRecordSeconds(0);
    audioChunksRef.current = [];

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setErrorMessage("Your browser does not support microphone audio recording.");
      setState("idle");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (token !== turnTokenRef.current || !isOpenRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      activeStreamRef.current = stream;

      let mimeType = "audio/webm;codecs=opus";
      if (!MediaRecorder.isTypeSupported(mimeType)) {
        mimeType = MediaRecorder.isTypeSupported("audio/mp4")
          ? "audio/mp4"
          : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : "";
      }

      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        if (activeStreamRef.current === stream) activeStreamRef.current = null;
        if (mediaRecorderRef.current === recorder) mediaRecorderRef.current = null;

        if (token !== turnTokenRef.current || !isOpenRef.current) return;

        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        audioChunksRef.current = [];
        if (blob.size === 0) {
          setErrorMessage("No audio was captured. Please try again.");
          setState("idle");
          return;
        }

        // 1. Process Transcription
        setState("processing");
        try {
          const extension = recorder.mimeType.includes("mp4")
            ? "mp4"
            : recorder.mimeType.includes("ogg")
            ? "ogg"
            : "webm";
          const transcribed = await transcribeAudio(blob, `recording.${extension}`);
          if (token !== turnTokenRef.current || !isOpenRef.current) return;

          if (!transcribed.trim()) {
            setErrorMessage("No speech was detected. Please try speaking again.");
            setState("idle");
            return;
          }

          setUserTranscript(transcribed);
          setAssistantText("");

          // 2. Send through conversational pipeline (with memory retrieval & DB persistence)
          const replyText = await onMessageSent(transcribed);
          if (token !== turnTokenRef.current || !isOpenRef.current) return;

          if (!replyText) {
            setErrorMessage("Could not generate a response. Check the chat connection and try again.");
            setState("idle");
            return;
          }

          setAssistantText(replyText);

          // 3. Synthesize Speech and Play (unless muted)
          if (isMutedRef.current) {
            setState("idle");
          } else {
            await playAssistantSpeech(replyText, token);
          }
        } catch (err: unknown) {
          if (token !== turnTokenRef.current) return;
          const msg = err instanceof Error ? err.message : "Voice conversation failed.";
          setErrorMessage(msg);
          setState("idle");
        }
      };

      recorder.start(250);
      setState("listening");
    } catch (err: unknown) {
      if (token !== turnTokenRef.current) return;
      const errName = (err as { name?: string })?.name;
      if (errName === "NotAllowedError" || errName === "PermissionDeniedError") {
        setErrorMessage("Microphone permission was denied. Please allow microphone access.");
      } else {
        setErrorMessage("Unable to access microphone. Check your audio device settings.");
      }
      setState("idle");
    }
  }

  function stopListening() {
    const recorder = mediaRecorderRef.current;
    if (!recorder) return;
    if (recorder.state === "recording" || recorder.state === "paused") {
      setState("processing");
      try {
        recorder.stop();
      } catch {
        setState("idle");
      }
    }
  }

  async function playAssistantSpeech(text: string, token: number) {
    if (!isOpenRef.current || token !== turnTokenRef.current) return;
    setState("speaking");

    const cleanText = cleanTextForSpeech(text);
    if (!cleanText) {
      setState("idle");
      return;
    }

    let audioUrl: string | null = null;
    try {
      const audioBlob = await synthesizeSpeech(cleanText, voiceNameRef.current);
      if (token !== turnTokenRef.current || !isOpenRef.current) return;

      audioUrl = URL.createObjectURL(audioBlob);
      audioUrlRef.current = audioUrl;

      const audio = new Audio(audioUrl);
      audioElementRef.current = audio;

      audio.onended = () => {
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        if (audioUrlRef.current === audioUrl) audioUrlRef.current = null;
        if (audioElementRef.current === audio) audioElementRef.current = null;
        if (token !== turnTokenRef.current || !isOpenRef.current) return;

        if (autoListenRef.current) {
          clearAutoListenTimer();
          autoListenTimeoutRef.current = setTimeout(() => {
            autoListenTimeoutRef.current = null;
            if (isOpenRef.current && autoListenRef.current) void startListening();
          }, 700);
        } else {
          setState("idle");
        }
      };

      audio.onerror = () => {
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        if (audioUrlRef.current === audioUrl) audioUrlRef.current = null;
        if (audioElementRef.current === audio) audioElementRef.current = null;
        if (token !== turnTokenRef.current) return;
        setErrorMessage("The spoken response could not be played. Tap Replay to try again.");
        setState("idle");
      };

      await audio.play();
    } catch (err: unknown) {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      if (audioUrlRef.current === audioUrl) audioUrlRef.current = null;
      if (audioElementRef.current?.src === audioUrl) audioElementRef.current = null;
      if (token !== turnTokenRef.current) return;

      const errName = (err as { name?: string })?.name;
      if (errName === "NotAllowedError") {
        setErrorMessage("The browser blocked audio autoplay. Tap Replay to hear the response.");
      } else {
        setErrorMessage(err instanceof Error ? err.message : "Failed to synthesize speech.");
      }
      setState("idle");
    }
  }

  function interruptPlayback() {
    stopAllAudio();
    setState("idle");
  }

  function replayLastResponse() {
    if (!assistantText.trim() || state === "listening" || state === "processing") return;
    stopAllAudio();
    const token = turnTokenRef.current;
    void playAssistantSpeech(assistantText, token);
  }

  function toggleMuted() {
    const next = !isMutedRef.current;
    isMutedRef.current = next;
    setIsMuted(next);
    if (next && state === "speaking") interruptPlayback();
  }

  if (!isOpen) return null;

  const formatTimer = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const s = sec % 60;
    return `${mins.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-xl transition-all">
      <div className="relative flex h-full max-h-[700px] w-full max-w-2xl flex-col justify-between overflow-hidden rounded-3xl border border-white/10 bg-[#0a0d18] p-6 shadow-2xl sm:p-8">
        {/* Top Header Controls */}
        <div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-violet-500/10 text-violet-300 border border-violet-500/20">
              <Sparkles size={16} />
            </span>
            <div>
              <h2 className="text-sm font-semibold text-slate-100">MNEMORA Voice Assistant</h2>
              <p className="text-[11px] text-slate-400">Conversational AI with persistent memory</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <select
              value={voiceName}
              onChange={(e) => setVoiceName(e.target.value)}
              aria-label="Assistant voice"
              className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-300 outline-none hover:bg-white/[0.08] transition"
            >
              {AVAILABLE_VOICES.map((v) => (
                <option key={v.id} value={v.id} className="bg-[#11131e] text-slate-200">
                  {v.name}
                </option>
              ))}
            </select>

            <button
              type="button"
              onClick={toggleMuted}
              aria-label={isMuted ? "Unmute spoken responses" : "Mute spoken responses"}
              className="rounded-xl p-2 text-slate-400 hover:bg-white/[0.08] hover:text-white transition"
              title={isMuted ? "Unmute audio" : "Mute audio"}
            >
              {isMuted ? <VolumeX size={18} className="text-amber-400" /> : <Volume2 size={18} />}
            </button>

            <button
              type="button"
              onClick={handleCloseModal}
              aria-label="Exit voice mode"
              className="rounded-xl p-2 text-slate-400 hover:bg-white/[0.08] hover:text-white transition"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Central Orb & Interaction Visualizer */}
        <div className="my-auto flex flex-col items-center justify-center py-6">
          {/* Animated Interactive Pulsing Orb */}
          <div className="relative flex items-center justify-center">
            {/* Outer Waves */}
            {state === "listening" && (
              <>
                <div className="absolute h-52 w-52 animate-ping rounded-full bg-rose-500/15 duration-1000" />
                <div className="absolute h-44 w-44 animate-pulse rounded-full bg-rose-500/25 duration-700" />
              </>
            )}

            {state === "speaking" && (
              <>
                <div className="absolute h-56 w-56 animate-ping rounded-full bg-violet-500/15 duration-1000" />
                <div className="absolute h-48 w-48 animate-pulse rounded-full bg-blue-500/20 duration-700" />
              </>
            )}

            {state === "processing" && (
              <div className="absolute h-48 w-48 animate-spin rounded-full border-2 border-violet-400/40 border-t-transparent" />
            )}

            {/* Central Glow Orb Button */}
            <button
              type="button"
              onClick={() => {
                if (state === "listening") stopListening();
                else if (state === "speaking") interruptPlayback();
                else if (state === "idle") void startListening();
              }}
              disabled={state === "processing"}
              aria-label={
                state === "listening"
                  ? "Finish recording and transcribe"
                  : state === "speaking"
                  ? "Interrupt spoken response"
                  : state === "processing"
                  ? "Processing your request"
                  : "Start speaking"
              }
              className={`relative z-10 flex h-32 w-32 items-center justify-center rounded-full shadow-2xl transition-all duration-300 ${
                state === "listening"
                  ? "bg-gradient-to-tr from-rose-600 to-rose-400 text-white shadow-[0_0_50px_rgba(244,63,94,0.5)] scale-105"
                  : state === "speaking"
                  ? "bg-gradient-to-tr from-violet-600 via-indigo-600 to-blue-500 text-white shadow-[0_0_60px_rgba(139,115,255,0.6)] animate-pulse"
                  : state === "processing"
                  ? "bg-[#181a2e] text-violet-300 border border-violet-500/40 cursor-wait"
                  : "bg-gradient-to-tr from-violet-700 to-blue-600 text-white shadow-[0_0_40px_rgba(112,83,255,0.3)] hover:scale-105"
              }`}
            >
              {state === "listening" ? (
                <Mic size={38} className="animate-bounce" />
              ) : state === "speaking" ? (
                <Volume2 size={40} />
              ) : state === "processing" ? (
                <Sparkles size={36} className="animate-spin text-violet-300" />
              ) : (
                <Mic size={38} />
              )}
            </button>
          </div>

          {/* Status Label & Timer */}
          <div className="mt-7 text-center">
            <p className="text-base font-medium text-slate-100">
              {state === "listening"
                ? "Listening… Tap orb to finish"
                : state === "processing"
                ? "Thinking & retrieving memories…"
                : state === "speaking"
                ? "MNEMORA is speaking… Tap orb to interrupt"
                : "Ready · Tap microphone to speak"}
            </p>
            {state === "listening" && (
              <p className="mt-1 font-mono text-xs text-rose-300">{formatTimer(recordSeconds)}</p>
            )}
          </div>

          {/* Real-time Transcription & Response Displays */}
          <div className="mt-6 w-full max-w-lg space-y-3">
            {userTranscript && (
              <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-3 text-xs text-slate-300 shadow-sm">
                <span className="font-semibold text-blue-300">You: </span>
                <span>{userTranscript}</span>
              </div>
            )}

            {assistantText && (
              <div className="max-h-40 overflow-y-auto rounded-2xl border border-violet-500/20 bg-violet-500/[0.06] p-3.5 text-xs text-slate-200 leading-relaxed shadow-sm">
                <span className="font-semibold text-violet-300">MNEMORA: </span>
                <span>{assistantText}</span>
              </div>
            )}

            {errorMessage && (
              <div className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                <AlertCircle size={15} className="shrink-0 text-rose-400" />
                <span>{errorMessage}</span>
              </div>
            )}
          </div>
        </div>

        {/* Bottom Bar Controls */}
        <div className="flex items-center justify-between border-t border-white/[0.08] pt-4 text-xs text-slate-400">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoListen}
              onChange={(e) => setAutoListen(e.target.checked)}
              className="rounded accent-violet-500"
            />
            <span>Continuous conversation (auto-listen)</span>
          </label>

          <div className="flex items-center gap-2">
            {state === "speaking" && (
              <button
                type="button"
                onClick={interruptPlayback}
                className="inline-flex items-center gap-1 rounded-xl border border-white/10 bg-white/[0.06] px-3 py-1.5 text-slate-200 hover:bg-white/[0.1] transition"
              >
                <Pause size={13} /> Stop Audio
              </button>
            )}
            {assistantText && state === "idle" && !isMuted && (
              <button
                type="button"
                onClick={replayLastResponse}
                className="inline-flex items-center gap-1 rounded-xl border border-violet-400/20 bg-violet-500/10 px-3 py-1.5 text-violet-200 hover:bg-violet-500/20 transition"
              >
                <RotateCcw size={13} /> Replay
              </button>
            )}
            <button
              type="button"
              onClick={handleCloseModal}
              className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-1.5 text-slate-300 hover:bg-white/[0.08] hover:text-white transition"
            >
              Back to Text Chat
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
