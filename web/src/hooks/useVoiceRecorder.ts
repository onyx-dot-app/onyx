import { useState, useRef, useCallback, useEffect } from "react";

import { INTERNAL_URL, IS_DEV } from "@/lib/constants";

// Target format for OpenAI Realtime API
const TARGET_SAMPLE_RATE = 24000;
const CHUNK_INTERVAL_MS = 250;
const DUPLICATE_FINAL_TRANSCRIPT_WINDOW_MS = 1500;
const VOICE_STARTUP_TIMEOUT_MS = 10000;
// When VAD-based auto-stop is disabled, force-stop after this much silence as a fallback
const SILENCE_FALLBACK_TIMEOUT_MS = 10000;

interface TranscriptMessage {
  type: "transcript" | "error";
  text?: string;
  message?: string;
  is_final?: boolean;
}

export interface UseVoiceRecorderOptions {
  /** Called when VAD detects silence and final transcript is received */
  onFinalTranscript?: (text: string) => void;
  /** If true, automatically stop recording when VAD detects silence */
  autoStopOnSilence?: boolean;
}

export interface UseVoiceRecorderReturn {
  isRecording: boolean;
  isStarting: boolean;
  isProcessing: boolean;
  isMuted: boolean;
  error: string | null;
  liveTranscript: string;
  /** Current microphone audio level (0-1, RMS-based) */
  audioLevel: number;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<string | null>;
  setMuted: (muted: boolean) => void;
}

/**
 * Encapsulates all browser resources for a voice recording session.
 * Manages WebSocket, Web Audio API, and audio buffering.
 */
class VoiceRecorderSession {
  // Browser resources
  private websocket: WebSocket | null = null;
  private audioContext: AudioContext | null = null;
  private scriptNode: ScriptProcessorNode | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private mediaStream: MediaStream | null = null;
  private sendInterval: NodeJS.Timeout | null = null;

  // State
  private audioBuffer: Float32Array[] = [];
  private transcript = "";
  private stopResolver: ((text: string | null) => void) | null = null;
  private isActive = false;
  private disposed = false;
  // Guard: true once onFinalTranscript has fired for the current utterance.
  // Prevents the same transcript from being delivered twice when VAD-triggered
  // stop causes the server to echo the final transcript a second time.
  private finalTranscriptDelivered = false;
  private lastDeliveredFinalText: string | null = null;
  private lastDeliveredFinalAtMs = 0;
  // Fallback timer: force-stop after extended silence when VAD auto-stop is disabled
  private silenceFallbackTimer: NodeJS.Timeout | null = null;

  // Callbacks to update React state
  private onTranscriptChange: (text: string) => void;
  private onFinalTranscript: ((text: string) => void) | null;
  private onError: (error: string) => void;
  private onAudioLevel: (level: number) => void;
  private onSilenceTimeout: (() => void) | null;
  private onVADStop: (() => void) | null;
  private autoStopOnSilence: boolean;

  constructor(
    onTranscriptChange: (text: string) => void,
    onFinalTranscript: ((text: string) => void) | null,
    onError: (error: string) => void,
    onAudioLevel: (level: number) => void,
    onSilenceTimeout?: () => void,
    autoStopOnSilence?: boolean,
    onVADStop?: () => void
  ) {
    this.onTranscriptChange = onTranscriptChange;
    this.onFinalTranscript = onFinalTranscript;
    this.onError = onError;
    this.onAudioLevel = onAudioLevel;
    this.onSilenceTimeout = onSilenceTimeout || null;
    this.autoStopOnSilence = autoStopOnSilence ?? false;
    this.onVADStop = onVADStop || null;
  }

  get recording(): boolean {
    return this.isActive;
  }

  get currentTranscript(): string {
    return this.transcript;
  }

  setMuted(muted: boolean): void {
    if (this.mediaStream) {
      this.mediaStream.getAudioTracks().forEach((track) => {
        track.enabled = !muted;
      });
    }
  }

