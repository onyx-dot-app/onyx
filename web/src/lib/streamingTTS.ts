/**
 * Real-time streaming TTS using HTTP streaming with MediaSource Extensions.
 * Plays audio chunks as they arrive for smooth, low-latency playback.
 */

/**
 * HTTPStreamingTTSPlayer - Uses HTTP streaming with MediaSource Extensions
 * for smooth, gapless audio playback. This is the recommended approach for
 * real-time TTS as it properly handles MP3 frame boundaries.
 */
export class HTTPStreamingTTSPlayer {
  private mediaSource: MediaSource | null = null;
  private mediaSourceUrl: string | null = null;
  private sourceBuffer: SourceBuffer | null = null;
  private audioElement: HTMLAudioElement | null = null;
  private pendingChunks: Uint8Array[] = [];
  private isAppending: boolean = false;
  private isPlaying: boolean = false;
  private streamComplete: boolean = false;
  private onPlayingChange?: (playing: boolean) => void;
  private onError?: (error: string) => void;
  private abortController: AbortController | null = null;

  constructor(options?: {
    onPlayingChange?: (playing: boolean) => void;
    onError?: (error: string) => void;
  }) {
    this.onPlayingChange = options?.onPlayingChange;
    this.onError = options?.onError;
  }

  private getAPIUrl(): string {
    // Always go through the frontend proxy to ensure cookies are sent correctly
    // The Next.js proxy at /api/* forwards to the backend
    return "/api/voice/synthesize";
  }

  /**
   * Speak text using HTTP streaming with real-time playback.
   * Audio begins playing as soon as the first chunks arrive.
   */
  async speak(
    text: string,
    voice?: string,
    speed: number = 1.0
  ): Promise<void> {
    // Cleanup any previous playback
    this.cleanup();

    // Create abort controller for this request
    this.abortController = new AbortController();

    // Build URL with query params
    const params = new URLSearchParams();
    params.set("text", text);
    if (voice) params.set("voice", voice);
    params.set("speed", speed.toString());

    const url = `${this.getAPIUrl()}?${params}`;

    // Check if MediaSource is supported
    if (!window.MediaSource || !MediaSource.isTypeSupported("audio/mpeg")) {
      // Fallback to simple buffered playback
      return this.fallbackSpeak(url);
    }

    // Create MediaSource and audio element
    this.mediaSource = new MediaSource();
    this.audioElement = new Audio();
    this.mediaSourceUrl = URL.createObjectURL(this.mediaSource);
    this.audioElement.src = this.mediaSourceUrl;

    // Set up audio element event handlers
    this.audioElement.onplay = () => {
      if (!this.isPlaying) {
        this.isPlaying = true;
        this.onPlayingChange?.(true);
      }
    };

    this.audioElement.onended = () => {
      this.isPlaying = false;
      this.onPlayingChange?.(false);
    };

    this.audioElement.onerror = () => {
      this.onError?.("Audio playback error");
      this.isPlaying = false;
      this.onPlayingChange?.(false);
    };

    // Wait for MediaSource to be ready
    await new Promise<void>((resolve, reject) => {
      if (!this.mediaSource) {
        reject(new Error("MediaSource not initialized"));
        return;
      }

      this.mediaSource.onsourceopen = () => {
        try {
          // Create SourceBuffer for MP3
          this.sourceBuffer = this.mediaSource!.addSourceBuffer("audio/mpeg");
          this.sourceBuffer.mode = "sequence";

          this.sourceBuffer.onupdateend = () => {
            this.isAppending = false;
            this.processNextChunk();
          };

          resolve();
        } catch (err) {
          reject(err);
        }
      };

      // MediaSource doesn't have onerror in all browsers, use onsourceclose as fallback
      this.mediaSource.onsourceclose = () => {
        if (this.mediaSource?.readyState === "closed") {
          reject(new Error("MediaSource closed unexpectedly"));
        }
      };
    });

    // Start fetching and streaming audio
    try {
      const response = await fetch(url, {
        method: "POST",
        signal: this.abortController.signal,
        credentials: "include", // Include cookies for authentication
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `TTS request failed: ${response.status} - ${errorText}`
        );
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body");
      }

      // Start playback as soon as we have some data
      let firstChunk = true;

      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          this.streamComplete = true;
          // End the stream when all chunks are appended
          this.finalizeStream();
          break;
        }

        if (value) {
          this.pendingChunks.push(value);
          this.processNextChunk();

          // Start playback after first chunk
          if (firstChunk && this.audioElement) {
            firstChunk = false;
            // Small delay to buffer a bit before starting
            setTimeout(() => {
              this.audioElement?.play().catch(() => {
                // Ignore playback start errors
              });
            }, 100);
          }
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        return;
      }
      this.onError?.(err instanceof Error ? err.message : "TTS error");
      throw err;
    }
  }

  /**
   * Process next chunk from the queue.
   */
  private processNextChunk(): void {
    if (
      this.isAppending ||
      this.pendingChunks.length === 0 ||
      !this.sourceBuffer ||
      this.sourceBuffer.updating
    ) {
      return;
    }

    const chunk = this.pendingChunks.shift();
    if (chunk) {
      this.isAppending = true;
      try {
        // Use ArrayBuffer directly for better TypeScript compatibility
        const buffer = chunk.buffer.slice(
          chunk.byteOffset,
          chunk.byteOffset + chunk.byteLength
        ) as ArrayBuffer;
        this.sourceBuffer.appendBuffer(buffer);
      } catch {
        this.isAppending = false;
        // Try next chunk
        this.processNextChunk();
      }
    }
  }

  /**
   * Finalize the stream when all data has been received.
   */
  private finalizeStream(): void {
    if (this.pendingChunks.length > 0 || this.isAppending) {
      // Wait for remaining chunks to be appended
      setTimeout(() => this.finalizeStream(), 50);
      return;
    }

    if (
      this.mediaSource &&
      this.mediaSource.readyState === "open" &&
      this.sourceBuffer &&
      !this.sourceBuffer.updating
    ) {
      try {
        this.mediaSource.endOfStream();
      } catch {
        // Ignore errors when ending stream
      }
    }
  }

  /**
   * Fallback for browsers that don't support MediaSource Extensions.
   * Buffers all audio before playing.
   */
  private async fallbackSpeak(url: string): Promise<void> {
    const response = await fetch(url, {
      method: "POST",
      signal: this.abortController?.signal,
      credentials: "include", // Include cookies for authentication
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`TTS request failed: ${response.status} - ${errorText}`);
    }

    const audioData = await response.arrayBuffer();

    const blob = new Blob([audioData], { type: "audio/mpeg" });
    const audioUrl = URL.createObjectURL(blob);

    this.audioElement = new Audio(audioUrl);

    this.audioElement.onplay = () => {
      this.isPlaying = true;
      this.onPlayingChange?.(true);
    };

    this.audioElement.onended = () => {
      this.isPlaying = false;
      this.onPlayingChange?.(false);
      URL.revokeObjectURL(audioUrl);
    };

    this.audioElement.onerror = () => {
      this.onError?.("Audio playback error");
    };

    await this.audioElement.play();
  }

  /**
   * Stop playback and cleanup resources.
   */
  stop(): void {
    // Abort any ongoing request
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }

    this.cleanup();
  }

  /**
   * Cleanup all resources.
   */
  private cleanup(): void {
    // Revoke Object URL to prevent memory leak
    if (this.mediaSourceUrl) {
      URL.revokeObjectURL(this.mediaSourceUrl);
      this.mediaSourceUrl = null;
    }

    // Stop and cleanup audio element
    if (this.audioElement) {
      this.audioElement.pause();
      this.audioElement.src = "";
      this.audioElement = null;
    }

    // Cleanup MediaSource
    if (this.mediaSource && this.mediaSource.readyState === "open") {
      try {
        if (this.sourceBuffer) {
          this.mediaSource.removeSourceBuffer(this.sourceBuffer);
        }
        this.mediaSource.endOfStream();
      } catch {
        // Ignore cleanup errors
      }
    }

    this.mediaSource = null;
    this.sourceBuffer = null;
    this.pendingChunks = [];
    this.isAppending = false;
    this.streamComplete = false;

    if (this.isPlaying) {
      this.isPlaying = false;
      this.onPlayingChange?.(false);
    }
  }

  get playing(): boolean {
    return this.isPlaying;
  }
}

