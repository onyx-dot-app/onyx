"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Popover, Text } from "@opal/components";
import { SvgLink, SvgCopy, SvgCheck, SvgX } from "@opal/icons";
import { setSessionSharing } from "@/app/craft/services/apiServices";
import type { SharingScope } from "@/app/craft/types/streamingTypes";
import { cn } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";
import { ContentAction } from "@opal/layouts";

interface ShareButtonProps {
  sessionId: string;
  webappUrl: string;
  sharingScope: SharingScope;
  onScopeChange?: () => void;
}

export default function ShareButton({
  sessionId,
  webappUrl,
  sharingScope: initialScope,
  onScopeChange,
}: ShareButtonProps) {
  const t = useTranslations("craft.share");
  const scopeOptions = useMemo<
    { value: SharingScope; label: string; description: string }[]
  >(
    () => [
      {
        value: "private",
        label: t("private.label"),
        description: t("private.description"),
      },
      {
        value: "public_org",
        label: t("organization.label"),
        description: t("organization.description"),
      },
    ],
    [t]
  );
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
            variant="action"
            prominence={isShared ? "primary" : "tertiary"}
            icon={SvgLink}
            aria-label={t("trigger.ariaLabel")}
          >
            {isShared ? t("shared.label") : t("share.label")}
          </Button>
        </Popover.Trigger>
        <Popover.Content side="bottom" align="end" width="lg" sideOffset={4}>
          <Section
            alignItems="stretch"
            gap={1}
            padding={1}
            width="full"
            height="fit"
          >
            {/* Scope options */}
            <Section alignItems="stretch" gap={1} width="full">
              {scopeOptions.map((opt) => (
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
                    padding={1}
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
                  gap={1}
                  padding={1}
                  width="full"
                  height="fit"
                >
                  <div className="min-w-0 flex-1 overflow-hidden">
                    <Text font="secondary-body" color="text-03" maxLines={1}>
                      {shareUrl}
                    </Text>
                  </div>
                  <Button
                    variant="action"
                    prominence="tertiary"
                    size="md"
                    icon={
                      copyState === "copied"
                        ? SvgCheck
                        : copyState === "error"
                          ? SvgX
                          : SvgCopy
                    }
                    onClick={handleCopy}
                    aria-label={t("copyLink.ariaLabel")}
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