  async start(signal: AbortSignal): Promise<void> {
    if (this.isActive) return;

    this.throwIfDisposed();
    this.transcript = "";
    this.audioBuffer = [];
    this.finalTranscriptDelivered = false;
    this.lastDeliveredFinalText = null;
    this.lastDeliveredFinalAtMs = 0;

    // Get microphone
    const mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: { ideal: TARGET_SAMPLE_RATE },
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    if (this.disposed) {
      mediaStream.getTracks().forEach((track) => track.stop());
      this.throwIfDisposed();
    }
    this.mediaStream = mediaStream;

    // Get WS token and connect WebSocket
    const wsUrl = await this.getWebSocketUrl(signal);
    this.throwIfDisposed();
    this.websocket = new WebSocket(wsUrl);
    this.websocket.onmessage = this.handleMessage;
    this.websocket.onerror = () => this.onError("Connection failed");
    this.websocket.onclose = () => {
      if (this.stopResolver) {
        this.stopResolver(this.transcript || null);
        this.stopResolver = null;
      }
    };

    await this.waitForConnection(signal);
    this.throwIfDisposed();

    // Restore error handler after connection (waitForConnection overwrites it)
    this.websocket.onerror = () => this.onError("Connection failed");

    // Set up audio capture
    this.audioContext = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
    this.sourceNode = this.audioContext.createMediaStreamSource(
      this.mediaStream
    );
    this.scriptNode = this.audioContext.createScriptProcessor(4096, 1, 1);

    this.scriptNode.onaudioprocess = (event) => {
      const inputData = event.inputBuffer.getChannelData(0);
      this.audioBuffer.push(new Float32Array(inputData));

      // Compute RMS audio level (0-1) for waveform visualization
      let sum = 0;
      for (let i = 0; i < inputData.length; i++) {
        sum += inputData[i]! * inputData[i]!;
      }
      const rms = Math.sqrt(sum / inputData.length);
      // Scale RMS to a more visible range (raw RMS is usually very small)
      this.onAudioLevel(Math.min(1, rms * 5));
    };

    this.sourceNode.connect(this.scriptNode);
    this.scriptNode.connect(this.audioContext.destination);

    // Start sending audio chunks
    this.sendInterval = setInterval(
      () => this.sendAudioBuffer(),
      CHUNK_INTERVAL_MS
    );
    this.isActive = true;
  }

  async stop(): Promise<string | null> {
    if (!this.isActive) return this.transcript || null;

    this.resetSilenceFallbackTimer();

    // Stop audio capture
    if (this.sendInterval) {
      clearInterval(this.sendInterval);
      this.sendInterval = null;
    }
    if (this.scriptNode) {
      this.scriptNode.disconnect();
      this.scriptNode = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }

    this.audioBuffer = [];
    this.isActive = false;

    // Get final transcript from server
    if (this.websocket?.readyState === WebSocket.OPEN) {
      return new Promise((resolve) => {
        this.stopResolver = resolve;
        this.websocket!.send(JSON.stringify({ type: "end" }));

        // Timeout fallback
        setTimeout(() => {
          if (this.stopResolver) {
            this.stopResolver(this.transcript || null);
            this.stopResolver = null;
          }
        }, 3000);
      });
    }

    return this.transcript || null;
  }

  cleanup(): void {
    this.disposed = true;
    this.resetSilenceFallbackTimer();
    if (this.sendInterval) clearInterval(this.sendInterval);
    if (this.scriptNode) this.scriptNode.disconnect();
    if (this.sourceNode) this.sourceNode.disconnect();
    if (this.audioContext) this.audioContext.close();
    if (this.mediaStream) this.mediaStream.getTracks().forEach((t) => t.stop());
    if (this.websocket) this.websocket.close();

    this.sendInterval = null;
    this.scriptNode = null;
    this.sourceNode = null;
    this.audioContext = null;
    this.mediaStream = null;
    this.websocket = null;
    this.isActive = false;
  }

  private throwIfDisposed(): void {
    if (this.disposed) {
      throw new DOMException("Recording startup cancelled", "AbortError");
    }
  }

  private async getWebSocketUrl(signal: AbortSignal): Promise<string> {
    // Fetch short-lived WS token
    const tokenResponse = await fetch("/api/voice/ws-token", {
      method: "POST",
      credentials: "include",
      signal,
    });
    if (!tokenResponse.ok) {
      throw new Error("Failed to get WebSocket authentication token");
    }
    const { token } = await tokenResponse.json();

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = IS_DEV ? new URL(INTERNAL_URL).host : window.location.host;
    const path = IS_DEV
      ? "/voice/transcribe/stream"
      : "/api/voice/transcribe/stream";
    return `${protocol}//${host}${path}?token=${encodeURIComponent(token)}`;
  }

