"use client";

import {
  ChangeEvent,
  DragEvent,
  FormEvent,
  KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  AlertCircle,
  ArrowUp,
  FileAudio,
  Image as ImageIcon,
  LoaderCircle,
  Mic,
  Square,
  X,
} from "lucide-react";
import { transcribeAudio, transcribeUpload } from "@/lib/voice";

type Props = {
  disabled?: boolean;
  onSend: (message: string, imageFile?: File) => void;
  onVoiceMode?: () => void;
};

export default function ChatInput({ disabled = false, onSend, onVoiceMode }: Props) {
  const [value, setValue] = useState("");
  const [attachedImage, setAttachedImage] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);

  // Voice recording state
  const [isRecording, setIsRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcribeNotice, setTranscribeNotice] = useState<string | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const audioInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordTimerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (isRecording) {
      recordTimerRef.current = setInterval(() => {
        setRecordSeconds((sec) => sec + 1);
      }, 1000);
    } else {
      if (recordTimerRef.current) {
        clearInterval(recordTimerRef.current);
        recordTimerRef.current = null;
      }
    }
    return () => {
      if (recordTimerRef.current) clearInterval(recordTimerRef.current);
    };
  }, [isRecording]);

  const canSend = (value.trim().length > 0 || attachedImage !== null) && !disabled && !isTranscribing;

  function clearAttachedImage() {
    if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    setAttachedImage(null);
    setImagePreviewUrl(null);
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const message = value.trim();
    if ((!message && !attachedImage) || disabled || isTranscribing) return;

    onSend(message, attachedImage ?? undefined);
    setValue("");
    clearAttachedImage();
    setInputError(null);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  // --- Microphone Recording Handlers ---
  async function startRecording() {
    setInputError(null);
    setRecordSeconds(0);
    audioChunksRef.current = [];

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setInputError("Your browser does not support microphone audio recording.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
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

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        if (blob.size === 0) return;

        setIsTranscribing(true);
        setTranscribeNotice("Transcribing your speech…");
        try {
          const extension = recorder.mimeType.includes("mp4")
            ? "mp4"
            : recorder.mimeType.includes("ogg")
            ? "ogg"
            : "webm";
          const transcript = await transcribeAudio(blob, `recording.${extension}`);
          if (transcript.trim()) {
            setValue((prev) => (prev ? `${prev.trim()} ${transcript.trim()}` : transcript.trim()));
          } else {
            setInputError("No speech was detected. Try again, then edit the text before sending.");
            if (textareaRef.current) {
              textareaRef.current.style.height = "auto";
              setTimeout(() => {
                if (textareaRef.current) {
                  textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 192)}px`;
                  textareaRef.current.focus();
                }
              }, 50);
            }
          }
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : "Failed to transcribe speech.";
          setInputError(msg);
        } finally {
          setIsTranscribing(false);
          setTranscribeNotice(null);
        }
      };

      recorder.start(250);
      setIsRecording(true);
    } catch (err: unknown) {
      const errName = (err as { name?: string })?.name;
      if (errName === "NotAllowedError" || errName === "PermissionDeniedError") {
        setInputError("Microphone permission was denied. Please allow microphone access in browser settings.");
      } else {
        setInputError("Unable to access your microphone. Please check your audio device settings.");
      }
    }
  }

  function stopRecording() {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  }

  function cancelRecording() {
    if (mediaRecorderRef.current) {
      mediaRecorderRef.current.ondataavailable = null;
      mediaRecorderRef.current.onstop = null;
      mediaRecorderRef.current.stop();
      if (mediaRecorderRef.current.stream) {
        mediaRecorderRef.current.stream.getTracks().forEach((track) => track.stop());
      }
      mediaRecorderRef.current = null;
    }
    audioChunksRef.current = [];
    setIsRecording(false);
    setRecordSeconds(0);
  }

  // --- Image & Audio File Handlers ---
  function handleImageSelected(e: ChangeEvent<HTMLInputElement>) {
    setInputError(null);
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 10 * 1024 * 1024) {
      setInputError("Image size exceeds 10 MB limit.");
      return;
    }
    if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    setAttachedImage(file);
    setImagePreviewUrl(URL.createObjectURL(file));
    e.target.value = "";
  }

  async function handleAudioSelected(e: ChangeEvent<HTMLInputElement>) {
    setInputError(null);
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 20 * 1024 * 1024) {
      setInputError("Audio file exceeds 20 MB limit.");
      return;
    }

    e.target.value = "";
    setIsTranscribing(true);
    setTranscribeNotice(`Transcribing ${file.name}…`);
    try {
      const transcript = await transcribeUpload(file);
      if (transcript.trim()) {
        setValue((prev) => (prev ? `${prev.trim()} ${transcript.trim()}` : transcript.trim()));
      } else {
        setInputError("No speech was detected in that audio file.");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to transcribe audio file.";
      setInputError(msg);
    } finally {
      setIsTranscribing(false);
      setTranscribeNotice(null);
    }
  }

  // --- Drag and Drop Handlers ---
  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave(e: DragEvent) {
    e.preventDefault();
    setIsDragging(false);
  }

  async function handleDrop(e: DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    setInputError(null);

    const file = e.dataTransfer.files?.[0];
    if (!file) return;

    if (file.type.startsWith("image/")) {
      if (file.size > 10 * 1024 * 1024) {
        setInputError("Image size exceeds 10 MB limit.");
        return;
      }
      if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
      setAttachedImage(file);
      setImagePreviewUrl(URL.createObjectURL(file));
    } else if (file.type.startsWith("audio/") || /\.(mp3|wav|m4a|webm|ogg|flac)$/i.test(file.name)) {
      if (file.size > 20 * 1024 * 1024) {
        setInputError("Audio file exceeds 20 MB limit.");
        return;
      }
      setIsTranscribing(true);
      setTranscribeNotice(`Transcribing ${file.name}…`);
      try {
        const transcript = await transcribeUpload(file);
        if (transcript.trim()) {
          setValue((prev) => (prev ? `${prev.trim()} ${transcript.trim()}` : transcript.trim()));
        } else {
          setInputError("No speech was detected in that audio file.");
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to transcribe audio file.";
        setInputError(msg);
      } finally {
        setIsTranscribing(false);
        setTranscribeNotice(null);
      }
    } else {
      setInputError("Unsupported file type. Please upload an image (PNG, JPEG, WebP) or audio file.");
    }
  }

  const formatTimer = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const s = sec % 60;
    return `${mins.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  return (
    <form
      onSubmit={submit}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className="mx-auto w-full max-w-4xl"
    >
      <input
        ref={imageInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif"
        className="hidden"
        onChange={handleImageSelected}
      />
      <input
        ref={audioInputRef}
        type="file"
        accept="audio/*,.mp3,.wav,.m4a,.webm,.ogg,.flac"
        className="hidden"
        onChange={handleAudioSelected}
      />

      {/* Error or Notice Banners */}
      {inputError && (
        <div className="mb-2 flex items-center justify-between rounded-xl border border-rose-400/20 bg-rose-500/10 px-3.5 py-2 text-xs text-rose-200">
          <div className="flex items-center gap-2">
            <AlertCircle size={14} className="shrink-0 text-rose-400" />
            <span>{inputError}</span>
          </div>
          <button
            type="button"
            onClick={() => setInputError(null)}
            className="text-rose-300 hover:text-white"
            aria-label="Dismiss error"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {isTranscribing && (
        <div className="mb-2 flex items-center gap-2 rounded-xl border border-violet-400/20 bg-violet-500/10 px-3.5 py-2 text-xs text-violet-200 animate-pulse">
          <LoaderCircle size={14} className="animate-spin text-violet-400" />
          <span>{transcribeNotice || "Transcribing audio…"}</span>
        </div>
      )}

      {/* Image Attachment Preview */}
      {attachedImage && imagePreviewUrl && (
        <div className="mb-2 flex items-center gap-3 rounded-2xl border border-white/[0.08] bg-[#141624] p-2.5 shadow-lg">
          <div className="relative h-14 w-14 shrink-0 overflow-hidden rounded-xl border border-white/10 bg-black/40">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={imagePreviewUrl} alt="Preview" className="h-full w-full object-cover" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-slate-200">{attachedImage.name}</p>
            <p className="mt-0.5 text-[10px] text-slate-500">
              {(attachedImage.size / 1024).toFixed(0)} KB · Ready to send
            </p>
          </div>
          <button
            type="button"
            onClick={clearAttachedImage}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-white/[0.08] hover:text-white transition"
            aria-label="Remove image"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {/* Active Recording Mode */}
      {isRecording ? (
        <div className="relative flex items-center justify-between rounded-[22px] border border-rose-500/30 bg-[#16121f] px-5 py-4 shadow-[0_10px_50px_rgba(244,63,94,0.12)]">
          <div className="flex items-center gap-3">
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-75" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-rose-500" />
            </span>
            <span className="text-sm font-medium text-rose-200">Recording audio…</span>
            <span className="rounded-md bg-rose-500/20 px-2 py-0.5 font-mono text-xs text-rose-200">
              {formatTimer(recordSeconds)}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={cancelRecording}
              className="rounded-xl px-3 py-1.5 text-xs text-slate-400 hover:bg-white/[0.08] hover:text-slate-200 transition"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={stopRecording}
              className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-rose-500 to-violet-600 px-3.5 py-1.5 text-xs font-medium text-white shadow-md hover:brightness-110 transition"
            >
              <Square size={13} className="fill-white" />
              Done & Transcribe
            </button>
          </div>
        </div>
      ) : (
        /* Standard Text & Multimodal Input */
        <div
          className={`relative rounded-[22px] border bg-[#11131e] transition shadow-[0_10px_50px_rgba(0,0,0,.25)] focus-within:border-violet-300/30 focus-within:shadow-[0_0_0_3px_rgba(139,115,255,.07)] ${
            isDragging ? "border-violet-400 ring-2 ring-violet-400/20" : "border-white/[0.11]"
          }`}
        >
          {/* Action buttons (Left side) */}
          <div className="absolute bottom-3 left-3 flex items-center gap-1">
            <button
              type="button"
              disabled={disabled || isTranscribing}
              onClick={() => imageInputRef.current?.click()}
              aria-label="Attach image"
              title="Attach image (JPEG, PNG, WebP)"
              className="rounded-xl p-2 text-slate-400 hover:bg-white/[0.06] hover:text-violet-200 transition disabled:opacity-40"
            >
              <ImageIcon size={18} />
            </button>

            <button
              type="button"
              disabled={disabled || isTranscribing}
              onClick={() => audioInputRef.current?.click()}
              aria-label="Upload audio file"
              title="Upload audio file to transcribe"
              className="rounded-xl p-2 text-slate-400 hover:bg-white/[0.06] hover:text-violet-200 transition disabled:opacity-40"
            >
              <FileAudio size={18} />
            </button>

            <button
              type="button"
              disabled={disabled || isTranscribing}
              onClick={startRecording}
              aria-label="Record voice note"
              title="Speak message (Speech-to-Text)"
              className="rounded-xl p-2 text-slate-400 hover:bg-white/[0.06] hover:text-rose-300 transition disabled:opacity-40"
            >
              <Mic size={18} />
            </button>
          </div>

          <textarea
            ref={textareaRef}
            rows={1}
            maxLength={8000}
            value={value}
            disabled={disabled || isTranscribing}
            onChange={(event) => {
              setValue(event.target.value);
              event.target.style.height = "auto";
              event.target.style.height = `${Math.min(event.target.scrollHeight, 192)}px`;
            }}
            onKeyDown={handleKeyDown}
            placeholder={
              attachedImage
                ? "Ask a question about this image…"
                : "Ask MNEMORA anything, speak, or drop an image/audio…"
            }
            aria-label="Message MNEMORA"
            className="max-h-48 min-h-[58px] w-full resize-none bg-transparent py-4 pl-32 pr-14 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-500 disabled:opacity-60"
          />

          <button
            type="submit"
            disabled={!canSend}
            aria-label="Send message"
            className="absolute bottom-3 right-3 grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 text-white shadow-[0_4px_18px_rgba(112,83,255,.24)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-none disabled:bg-white/[0.07] disabled:text-slate-600 disabled:shadow-none"
          >
            {disabled || isTranscribing ? (
              <LoaderCircle className="animate-spin" size={16} />
            ) : (
              <ArrowUp size={18} />
            )}
          </button>
        </div>
      )}

      <div className="mt-2 flex items-center justify-between px-1 text-[10px] text-slate-500">
        <span>Enter to send · Shift + Enter for new line · Drag & drop images or audio</span>
        {onVoiceMode && (
          <button
            type="button"
            onClick={onVoiceMode}
            className="inline-flex items-center gap-1 text-violet-300 hover:text-violet-200 transition"
          >
            <Mic size={11} /> Open Voice Mode
          </button>
        )}
      </div>
    </form>
  );
}
