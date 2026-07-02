"use client";

import { useRef, useState } from "react";
import { BuildFile } from "@/app/craft/contexts/UploadFilesContext";
import { useVideoBackgroundToggleClick } from "@/app/craft/components/video-background/useVideoBackgroundToggleClick";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import CraftInputBar, {
  CraftInputBarHandle,
} from "@/app/craft/components/CraftInputBar";
import ModelPickerButton from "@/app/craft/components/ModelPickerButton";
import SuggestedPrompts from "@/app/craft/components/SuggestedPrompts";
import ConnectDataBanner from "@/app/craft/components/ConnectDataBanner";
import { BuildLlmSelection } from "@/app/craft/onboarding/constants";

interface BuildWelcomeProps {
  onSubmit: (
    message: string,
    files: BuildFile[],
    model?: BuildLlmSelection | null
  ) => void;
  isRunning: boolean;
  /** When true, shows spinner on send button with "Initializing sandbox..." tooltip */
  sandboxInitializing?: boolean;
}

/**
 * BuildWelcome - Welcome screen shown when no session exists
 *
 * Displays a centered welcome message and input bar to start a new build.
 */
export default function BuildWelcome({
  onSubmit,
  isRunning,
  sandboxInitializing = false,
}: BuildWelcomeProps) {
  const inputBarRef = useRef<CraftInputBarHandle>(null);
  const [selectedModel, setSelectedModel] = useState<BuildLlmSelection | null>(
    null
  );
  const handleWordmarkClick = useVideoBackgroundToggleClick();

  const handlePromptClick = (promptText: string) => {
    inputBarRef.current?.setMessage(promptText);
  };

  return (
    // Mirror the main app's empty-state grid (`1fr auto 1fr`) so the input bar
    // centers vertically at the same position: wordmark pinned above it, the
    // supporting content below.
    <div
      className="h-full grid px-4"
      style={{ gridTemplateRows: "1fr auto 1fr" }}
    >
      <div className="row-start-1 min-h-0 w-full flex flex-col items-center justify-end">
        <div className="w-full max-w-(--app-page-main-content-width)">
          <div className="flex flex-row items-center justify-between gap-4 pb-6">
            {/* The wordmark's baseline sits ~79% down its box, so nudge it
                down (~0.21 × size) to share craft's baseline. */}
            <div
              className="flex flex-row items-baseline gap-2 select-none"
              onClick={handleWordmarkClick}
            >
              <Logo onyxBranded size={28} className="translate-y-[6px]" />
              <Text
                text05
                style={{
                  fontFamily: "var(--font-kh-teka)",
                  fontWeight: 400,
                  // Sized so the x-height matches the custom "onyx" logotype
                  // (its x-height ≈ 0.595em vs KH Teka's 0.504em at size 28).
                  fontSize: "34px",
                  lineHeight: "1",
                  letterSpacing: "-0.02em",
                }}
              >
                craft
              </Text>
            </div>
            <ModelPickerButton
              selection={selectedModel}
              onChange={setSelectedModel}
            />
          </div>
        </div>
      </div>

      <div className="row-start-2 w-full flex flex-col items-center">
        <div className="w-full max-w-(--app-page-main-content-width)">
          <CraftInputBar
            ref={inputBarRef}
            onSubmit={(message, files) =>
              onSubmit(message, files, selectedModel)
            }
            isRunning={isRunning}
            placeholder="Analyze my data and create a dashboard..."
            sandboxInitializing={sandboxInitializing}
          />
        </div>
      </div>

      <div className="row-start-3 min-h-0 w-full flex flex-col items-center">
        <div className="w-full max-w-(--app-page-main-content-width)">
          <ConnectDataBanner />
          <SuggestedPrompts onPromptClick={handlePromptClick} />
        </div>
      </div>
    </div>
  );
}
