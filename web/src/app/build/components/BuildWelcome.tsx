"use client";

import { LlmManager } from "@/lib/hooks";
import { BuildFile } from "@/app/build/contexts/UploadFilesContext";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import InputBar from "@/app/build/components/InputBar";

interface BuildWelcomeProps {
  onSubmit: (message: string, files: BuildFile[]) => void;
  isRunning: boolean;
  llmManager: LlmManager;
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
  llmManager,
  sandboxInitializing = false,
}: BuildWelcomeProps) {
  return (
    <div className="h-full flex flex-col items-center justify-center px-4">
      <div className="flex flex-col items-center gap-4 mb-8">
        <Logo folded size={48} />
        <Text headingH2 text05>
          What would you like to build?
        </Text>
        <Text secondaryBody text03 className="text-center max-w-md">
          Describe your task and I'll execute it in an isolated environment. You
          can build web apps, run scripts, process data, and more.
        </Text>
      </div>
      <div className="w-full max-w-2xl">
        <InputBar
          onSubmit={onSubmit}
          isRunning={isRunning}
          placeholder="Create a React app that shows a dashboard..."
          llmManager={llmManager}
          sandboxInitializing={sandboxInitializing}
        />
      </div>
    </div>
  );
}
