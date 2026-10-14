import { act, renderHook, waitFor } from "@testing-library/react";

import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";

class TestWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: TestWebSocket[] = [];

  readonly close = jest.fn(() => {
    this.readyState = TestWebSocket.CLOSED;
    this.dispatch("close");
  });
  readonly send = jest.fn();
  readyState = TestWebSocket.CONNECTING;
  onclose: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  private listeners = new Map<string, Set<EventListener>>();

  constructor(readonly url: string) {
    TestWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener): void {
    const listeners = this.listeners.get(type) ?? new Set<EventListener>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: EventListener): void {
    this.listeners.get(type)?.delete(listener);
  }

  open(): void {
    this.readyState = TestWebSocket.OPEN;
    this.dispatch("open");
  }

  private dispatch(type: "open" | "close"): void {
    const event = new Event(type);
    this.listeners.get(type)?.forEach((listener) => listener(event));
    if (type === "close") {
      this.onclose?.(event);
    }
  }
}

describe("useVoiceRecorder", () => {
  const originalMediaDevices = navigator.mediaDevices;
  const originalWebSocket = global.WebSocket;
  const originalAudioContext = global.AudioContext;
  const originalFetch = global.fetch;

  afterEach(() => {
    jest.useRealTimers();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: originalMediaDevices,
    });
    Object.defineProperty(global, "WebSocket", {
      configurable: true,
      value: originalWebSocket,
      writable: true,
    });
    Object.defineProperty(global, "AudioContext", {
      configurable: true,
      value: originalAudioContext,
      writable: true,
    });
    Object.defineProperty(global, "fetch", {
      configurable: true,
      value: originalFetch,
      writable: true,
    });
    TestWebSocket.instances = [];
  });

  function installStartupMocks() {
    const stopTrack = jest.fn();
    const stream = {
      getTracks: () => [{ stop: stopTrack }],
    } as unknown as MediaStream;
    const getUserMedia = jest.fn().mockResolvedValue(stream);
    const sourceNode = {
      connect: jest.fn(),
      disconnect: jest.fn(),
    };
    const scriptNode = {
      connect: jest.fn(),
      disconnect: jest.fn(),
      onaudioprocess: null,
    };
    const audioContext = {
      close: jest.fn(),
      createMediaStreamSource: jest.fn(() => sourceNode),
      createScriptProcessor: jest.fn(() => scriptNode),
      destination: {},
      sampleRate: 24000,
    };

    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    Object.defineProperty(global, "WebSocket", {
      configurable: true,
      value: TestWebSocket,
      writable: true,
    });
    Object.defineProperty(global, "AudioContext", {
      configurable: true,
      value: jest.fn(() => audioContext),
      writable: true,
    });
    Object.defineProperty(global, "fetch", {
      configurable: true,
      value: jest.fn().mockResolvedValue({
        json: jest.fn().mockResolvedValue({ token: "test-token" }),
        ok: true,
      }),
      writable: true,
    });

    return { audioContext, getUserMedia, sourceNode, stopTrack };
  }

  test("ignores a repeated start while microphone access is pending", async () => {
    const rejectors: Array<(reason?: unknown) => void> = [];
    const getUserMedia = jest.fn(
      () =>
        new Promise<MediaStream>((_resolve, reject) => {
          rejectors.push(reject);
        })
    );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });

    const { result } = renderHook(() => useVoiceRecorder());
    const starts: Promise<void>[] = [];

    act(() => {
      starts.push(result.current.startRecording());
      starts.push(result.current.startRecording());
    });

    try {
      expect(getUserMedia).toHaveBeenCalledTimes(1);
      expect(result.current.isStarting).toBe(true);
      await expect(starts[1]).resolves.toBeUndefined();
    } finally {
      await act(async () => {
        rejectors.forEach((reject) =>
          reject(new DOMException("test cleanup", "AbortError"))
        );
        await Promise.allSettled(starts);
      });
    }
    expect(result.current.isStarting).toBe(false);
  });

  test("clears the starting state when microphone access fails", async () => {
    const getUserMedia = jest
      .fn()
      .mockRejectedValue(
        new DOMException("permission denied", "NotAllowedError")
      );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });

    const { result } = renderHook(() => useVoiceRecorder());
    let start: Promise<void> | undefined;

    act(() => {
      start = result.current.startRecording();
    });
    expect(result.current.isStarting).toBe(true);

    await act(async () => {
      await expect(start).rejects.toThrow("permission denied");
    });

    expect(result.current.isStarting).toBe(false);
    expect(result.current.error).toBe("permission denied");
  });

  test("times out startup and releases a microphone stream that resolves late", async () => {
    jest.useFakeTimers();
    let resolveMicrophone: ((stream: MediaStream) => void) | undefined;
    const getUserMedia = jest.fn(
      () =>
        new Promise<MediaStream>((resolve) => {
          resolveMicrophone = resolve;
        })
    );
    const stopTrack = jest.fn();
    const stream = {
      getTracks: () => [{ stop: stopTrack }],
    } as unknown as MediaStream;
    const webSocket = jest.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    Object.defineProperty(global, "WebSocket", {
      configurable: true,
      value: webSocket,
      writable: true,
    });

    const { result } = renderHook(() => useVoiceRecorder());
    let start: Promise<void> | undefined;
    act(() => {
      start = result.current.startRecording();
    });
    const outcome = start!.then(
      () => null,
      (error: unknown) => error
    );

    await act(async () => {
      jest.advanceTimersByTime(10000);
      await Promise.resolve();
    });

    expect(await outcome).toEqual(new Error("Microphone startup timed out"));
    expect(result.current.isStarting).toBe(false);
    expect(result.current.error).toBe("Microphone startup timed out");

    await act(async () => {
      resolveMicrophone!(stream);
      await Promise.resolve();
    });
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(webSocket).not.toHaveBeenCalled();
  });

  test("releases microphone access that resolves after unmount", async () => {
    let resolveMicrophone: ((stream: MediaStream) => void) | undefined;
    const getUserMedia = jest.fn(
      () =>
        new Promise<MediaStream>((resolve) => {
          resolveMicrophone = resolve;
        })
    );
    const stopTrack = jest.fn();
    const stream = {
      getTracks: () => [{ stop: stopTrack }],
    } as unknown as MediaStream;
    const webSocket = jest.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    Object.defineProperty(global, "WebSocket", {
      configurable: true,
      value: webSocket,
      writable: true,
    });

    const { result, unmount } = renderHook(() => useVoiceRecorder());
    let start: Promise<void> | undefined;
    act(() => {
      start = result.current.startRecording();
    });
    unmount();

    await act(async () => {
      resolveMicrophone!(stream);
      await start;
    });

    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(webSocket).not.toHaveBeenCalled();
  });

  test("enters recording state after the WebSocket connects", async () => {
    const { audioContext, sourceNode, stopTrack } = installStartupMocks();
    const { result, unmount } = renderHook(() => useVoiceRecorder());
    let start: Promise<void> | undefined;

    act(() => {
      start = result.current.startRecording();
    });
    expect(result.current.isStarting).toBe(true);

    await waitFor(() => expect(TestWebSocket.instances).toHaveLength(1));
    act(() => TestWebSocket.instances[0]!.open());
    await act(async () => await start);

    expect(result.current.isStarting).toBe(false);
    expect(result.current.isRecording).toBe(true);

    unmount();
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(TestWebSocket.instances[0]!.close).toHaveBeenCalled();
    expect(sourceNode.disconnect).toHaveBeenCalled();
    expect(audioContext.close).toHaveBeenCalled();
  });

  test("settles startup when unmounted during WebSocket connection", async () => {
    const { stopTrack } = installStartupMocks();
    const { result, unmount } = renderHook(() => useVoiceRecorder());
    let start: Promise<void> | undefined;

    act(() => {
      start = result.current.startRecording();
    });
    await waitFor(() => expect(TestWebSocket.instances).toHaveLength(1));

    unmount();
    await act(async () => await start);

    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(TestWebSocket.instances[0]!.close).toHaveBeenCalled();
  });
});
