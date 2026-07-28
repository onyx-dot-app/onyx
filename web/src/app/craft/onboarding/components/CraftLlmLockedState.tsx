"use client";

import { Button } from "@opal/components";
import { SvgLock } from "@opal/icons";
import { ContentAction } from "@opal/layouts";

/**
 * Inline blocked state shown on the craft welcome page when a non-admin has
 * no supported provider available — only admins can configure one.
 */
export default function CraftLlmLockedState() {
  return (
    <div
      className="flex flex-col w-full p-1 rounded-16 border border-border-01 bg-background-tint-00"
      aria-label="craft-llm-locked"
    >
      <ContentAction
        icon={SvgLock}
        title="An LLM provider is required"
        description="Onyx Craft needs a model provider, and only admins can set one up. Ask your admin to connect Anthropic, OpenAI, or OpenRouter."
        sizePreset="main-ui"
        variant="section"
        padding="lg"
        rightChildren={
          <Button prominence="tertiary" href="/app">
            Back to Chat
          </Button>
        }
      />
    </div>
  );
}
