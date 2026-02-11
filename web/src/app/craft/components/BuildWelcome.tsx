"use client";

import { useRef } from "react";
import { BuildFile } from "@/app/craft/contexts/UploadFilesContext";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import InputBar, { InputBarHandle } from "@/app/craft/components/InputBar";
import SuggestedPrompts from "@/app/craft/components/SuggestedPrompts";
import ConnectDataBanner from "@/app/craft/components/ConnectDataBanner";
import { getBuildUserPersona } from "@/app/craft/onboarding/constants";
import { workAreaToPersona } from "@/app/craft/constants/exampleBuildPrompts";

interface BuildWelcomeProps {
  onSubmit: (
    message: string,
    files: BuildFile[],
    demoDataEnabled: boolean
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
  const inputBarRef = useRef<InputBarHandle>(null);
  const userPersona = getBuildUserPersona();
  const persona = workAreaToPersona(userPersona?.workArea);

  const handlePromptClick = (promptText: string) => {
    inputBarRef.current?.setMessage(promptText);
  };

  return (
    <div className="h-full flex flex-col items-center justify-center px-4">
      <div className="flex flex-col items-center gap-4 mb-6">
        <Logo folded size={48} />
        <Text headingH2 text05>
          What shall we craft today?
        </Text>
      </div>
      <div className="w-full max-w-2xl">
        <InputBar
          ref={inputBarRef}
          onSubmit={onSubmit}
          isRunning={isRunning}
          placeholder="Analyze my data and create a dashboard..."
          sandboxInitializing={sandboxInitializing}
          isWelcomePage
        />
        <ConnectDataBanner />
        <SuggestedPrompts persona={persona} onPromptClick={handlePromptClick} />
      </div>
    </div>
  );
}
