"use client";

import { useRef, useState } from "react";
import { BuildFile } from "@/app/craft/contexts/UploadFilesContext";
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

  const handlePromptClick = (promptText: string) => {
    inputBarRef.current?.setMessage(promptText);
  };

  return (
    <div className="h-full flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-(--app-page-main-content-width) flex flex-col">
        {/* Branding on the left, model picker on the right — mirrors AppPage. */}
        <div className="flex flex-row items-center justify-between gap-4 pb-6">
          {/* Typed Onyx wordmark + "Craft". The wordmark's letters sit in the
              upper-middle of its box (baseline ~79% down), so we baseline-align
              and nudge the wordmark down to share "Craft"'s baseline; the font
              size is matched to the wordmark's letter height. */}
          <div className="flex flex-row items-baseline gap-2">
            <Logo size={34} className="translate-y-[7px]" />
            <Text
              as="p"
              headingH1
              text05
              className="!text-[2.0625rem] !leading-none"
            >
              Craft
            </Text>
          </div>
          <ModelPickerButton
            selection={selectedModel}
            onChange={setSelectedModel}
          />
        </div>
        <CraftInputBar
          ref={inputBarRef}
          onSubmit={(message, files) => onSubmit(message, files, selectedModel)}
          isRunning={isRunning}
          placeholder="Analyze my data and create a dashboard..."
          sandboxInitializing={sandboxInitializing}
        />
        <ConnectDataBanner />
        <SuggestedPrompts onPromptClick={handlePromptClick} />
      </div>
    </div>
  );
}
