"use client";

import React from "react";
import { useAvatarContextOptional } from "@/app/chat/avatars/AvatarContext";
import { AvatarQueryMode } from "@/lib/types";
import { User, X, Lock, Unlock, Radio } from "lucide-react";
import { cn } from "@/lib/utils";

export function AvatarModeIndicator() {
  const avatarContext = useAvatarContextOptional();

  if (!avatarContext || !avatarContext.isAvatarMode) {
    return null;
  }

  const {
    isBroadcastMode,
    selectedAvatar,
    selectedAvatars,
    queryMode,
    setQueryMode,
    disableAvatarMode,
  } = avatarContext;

  // Don't show if no avatar selected (single mode)
  if (!isBroadcastMode && !selectedAvatar) {
    return null;
  }

  // Check if all selected avatars allow accessible mode
  const allAllowAccessible = isBroadcastMode
    ? selectedAvatars.every((a) => a.allow_accessible_mode)
    : selectedAvatar?.allow_accessible_mode;

  return (
    <div className="w-full max-w-[50rem] my-2">
      <div className="bg-background border border-accent/20 rounded-lg p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-accent/20 flex items-center justify-center">
              {isBroadcastMode ? (
                <Radio className="h-4 w-4 text-accent" />
              ) : (
                <User className="h-4 w-4 text-accent" />
              )}
            </div>
            <div>
              <div className="text-sm font-medium text-accent">
                {isBroadcastMode ? "Broadcast" : "Avatar Query"}
              </div>
              <div className="text-xs text-text-subtle">
                {isBroadcastMode
                  ? "Asking everyone at the company"
                  : `Asking: ${
                      selectedAvatar?.name || selectedAvatar?.user_email
                    }`}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Query Mode Toggle */}
            <div className="flex bg-background rounded border border-border">
              <button
                onClick={() => setQueryMode(AvatarQueryMode.OWNED_DOCUMENTS)}
                className={cn(
                  "flex items-center gap-1 px-2 py-1 text-xs rounded-l transition-colors",
                  queryMode === AvatarQueryMode.OWNED_DOCUMENTS
                    ? "bg-accent text-white"
                    : "text-text-subtle hover:text-text"
                )}
              >
                <Lock className="h-3 w-3" />
                Owned
              </button>
              {allAllowAccessible && (
                <button
                  onClick={() =>
                    setQueryMode(AvatarQueryMode.ACCESSIBLE_DOCUMENTS)
                  }
                  className={cn(
                    "flex items-center gap-1 px-2 py-1 text-xs rounded-r transition-colors",
                    queryMode === AvatarQueryMode.ACCESSIBLE_DOCUMENTS
                      ? "bg-accent text-white"
                      : "text-text-subtle hover:text-text"
                  )}
                >
                  <Unlock className="h-3 w-3" />
                  All
                </button>
              )}
            </div>

            {/* Close button */}
            <button
              onClick={disableAvatarMode}
              className="p-1 hover:bg-background rounded transition-colors"
              title="Exit Avatar Mode"
            >
              <X className="h-4 w-4 text-text-subtle hover:text-text" />
            </button>
          </div>
        </div>

        {queryMode === AvatarQueryMode.ACCESSIBLE_DOCUMENTS && (
          <div className="mt-2 text-xs text-warning bg-warning/10 px-2 py-1 rounded">
            Note: Accessible mode queries require permission from the avatar
            owner{isBroadcastMode && "s"}
          </div>
        )}
      </div>
    </div>
  );
}
