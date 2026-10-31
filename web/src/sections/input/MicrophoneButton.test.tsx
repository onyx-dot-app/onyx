import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useTranslations } from "next-intl";

import MicrophoneButton from "@/sections/input/MicrophoneButton";

jest.mock("next-intl", () => ({
  useTranslations: jest.fn(),
}));

jest.mock("@/providers/VoiceModeProvider", () => ({
  useVoiceMode: () => ({
    isTTSPlaying: false,
    isTTSLoading: false,
    isAwaitingAutoPlaybackStart: false,
    manualStopCount: 0,
  }),
}));

jest.mock("@opal/layouts", () => ({
  toast: { error: jest.fn() },
}));

describe("MicrophoneButton", () => {
  const originalMediaDevices = navigator.mediaDevices;

  beforeEach(() => {
    jest.mocked(useTranslations).mockReturnValue(((key: string) => {
      const messages: Record<string, string> = {
        "microphoneButton.startRecording.ariaLabel": "Start recording",
        "microphoneButton.startingRecording.ariaLabel": "Starting recording",
        "microphoneButton.stopRecording.ariaLabel": "Stop recording",
        "microphoneButton.accessError.toast": "Could not access microphone",
      };
      return messages[key] ?? key;
    }) as ReturnType<typeof useTranslations>);
  });

  afterEach(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: originalMediaDevices,
    });
    jest.restoreAllMocks();
  });

  test("shows immediate progress feedback while microphone access is pending", async () => {
    let rejectMicrophone: ((reason?: unknown) => void) | undefined;
    const getUserMedia = jest.fn(
      () =>
        new Promise<MediaStream>((_resolve, reject) => {
          rejectMicrophone = reject;
        })
    );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    jest.spyOn(console, "error").mockImplementation(() => {});

    render(<MicrophoneButton onTranscription={jest.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    const startingButton = await screen.findByRole("button", {
      name: "Starting recording",
    });
    expect(startingButton).toBeDisabled();
    expect(startingButton).toHaveAttribute("aria-busy", "true");
    expect(getUserMedia).toHaveBeenCalledTimes(1);

    await act(async () => {
      rejectMicrophone!(new DOMException("test cleanup", "AbortError"));
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start recording" })
      ).toBeEnabled()
    );
  });
});
