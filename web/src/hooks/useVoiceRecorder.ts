import { useState, useRef, useCallback, useEffect } from "react";

// Target format for OpenAI Realtime API
const TARGET_SAMPLE_RATE = 24000;
const CHUNK_INTERVAL_MS = 250;
const SILENCE_TIMEOUT_MS = 5000; // Stop recording if no speech detected for 5 seconds

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
  isProcessing: boolean;
  isMuted: boolean;
  error: string | null;
  liveTranscript: string;
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
  private silenceTimeout: NodeJS.Timeout | null = null;

  // Callbacks to update React state
  private onTranscriptChange: (text: string) => void;
  private onFinalTranscript: ((text: string) => void) | null;
  private onError: (error: string) => void;
  private onSilenceTimeout: (() => void) | null;
  private onVADStop: (() => void) | null;
  private autoStopOnSilence: boolean;

  constructor(
    onTranscriptChange: (text: string) => void,
    onFinalTranscript: ((text: string) => void) | null,
    onError: (error: string) => void,
    onSilenceTimeout?: () => void,
    autoStopOnSilence?: boolean,
    onVADStop?: () => void
  ) {
    this.onTranscriptChange = onTranscriptChange;
    this.onFinalTranscript = onFinalTranscript;
    this.onError = onError;
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

  async start(): Promise<void> {
    if (this.isActive) return;

    this.cleanup();
    this.transcript = "";
    this.audioBuffer = [];

    // Get microphone
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: { ideal: TARGET_SAMPLE_RATE },
        echoCancellation: true,
        noiseSuppression: true,
      },
    });

    // Get WS token and connect WebSocket
    const wsUrl = await this.getWebSocketUrl();
    this.websocket = new WebSocket(wsUrl);
    this.websocket.onmessage = this.handleMessage;
    this.websocket.onerror = () => this.onError("Connection failed");
    this.websocket.onclose = () => {
      if (this.stopResolver) {
        this.stopResolver(this.transcript || null);
        this.stopResolver = null;
      }
    };

    await this.waitForConnection();

    // Set up audio capture
    this.audioContext = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
    this.sourceNode = this.audioContext.createMediaStreamSource(
      this.mediaStream
    );
    this.scriptNode = this.audioContext.createScriptProcessor(4096, 1, 1);

    this.scriptNode.onaudioprocess = (event) => {
      const inputData = event.inputBuffer.getChannelData(0);
      this.audioBuffer.push(new Float32Array(inputData));
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

  private async getWebSocketUrl(): Promise<string> {
    // Fetch short-lived WS token
    const tokenResponse = await fetch("/api/voice/ws-token", {
      method: "POST",
      credentials: "include",
    });
    if (!tokenResponse.ok) {
      throw new Error("Failed to get WebSocket authentication token");
    }
    const { token } = await tokenResponse.json();

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const isDev = window.location.port === "3000";
    const host = isDev ? "localhost:8080" : window.location.host;
    const path = isDev
      ? "/voice/transcribe/stream"
      : "/api/voice/transcribe/stream";
    return `${protocol}//${host}${path}?token=${encodeURIComponent(token)}`;
  }

  private waitForConnection(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.websocket) return reject(new Error("No WebSocket"));

      const timeout = setTimeout(
        () => reject(new Error("Connection timeout")),
        5000
      );

      this.websocket.onopen = () => {
        clearTimeout(timeout);
        resolve();
      };
      this.websocket.onerror = () => {
        clearTimeout(timeout);
        reject(new Error("Connection failed"));
      };
    });
  }

  private handleMessage = (event: MessageEvent): void => {
    try {
      const data: TranscriptMessage = JSON.parse(event.data);

      if (data.type === "transcript") {
        if (data.text) {
          this.transcript = data.text;
          this.onTranscriptChange(data.text);
        }

        if (data.is_final && data.text) {
          // VAD detected silence - trigger callback
          if (this.onFinalTranscript) {
            this.onFinalTranscript(data.text);
          }

          // Auto-stop recording if enabled
          if (this.autoStopOnSilence) {
            // Trigger stop callback to update React state
            if (this.onVADStop) {
              this.onVADStop();
            }
          } else {
            // If not auto-stopping, reset for next utterance
            this.transcript = "";
            this.onTranscriptChange("");
            this.resetBackendTranscript();
          }

          // Resolve stop promise if waiting
          if (this.stopResolver) {
            this.stopResolver(data.text);
            this.stopResolver = null;
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

  private float32ToInt16(float32: Float32Array): Int16Array {
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
  const [isProcessing, setIsProcessing] = useState(false);
  const [isMuted, setIsMutedState] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [liveTranscript, setLiveTranscript] = useState("");

  const sessionRef = useRef<VoiceRecorderSession | null>(null);
  const onFinalTranscriptRef = useRef(options?.onFinalTranscript);
  const autoStopOnSilenceRef = useRef(options?.autoStopOnSilence ?? true); // Default to true

  // Keep callback ref in sync
  useEffect(() => {
    onFinalTranscriptRef.current = options?.onFinalTranscript;
    autoStopOnSilenceRef.current = options?.autoStopOnSilence ?? true;
  }, [options?.onFinalTranscript, options?.autoStopOnSilence]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      sessionRef.current?.cleanup();
    };
  }, []);

  const startRecording = useCallback(async () => {
    if (sessionRef.current?.recording) return;

    setError(null);
    setLiveTranscript("");

    // Create VAD stop handler that will stop the session
    const handleVADStop = () => {
      if (sessionRef.current) {
        sessionRef.current.stop().then(() => {
          setIsRecording(false);
        });
      }
    };

    sessionRef.current = new VoiceRecorderSession(
      setLiveTranscript,
      (text) => onFinalTranscriptRef.current?.(text),
      setError,
      undefined, // onSilenceTimeout
      autoStopOnSilenceRef.current,
      handleVADStop
    );

    try {
      await sessionRef.current.start();
      setIsRecording(true);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start recording"
      );
      throw err;
    }
  }, []);

  const stopRecording = useCallback(async (): Promise<string | null> => {
    if (!sessionRef.current) return null;

    setIsProcessing(true);

    try {
      const transcript = await sessionRef.current.stop();
      return transcript;
    } finally {
      setIsRecording(false);
      setIsProcessing(false);
      setIsMutedState(false); // Reset mute state when recording stops
    }
  }, []);

  const setMuted = useCallback((muted: boolean) => {
    setIsMutedState(muted);
    sessionRef.current?.setMuted(muted);
  }, []);

  return {
    isRecording,
    isProcessing,
    isMuted,
    error,
    liveTranscript,
    startRecording,
    stopRecording,
    setMuted,
  };
}
