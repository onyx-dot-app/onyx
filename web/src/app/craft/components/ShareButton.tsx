"use client";

import { useState, useRef, useEffect } from "react";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import Switch from "@/refresh-components/inputs/Switch";
import { SvgLink, SvgCopy, SvgCheck, SvgX } from "@opal/icons";
import { setSessionPublic } from "@/app/craft/services/apiServices";

interface ShareButtonProps {
  sessionId: string;
  webappUrl: string;
  isPublic: boolean;
  onPublicChange?: () => void;
}

export default function ShareButton({
  sessionId,
  webappUrl,
  isPublic: initialIsPublic,
  onPublicChange,
}: ShareButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isPublic, setIsPublic] = useState(initialIsPublic);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">(
    "idle"
  );
  const [isLoading, setIsLoading] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Build the full share URL from the webapp URL path
  const shareUrl = webappUrl.startsWith("http")
    ? webappUrl
    : `${window.location.origin}${webappUrl}`;

  // Close popover on outside click
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

  const handleToggle = async (newValue: boolean) => {
    setIsLoading(true);
    try {
      await setSessionPublic(sessionId, newValue);
      setIsPublic(newValue);
      onPublicChange?.();
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
      // Clipboard API unavailable (HTTP context or permission denied) — try execCommand
      try {
        const el = document.createElement("textarea");
        el.value = shareUrl;
        el.style.cssText = "position:fixed;opacity:0";
        document.body.appendChild(el);
        el.focus();
        el.select();
        success = document.execCommand("copy");
        document.body.removeChild(el);
      } catch {
        // Both methods failed
      }
    }
    setCopyState(success ? "copied" : "error");
    setTimeout(() => setCopyState("idle"), 2000);
  };

  return (
    <div className="relative flex-shrink-0" ref={popoverRef}>
      <Button
        action
        primary={isPublic}
        tertiary={!isPublic}
        leftIcon={SvgLink}
        onClick={() => setIsOpen((v) => !v)}
        aria-label="Share webapp"
      >
        {isPublic ? "Shared" : "Share"}
      </Button>

      {isOpen && (
        <div className="absolute top-full right-0 mt-2 z-50 w-80 rounded-12 border border-border-01 bg-background-neutral-00 shadow-lg p-4 flex flex-col gap-3">
          {/* Header */}
          <div className="flex items-center justify-between">
            <Text mainUiAction text04>
              Share app
            </Text>
            <Switch
              checked={isPublic}
              disabled={isLoading}
              onCheckedChange={handleToggle}
            />
          </div>

          {/* Description */}
          <Text secondaryBody text03>
            {isPublic
              ? "Anyone with the link can view this app."
              : "Enable sharing to let anyone view this app with a link."}
          </Text>

          {/* URL row - only shown when public */}
          {isPublic && (
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
