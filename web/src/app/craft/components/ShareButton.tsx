"use client";

import { useState, useEffect } from "react";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgLink, SvgCopy, SvgCheck, SvgX } from "@opal/icons";
import { setSessionSharing } from "@/app/craft/services/apiServices";
import type { SharingScope } from "@/app/craft/types/streamingTypes";
import { cn } from "@/lib/utils";
import Popover from "@/refresh-components/Popover";
import Truncated from "@/refresh-components/texts/Truncated";
import { Section } from "@/layouts/general-layouts";
import { ContentAction } from "@opal/layouts";

interface ShareButtonProps {
  sessionId: string;
  webappUrl: string;
  sharingScope: SharingScope;
  onScopeChange?: () => void;
}

const SCOPE_OPTIONS: {
  value: SharingScope;
  label: string;
  description: string;
}[] = [
  {
    value: "private",
    label: "Private",
    description: "Only you can view this app.",
  },
  {
    value: "public_org",
    label: "Organization",
    description: "Anyone logged into your Onyx can view this app.",
  },
];

export default function ShareButton({
  sessionId,
  webappUrl,
  sharingScope: initialScope,
  onScopeChange,
}: ShareButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [sharingScope, setSharingScope] = useState<SharingScope>(initialScope);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">(
    "idle"
  );
  const [isLoading, setIsLoading] = useState(false);

  const isShared = sharingScope !== "private";

  const shareUrl =
    typeof window !== "undefined"
      ? webappUrl.startsWith("http")
        ? webappUrl
        : `${window.location.origin}${webappUrl}`
      : webappUrl;

  const handleSelect = async (scope: SharingScope) => {
    if (scope === sharingScope || isLoading) return;
    setIsLoading(true);
    try {
      await setSessionSharing(sessionId, scope);
      setSharingScope(scope);
      onScopeChange?.();
    } catch (err) {
      console.error("Failed to update sharing:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = async () => {
    let success = false;
    try {
      await navigator.clipboard.writeText(shareUrl);
      success = true;
    } catch {
      try {
        const el = document.createElement("textarea");
        el.value = shareUrl;
        el.style.cssText = "position:fixed;opacity:0";
        document.body.appendChild(el);
        el.focus();
        el.select();
        success = document.execCommand("copy");
        document.body.removeChild(el);
      } catch {}
    }
    setCopyState(success ? "copied" : "error");
    setTimeout(() => setCopyState("idle"), 2000);
  };

  return (
    <Section width="fit" height="fit">
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <Popover.Trigger asChild>
          <Button
            action
            primary={isShared}
            tertiary={!isShared}
            leftIcon={SvgLink}
            aria-label="Share webapp"
          >
            {isShared ? "Shared" : "Share"}
          </Button>
        </Popover.Trigger>
        <Popover.Content side="bottom" align="end" width="lg" sideOffset={4}>
          <Section
            alignItems="stretch"
            gap={0.25}
            padding={0.25}
            width="full"
            height="fit"
          >
            {/* Scope options */}
            <Section alignItems="stretch" gap={0.25} width="full">
              {SCOPE_OPTIONS.map((opt) => (
                <div
                  key={opt.value}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleSelect(opt.value)}
                  onKeyDown={(e) =>
                    e.key === "Enter" && handleSelect(opt.value)
                  }
                  aria-disabled={isLoading}
                  className={cn(
                    "cursor-pointer rounded-08 transition-colors",
                    sharingScope === opt.value
                      ? "bg-background-tint-03"
                      : "hover:bg-background-tint-02"
                  )}
                >
                  <ContentAction
                    title={opt.label}
                    description={opt.description}
                    sizePreset="main-ui"
                    variant="section"
                    paddingVariant="sm"
                  />
                </div>
              ))}
            </Section>

            {/* Copy link — shown when not private */}
            {isShared && (
              <div className="rounded-08 bg-background-tint-02">
                <Section
                  flexDirection="row"
                  alignItems="center"
                  gap={0.25}
                  padding={0.25}
                  width="full"
                  height="fit"
                >
                  <div className="min-w-0 flex-1 overflow-hidden">
                    <Truncated secondaryBody text03>
                      {shareUrl}
                    </Truncated>
                  </div>
                  <Button
                    action
                    tertiary
                    size="md"
                    leftIcon={
                      copyState === "copied"
                        ? SvgCheck
                        : copyState === "error"
                          ? SvgX
                          : SvgCopy
                    }
                    onClick={handleCopy}
                    aria-label="Copy link"
                  />
                </Section>
              </div>
            )}
          </Section>
        </Popover.Content>
      </Popover>
    </Section>
  );
}
