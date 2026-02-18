"use client";

import { useState, useRef, useEffect } from "react";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgLink, SvgCopy, SvgCheck, SvgX } from "@opal/icons";
import { setSessionSharing } from "@/app/craft/services/apiServices";
import type { SharingScope } from "@/app/craft/types/streamingTypes";
import { cn } from "@/lib/utils";

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
    label: "Org",
    description: "Anyone logged into your Onyx can view this app.",
  },
  {
    value: "public_global",
    label: "Public",
    description: "Anyone with the link can view this app.",
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
  const popoverRef = useRef<HTMLDivElement>(null);

  const isShared = sharingScope !== "private";

  const shareUrl = webappUrl.startsWith("http")
    ? webappUrl
    : `${window.location.origin}${webappUrl}`;

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isOpen]);

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
    <div className="relative flex-shrink-0" ref={popoverRef}>
      <Button
        action
        primary={isShared}
        tertiary={!isShared}
        leftIcon={SvgLink}
        onClick={() => setIsOpen((v) => !v)}
        aria-label="Share webapp"
      >
        {isShared ? "Shared" : "Share"}
      </Button>

      {isOpen && (
        <div className="absolute top-full right-0 mt-2 z-50 w-80 rounded-12 border border-border-01 bg-background-neutral-00 shadow-lg p-4 flex flex-col gap-3">
          <Text mainUiAction text04>
            Share app
          </Text>

          {/* Scope selector */}
          <div className="flex flex-col gap-1">
            {SCOPE_OPTIONS.map((opt) => (
              <div
                key={opt.value}
                role="button"
                tabIndex={0}
                onClick={() => handleSelect(opt.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSelect(opt.value)}
                aria-disabled={isLoading}
                className={cn(
                  "flex flex-col items-start gap-0.5 px-3 py-2 rounded-08 text-left transition-colors cursor-pointer",
                  sharingScope === opt.value
                    ? "bg-background-tint-03"
                    : "hover:bg-background-tint-02"
                )}
              >
                <Text mainUiAction text04>
                  {opt.label}
                </Text>
                <Text secondaryBody text03>
                  {opt.description}
                </Text>
              </div>
            ))}
          </div>

          {/* Copy link row — shown when not private */}
          {isShared && (
            <div className="flex items-center gap-2 p-2 rounded-08 bg-background-tint-02">
              <Text secondaryBody text03 className="flex-1 truncate">
                {shareUrl}
              </Text>
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
            </div>
          )}
        </div>
      )}
    </div>
  );
}
