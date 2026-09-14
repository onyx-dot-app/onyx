"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { SvgLock } from "@opal/icons";
import { ContentAction } from "@opal/layouts";

/**
 * Inline blocked state shown on the craft welcome page when a non-admin has
 * no supported provider available — only admins can configure one.
 */
export default function CraftLlmLockedState() {
  const t = useTranslations("craft.onboarding.llmLocked");
  return (
    <div
      className="flex flex-col w-full p-1 rounded-16 border border-border-01 bg-background-tint-00"
      aria-label="craft-llm-locked"
    >
      <ContentAction
        icon={SvgLock}
        title={t("title")}
        description={t("description")}
        sizePreset="main-ui"
        variant="section"
        padding={2}
        rightChildren={
          <Button prominence="tertiary" href="/app">
            {t("backToChatButton")}
          </Button>
        }
      />
    </div>
  );
}