/**
 * WebSocketStreamingTTSPlayer - Uses WebSocket for bidirectional streaming.
 * Useful for scenarios where you want to stream text in and get audio out
 * incrementally (e.g., as LLM generates text).
 */
export class WebSocketStreamingTTSPlayer {
  private websocket: WebSocket | null = null;
  private mediaSource: MediaSource | null = null;
  private mediaSourceUrl: string | null = null;
  private sourceBuffer: SourceBuffer | null = null;
  private audioElement: HTMLAudioElement | null = null;
  private pendingChunks: Uint8Array[] = [];
  private isAppending: boolean = false;
  private isPlaying: boolean = false;
  private onPlayingChange?: (playing: boolean) => void;
  private onError?: (error: string) => void;
  private hasStartedPlayback: boolean = false;

  constructor(options?: {
    onPlayingChange?: (playing: boolean) => void;
    onError?: (error: string) => void;
  }) {
    this.onPlayingChange = options?.onPlayingChange;
    this.onError = options?.onError;
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
      ? "/voice/synthesize/stream"
      : "/api/voice/synthesize/stream";
    return `${protocol}//${host}${path}?token=${encodeURIComponent(token)}`;
  }

  async connect(voice?: string, speed?: number): Promise<void> {
    // Cleanup any previous connection
    this.cleanup();

    // Check MediaSource support
    if (!window.MediaSource || !MediaSource.isTypeSupported("audio/mpeg")) {
      throw new Error("MediaSource Extensions not supported");
    }

    // Create MediaSource and audio element
    this.mediaSource = new MediaSource();
    this.audioElement = new Audio();
    this.mediaSourceUrl = URL.createObjectURL(this.mediaSource);
    this.audioElement.src = this.mediaSourceUrl;

    this.audioElement.onplay = () => {
      if (!this.isPlaying) {
        this.isPlaying = true;
        this.onPlayingChange?.(true);
      }
    };

    this.audioElement.onended = () => {
      this.isPlaying = false;
      this.onPlayingChange?.(false);
    };

    // Wait for MediaSource to be ready
    await new Promise<void>((resolve, reject) => {
      this.mediaSource!.onsourceopen = () => {
        try {
          this.sourceBuffer = this.mediaSource!.addSourceBuffer("audio/mpeg");
          this.sourceBuffer.mode = "sequence";
          this.sourceBuffer.onupdateend = () => {
            this.isAppending = false;
            this.processNextChunk();
          };
          resolve();
        } catch (err) {
          reject(err);
        }
      };
    });

    // Connect WebSocket
    const url = await this.getWebSocketUrl();
    return new Promise((resolve, reject) => {
      this.websocket = new WebSocket(url);

      this.websocket.onopen = () => {
        // Send initial config
        this.websocket?.send(
          JSON.stringify({
            type: "config",
            voice: voice,
            speed: speed || 1.0,
          })
        );
        resolve();
      };

      this.websocket.onerror = () => {
        reject(new Error("WebSocket connection failed"));
      };

      this.websocket.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          // Audio chunk received
          const arrayBuffer = await event.data.arrayBuffer();
          this.pendingChunks.push(new Uint8Array(arrayBuffer));
          this.processNextChunk();

          // Start playback after first chunk
          if (!this.hasStartedPlayback && this.audioElement) {
            this.hasStartedPlayback = true;
            setTimeout(() => {
              this.audioElement?.play().catch(() => {
                // Ignore playback errors
              });
            }, 100);
          }
        } else {
          // JSON message
          try {
            const data = JSON.parse(event.data);
            if (data.type === "audio_done") {
              this.finalizeStream();
            } else if (data.type === "error") {
              this.onError?.(data.message);
            }
          } catch {
            // Ignore parse errors
          }
        }
      };

      this.websocket.onclose = () => {
        this.finalizeStream();
      };
    });
  }

  private processNextChunk(): void {
    if (
      this.isAppending ||
      this.pendingChunks.length === 0 ||
      !this.sourceBuffer ||
      this.sourceBuffer.updating
    ) {
      return;
    }

    const chunk = this.pendingChunks.shift();
    if (chunk) {
      this.isAppending = true;
      try {
        // Use ArrayBuffer directly for better TypeScript compatibility
        const buffer = chunk.buffer.slice(
          chunk.byteOffset,
          chunk.byteOffset + chunk.byteLength
        ) as ArrayBuffer;
        this.sourceBuffer.appendBuffer(buffer);
      } catch {
        this.isAppending = false;
        this.processNextChunk();
      }
    }
  }

  private finalizeStream(): void {
    if (this.pendingChunks.length > 0 || this.isAppending) {
      setTimeout(() => this.finalizeStream(), 50);
      return;
    }

    if (
      this.mediaSource &&
      this.mediaSource.readyState === "open" &&
      this.sourceBuffer &&
      !this.sourceBuffer.updating
    ) {
      try {
        this.mediaSource.endOfStream();
      } catch {
        // Ignore
      }
    }
  }

  async speak(text: string): Promise<void> {
    if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket not connected");
    }

    this.websocket.send(
      JSON.stringify({
        type: "synthesize",
        text: text,
      })
    );
  }

  stop(): void {
    this.cleanup();
  }

  disconnect(): void {
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
      this.websocket.send(JSON.stringify({ type: "end" }));
      this.websocket.close();
    }
    this.cleanup();
  }

  private cleanup(): void {
    if (this.websocket) {
      this.websocket.close();
      this.websocket = null;
    }

    // Revoke Object URL to prevent memory leak
    if (this.mediaSourceUrl) {
      URL.revokeObjectURL(this.mediaSourceUrl);
      this.mediaSourceUrl = null;
    }

    if (this.audioElement) {
      this.audioElement.pause();
      this.audioElement.src = "";
      this.audioElement = null;
    }

    if (this.mediaSource && this.mediaSource.readyState === "open") {
      try {
        if (this.sourceBuffer) {
          this.mediaSource.removeSourceBuffer(this.sourceBuffer);
        }
        this.mediaSource.endOfStream();
      } catch {
        // Ignore
      }
    }

    this.mediaSource = null;
    this.sourceBuffer = null;
    this.pendingChunks = [];
    this.isAppending = false;
    this.hasStartedPlayback = false;

    if (this.isPlaying) {
      this.isPlaying = false;
      this.onPlayingChange?.(false);
    }
  }

  get playing(): boolean {
    return this.isPlaying;
  }
}

// Export the HTTP player as the default/recommended option
export { HTTPStreamingTTSPlayer as StreamingTTSPlayer };
