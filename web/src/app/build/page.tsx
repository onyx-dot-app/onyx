"use client";

import { useState } from "react";
import { useBuild } from "@/hooks/useBuild";
import { getWebappUrl } from "@/lib/build/client";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Message from "@/refresh-components/messages/Message";
import Card from "@/refresh-components/cards/Card";
import TerminalOutput from "./components/TerminalOutput";
import ArtifactList from "./components/ArtifactList";
import FileBrowser from "./components/FileBrowser";
import {
  SvgPlayCircle,
  SvgTrash,
  SvgExternalLink,
  SvgLoader,
  SvgGlobe,
} from "@opal/icons";

export default function BuildPage() {
  const [taskInput, setTaskInput] = useState("");
  const { status, sessionId, packets, artifacts, error, run, cleanup } =
    useBuild();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskInput.trim()) return;
    await run(taskInput);
  };

  const webappArtifact = artifacts.find((a) => a.artifact_type === "webapp");
  const isRunning = status === "running" || status === "creating";

  return (
    <div className="flex flex-col gap-6 p-6 max-w-5xl mx-auto">
      <div className="flex flex-col gap-2">
        <Text headingH1 text05>
          Build
        </Text>
        <Text mainContentMuted text03>
          Execute tasks and generate artifacts in an isolated environment
        </Text>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <InputTextArea
          value={taskInput}
          onChange={(e) => setTaskInput(e.target.value)}
          placeholder="Describe your task..."
          rows={4}
          disabled={isRunning}
        />
        <div className="flex flex-row gap-2">
          <Button
            action
            primary
            type="submit"
            disabled={isRunning || !taskInput.trim()}
            leftIcon={isRunning ? SvgLoader : SvgPlayCircle}
          >
            {status === "creating"
              ? "Creating..."
              : status === "running"
                ? "Running..."
                : "Execute"}
          </Button>
          {sessionId && (
            <Button
              danger
              secondary
              type="button"
              onClick={cleanup}
              leftIcon={SvgTrash}
            >
              Cleanup
            </Button>
          )}
        </div>
      </form>

      {error && (
        <Message
          error
          text={error}
          description="An error occurred during task execution"
          onClose={() => {}}
          close={false}
        />
      )}

      {(packets.length > 0 || status === "running") && (
        <TerminalOutput packets={packets} isStreaming={status === "running"} />
      )}

      {sessionId && <FileBrowser sessionId={sessionId} />}

      {artifacts.length > 0 && sessionId && (
        <ArtifactList artifacts={artifacts} sessionId={sessionId} />
      )}

      {webappArtifact && (
        <Card>
          <div className="flex flex-row items-center justify-between w-full">
            <div className="flex flex-row items-center gap-1.5">
              <SvgGlobe className="size-4 stroke-text-03" />
              <Text mainUiAction text03>
                Web App Preview
              </Text>
            </div>
            <a href={getWebappUrl()} target="_blank" rel="noopener noreferrer">
              <Button action tertiary rightIcon={SvgExternalLink}>
                Open in new tab
              </Button>
            </a>
          </div>
          <iframe
            src={getWebappUrl()}
            className="w-full h-96 rounded-08 border border-border-01"
            sandbox="allow-scripts allow-same-origin allow-forms"
            title="Web App Preview"
          />
        </Card>
      )}
    </div>
  );
}
