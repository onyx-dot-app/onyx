import { HTTPStreamingTTSPlayer } from "./streamingTTS";

describe("HTTP TTS cleanup", () => {
  afterEach(() => jest.restoreAllMocks());

  it("does not report a delayed error from an audio element after stopping", async () => {
    const audio = document.createElement("audio");
    jest.spyOn(window, "Audio").mockImplementation(() => audio);
    jest.spyOn(audio, "play").mockResolvedValue();
    jest.spyOn(audio, "pause").mockImplementation(() => {});
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: jest.fn(() => "blob:test"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: jest.fn(),
    });
    jest.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(1),
    } as Response);
    const onError = jest.fn();
    const player = new HTTPStreamingTTSPlayer({ onError });
    await player.speak("Hello");
    player.stop();
    audio.dispatchEvent(new Event("error"));
    audio.dispatchEvent(new Event("ended"));
    expect(onError).not.toHaveBeenCalled();
  });
});