  private waitForConnection(signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      const websocket = this.websocket;
      if (!websocket) return reject(new Error("No WebSocket"));

      const cleanup = () => {
        clearTimeout(timeout);
        websocket.removeEventListener("open", handleOpen);
        websocket.removeEventListener("error", handleError);
        websocket.removeEventListener("close", handleClose);
        signal.removeEventListener("abort", handleAbort);
      };

      const succeed = () => {
        cleanup();
        resolve();
      };
      const fail = (error: Error) => {
        cleanup();
        reject(error);
      };

      const handleOpen = () => succeed();
      const handleError = () => fail(new Error("Connection failed"));
      const handleClose = () => fail(new Error("Connection closed"));
      const handleAbort = () =>
        fail(new DOMException("Recording startup cancelled", "AbortError"));
      const timeout = setTimeout(
        () => fail(new Error("Connection timeout")),
        5000
      );

      websocket.addEventListener("open", handleOpen, { once: true });
      websocket.addEventListener("error", handleError, { once: true });
      websocket.addEventListener("close", handleClose, { once: true });
      signal.addEventListener("abort", handleAbort, { once: true });
      if (signal.aborted) {
        handleAbort();
      }
    });
  }

  private resetSilenceFallbackTimer(): void {
    if (this.silenceFallbackTimer) {
      clearTimeout(this.silenceFallbackTimer);
      this.silenceFallbackTimer = null;
    }
  }

  private startSilenceFallbackTimer(): void {
    this.resetSilenceFallbackTimer();
    this.silenceFallbackTimer = setTimeout(() => {
      // 10s of silence with no new speech — force-stop as a safety fallback
      if (this.isActive && this.onVADStop) {
        this.onVADStop();
      }
    }, SILENCE_FALLBACK_TIMEOUT_MS);
  }

  private handleMessage = (event: MessageEvent): void => {
    try {
      const data: TranscriptMessage = JSON.parse(event.data);

      if (data.type === "transcript") {
        if (data.text) {
          this.transcript = data.text;
          // Only push live updates to React while actively recording.
          // After stop(), the final transcript is returned via stopResolver
          // instead — this prevents stale text from reappearing in the
          // input box when the user clears it and starts a new recording.
          if (this.isActive) {
            this.onTranscriptChange(data.text);
          }
        }

        if (data.is_final && data.text) {
          // Resolve stop promise if waiting — must run even after stop()
          // so the caller receives the final transcript.
          if (this.stopResolver) {
            this.stopResolver(data.text);
            this.stopResolver = null;
          }

          // Skip VAD logic if session is no longer active
          if (!this.isActive) return;

          if (this.autoStopOnSilence) {
            // VAD detected silence — auto-stop and trigger callback
            const now = Date.now();
            const isLikelyDuplicateFinal =
              this.lastDeliveredFinalText === data.text &&
              now - this.lastDeliveredFinalAtMs <
                DUPLICATE_FINAL_TRANSCRIPT_WINDOW_MS;

            if (
              this.onFinalTranscript &&
              !this.finalTranscriptDelivered &&
              !isLikelyDuplicateFinal
            ) {
              this.finalTranscriptDelivered = true;
              this.lastDeliveredFinalText = data.text;
              this.lastDeliveredFinalAtMs = now;
              this.onFinalTranscript(data.text);
            }

            if (this.onVADStop) {
              this.onVADStop();
            }
          } else {
            // Auto-stop disabled (push-to-talk): ignore VAD, keep recording.
            // Start/reset a 10s fallback timer — if no new speech arrives,
            // force-stop to avoid recording silence indefinitely.
            this.startSilenceFallbackTimer();
          }
        }
      } else if (data.type === "error") {
        this.onError(data.message || "Transcription error");
      }
    } catch (e) {
      console.error("Failed to parse transcript message:", e);
    }
  };

  private resetBackendTranscript(): void {
    if (this.websocket?.readyState === WebSocket.OPEN) {
      this.websocket.send(JSON.stringify({ type: "reset" }));
    }
  }

  private sendAudioBuffer(): void {
    if (
      !this.websocket ||
      this.websocket.readyState !== WebSocket.OPEN ||
      !this.audioContext ||
      this.audioBuffer.length === 0
    ) {
      return;
    }

    // Concatenate buffered chunks
    const totalLength = this.audioBuffer.reduce(
      (sum, chunk) => sum + chunk.length,
      0
    );

    // Prevent buffer overflow
    if (totalLength > this.audioContext.sampleRate * 0.5 * 2) {
      this.audioBuffer = this.audioBuffer.slice(-10);
      return;
    }

    const concatenated = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of this.audioBuffer) {
      concatenated.set(chunk, offset);
      offset += chunk.length;
    }
    this.audioBuffer = [];

    // Resample and convert to PCM16
    const resampled = this.resampleAudio(
      concatenated,
      this.audioContext.sampleRate
    );
    const pcm16 = this.float32ToInt16(resampled);

    this.websocket.send(pcm16.buffer);
  }

  private resampleAudio(input: Float32Array, inputRate: number): Float32Array {
    if (inputRate === TARGET_SAMPLE_RATE) return input;

    const ratio = inputRate / TARGET_SAMPLE_RATE;
    const outputLength = Math.round(input.length / ratio);
    const output = new Float32Array(outputLength);

    for (let i = 0; i < outputLength; i++) {
      const srcIndex = i * ratio;
      const floor = Math.floor(srcIndex);
      const ceil = Math.min(floor + 1, input.length - 1);
      const fraction = srcIndex - floor;
      output[i] = input[floor]! * (1 - fraction) + input[ceil]! * fraction;
    }

    return output;
  }

  private float32ToInt16(float32: Float32Array): Int16Array<ArrayBuffer> {
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]!));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return int16;
  }
}

