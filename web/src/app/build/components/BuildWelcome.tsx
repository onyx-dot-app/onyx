"use client";

import { useRef } from "react";
import { BuildFile } from "@/app/build/contexts/UploadFilesContext";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import InputBar, { InputBarHandle } from "@/app/build/components/InputBar";
import SuggestedPrompts from "@/app/build/components/SuggestedPrompts";

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

  const handlePromptClick = (promptText: string) => {
    inputBarRef.current?.setMessage(promptText);
  };

  return (
    <div className="h-full flex flex-col items-center justify-center px-4">
      <div className="flex flex-col items-center gap-4 mb-6">
        <Logo folded size={48} />
        <Text headingH2 text05>
          What would you like to build?
        </Text>
      </div>
      <div className="w-full max-w-2xl">
        <InputBar
          ref={inputBarRef}
          onSubmit={onSubmit}
          isRunning={isRunning}
          placeholder="Create a React app that shows a dashboard..."
          sandboxInitializing={sandboxInitializing}
        />
        <SuggestedPrompts onPromptClick={handlePromptClick} />
      </div>
    </div>
  );
}