/**
 * Hook for voice recording with streaming transcription.
 */
export function useVoiceRecorder(
  options?: UseVoiceRecorderOptions
): UseVoiceRecorderReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isMuted, setIsMutedState] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [audioLevel, setAudioLevel] = useState(0);

  const sessionRef = useRef<VoiceRecorderSession | null>(null);
  const isStartingRef = useRef(false);
  const isMountedRef = useRef(false);
  const onFinalTranscriptRef = useRef(options?.onFinalTranscript);
  const autoStopOnSilenceRef = useRef(options?.autoStopOnSilence ?? true); // Default to true

  // Keep callback ref in sync
  useEffect(() => {
    onFinalTranscriptRef.current = options?.onFinalTranscript;
    autoStopOnSilenceRef.current = options?.autoStopOnSilence ?? true;
  }, [options?.onFinalTranscript, options?.autoStopOnSilence]);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      isStartingRef.current = false;
      const session = sessionRef.current;
      sessionRef.current = null;
      session?.cleanup();
    };
  }, []);

  const startRecording = useCallback(async () => {
    if (isStartingRef.current || sessionRef.current?.recording) return;

    isStartingRef.current = true;
    setIsStarting(true);

    setError(null);
    setLiveTranscript("");

    // Clear any stale, inactive session before starting a new one.
    if (sessionRef.current && !sessionRef.current.recording) {
      sessionRef.current.cleanup();
      sessionRef.current = null;
    }

    // Create VAD stop handler that will stop the session
    const currentSession = new VoiceRecorderSession(
      setLiveTranscript,
      (text) => onFinalTranscriptRef.current?.(text),
      setError,
      setAudioLevel,
      undefined, // onSilenceTimeout
      autoStopOnSilenceRef.current,
      () => {
        // Stop only this session instance, and only clear recording state if it
        // is still the active session when stop resolves.
        currentSession.stop().then(() => {
          if (sessionRef.current === currentSession) {
            setIsRecording(false);
            setIsMutedState(false);
            sessionRef.current = null;
          }
        });
      }
    );
    sessionRef.current = currentSession;
    const abortController = new AbortController();
    let startupTimeout: ReturnType<typeof setTimeout> | null = null;

    try {
      const timeout = new Promise<never>((_resolve, reject) => {
        startupTimeout = setTimeout(() => {
          abortController.abort();
          currentSession.cleanup();
          reject(new Error("Microphone startup timed out"));
        }, VOICE_STARTUP_TIMEOUT_MS);
      });
      await Promise.race([
        currentSession.start(abortController.signal),
        timeout,
      ]);
      if (sessionRef.current === currentSession && currentSession.recording) {
        setIsRecording(true);
      } else {
        currentSession.cleanup();
      }
    } catch (err) {
      currentSession.cleanup();
      if (sessionRef.current === currentSession) {
        sessionRef.current = null;
      }
      if (!isMountedRef.current) {
        return;
      }
      setError(
        err instanceof Error ? err.message : "Failed to start recording"
      );
      throw err;
    } finally {
      abortController.abort();
      if (startupTimeout) {
        clearTimeout(startupTimeout);
      }
      isStartingRef.current = false;
      if (isMountedRef.current) {
        setIsStarting(false);
      }
    }
  }, []);

  const stopRecording = useCallback(async (): Promise<string | null> => {
    if (!sessionRef.current) return null;
    const currentSession = sessionRef.current;

    setIsProcessing(true);

    try {
      const transcript = await currentSession.stop();
      return transcript;
    } finally {
      // Only clear state if this is still the active session.
      if (sessionRef.current === currentSession) {
        setIsRecording(false);
        setIsMutedState(false); // Reset mute state when recording stops
        sessionRef.current = null;
      }
      setIsProcessing(false);
    }
  }, []);

  const setMuted = useCallback((muted: boolean) => {
    setIsMutedState(muted);
    sessionRef.current?.setMuted(muted);
  }, []);

  return {
    isRecording,
    isStarting,
    isProcessing,
    isMuted,
    error,
    liveTranscript,
    audioLevel,
    startRecording,
    stopRecording,
    setMuted,
  };
}
