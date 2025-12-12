"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import { AvatarListItem } from "@/lib/types";
import {
  useQueryableAvatars,
  useIncomingPermissionRequests,
} from "@/lib/avatar";
import { useAvatarContextOptional } from "@/app/chat/avatars/AvatarContext";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import SvgUsers from "@/icons/users";
import SvgX from "@/icons/x";
import { Search, User, Loader2, Radio, Bell, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";

interface AvatarSectionProps {
  folded?: boolean;
}

const MAX_AVATARS_TO_SHOW = 6;

export default function AvatarSection({ folded }: AvatarSectionProps) {
  const avatarContext = useAvatarContextOptional();
  const { avatars, loading, error } = useQueryableAvatars();
  const { requests: incomingRequests } = useIncomingPermissionRequests();
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  // If context is not available (provider not mounted), don't render
  if (!avatarContext) {
    return null;
  }

  const pendingRequestCount = incomingRequests.length;

  const {
    isAvatarMode,
    isBroadcastMode,
    selectedAvatar,
    selectedAvatars,
    enableAvatarMode,
    disableAvatarMode,
    enableBroadcastMode,
  } = avatarContext;

  const filteredAvatars = useMemo(() => {
    if (!searchTerm) return avatars.slice(0, MAX_AVATARS_TO_SHOW); // Show first MAX_AVATARS_TO_SHOW by default
    return avatars.filter(
      (avatar) =>
        avatar.user_email.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (avatar.name?.toLowerCase().includes(searchTerm.toLowerCase()) ?? false)
    );
  }, [avatars, searchTerm]);

  const handleAvatarClick = (avatar: AvatarListItem) => {
    // Toggle selection for single avatar mode
    if (selectedAvatar?.id === avatar.id) {
      disableAvatarMode();
    } else {
      enableAvatarMode(avatar);
    }
    setSearchExpanded(false);
    setSearchTerm("");
  };

  const handleEnableBroadcastMode = () => {
    // Enable broadcast mode with all avatars automatically selected
    enableBroadcastMode(avatars);
  };

  if (folded) {
    return (
      <SidebarTab
        leftIcon={SvgUsers}
        folded
        active={isAvatarMode}
        onClick={() => {
          if (isAvatarMode) {
            disableAvatarMode();
          }
        }}
      >
        Avatars
      </SidebarTab>
    );
  }

  return (
    <SidebarSection
      title="Avatars"
      action={
        <div className="flex items-center gap-1">
          {/* Pending requests indicator */}
          <Link href="/avatars?tab=requests&subtab=incoming">
            <div className="relative">
              <IconButton
                icon={Bell}
                internal
                tooltip={
                  pendingRequestCount > 0
                    ? `${pendingRequestCount} pending request${
                        pendingRequestCount !== 1 ? "s" : ""
                      }`
                    : "No pending requests"
                }
              />
              {pendingRequestCount > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 bg-error text-white text-[10px] font-bold rounded-full flex items-center justify-center">
                  {pendingRequestCount > 9 ? "9+" : pendingRequestCount}
                </span>
              )}
            </div>
          </Link>
          <Link href="/avatars?tab=settings">
            <IconButton icon={Settings} internal tooltip="Avatar Settings" />
          </Link>
          <IconButton
            icon={searchExpanded ? SvgX : Search}
            internal
            tooltip={searchExpanded ? "Close Search" : "Search Avatars"}
            onClick={() => {
              setSearchExpanded(!searchExpanded);
              if (!searchExpanded) setSearchTerm("");
            }}
          />
        </div>
      }
    >
      {/* Active avatar indicator - Single mode */}
      {isAvatarMode && !isBroadcastMode && selectedAvatar && (
        <div className="mx-2 mb-2 p-2 bg-accent/10 border border-accent/30 rounded-08">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-6 h-6 rounded-full bg-accent/20 flex items-center justify-center flex-shrink-0">
                <User className="h-3 w-3 text-accent" />
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium text-accent truncate">
                  Querying: {selectedAvatar.name || selectedAvatar.user_email}
                </div>
              </div>
            </div>
            <IconButton
              icon={SvgX}
              internal
              tooltip="Exit Avatar Mode"
              onClick={disableAvatarMode}
            />
          </div>
        </div>
      )}

      {/* Active avatar indicator - Broadcast mode */}
      {isAvatarMode && isBroadcastMode && (
        <div className="mx-2 mb-2 p-2 bg-accent/10 border border-accent/30 rounded-08">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <Radio className="h-3 w-3 text-accent" />
              <span className="text-xs font-medium text-accent">
                Broadcast Mode
              </span>
            </div>
            <IconButton
              icon={SvgX}
              internal
              tooltip="Exit Avatar Mode"
              onClick={disableAvatarMode}
            />
          </div>
          <div className="text-[10px] text-accent/80">
            {selectedAvatars.length === 0
              ? "Select avatars to query"
              : `${selectedAvatars.length} avatar${
                  selectedAvatars.length !== 1 ? "s" : ""
                } selected`}
          </div>
          {selectedAvatars.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {selectedAvatars.slice(0, 3).map((avatar) => (
                <span
                  key={avatar.id}
                  className="text-[10px] bg-accent/20 px-1.5 py-0.5 rounded text-accent"
                >
                  {avatar.name || avatar.user_email.split("@")[0]}
                </span>
              ))}
              {selectedAvatars.length > 3 && (
                <span className="text-[10px] text-accent/60">
                  +{selectedAvatars.length - 3} more
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Search input */}
      {searchExpanded && (
        <div className="mx-2 mb-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-text-subtle" />
            <input
              type="text"
              placeholder="Search avatars..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-7 pr-2 py-1.5 text-xs border border-border rounded bg-background focus:outline-none focus:ring-1 focus:ring-accent"
              autoFocus
            />
          </div>
        </div>
      )}

      {/* Broadcast (Everyone) option - always show at top when not in broadcast mode */}
      {!loading && avatars.length > 0 && !isBroadcastMode && (
        <div
          onClick={handleEnableBroadcastMode}
          className="flex items-center gap-2 px-3 py-2 mx-1 mb-1 rounded-08 cursor-pointer hover:bg-accent/10 text-text-03 hover:text-accent border-b border-border transition-colors"
        >
          <div className="w-6 h-6 rounded-full bg-accent/10 flex items-center justify-center flex-shrink-0">
            <Radio className="h-3 w-3 text-accent" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium">Broadcast</div>
            <div className="text-[10px] text-text-02">
              Ask everyone at the company at once.
            </div>
          </div>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-text-subtle" />
        </div>
      )}

      {/* Error state */}
      {error && <div className="mx-2 py-2 text-xs text-error">{error}</div>}

      {/* Avatar list */}
      {!loading && !error && (
        <>
          {filteredAvatars.length === 0 ? (
            <div className="mx-2 py-2 text-xs text-text-subtle">
              {searchTerm
                ? "No avatars match your search"
                : "No avatars available"}
            </div>
          ) : (
            // Don't show individual avatars in broadcast mode (everyone is selected)
            !isBroadcastMode &&
            filteredAvatars.map((avatar) => (
              <AvatarRow
                key={avatar.id}
                avatar={avatar}
                isSelected={selectedAvatar?.id === avatar.id}
                onClick={() => handleAvatarClick(avatar)}
              />
            ))
          )}

          {/* Show more if there are more avatars - only in single mode */}
          {!isBroadcastMode &&
            !searchTerm &&
            avatars.length > MAX_AVATARS_TO_SHOW && (
              <div
                className="text-xs text-text-03 hover:text-text-04 cursor-pointer ml-4 mt-3"
                onClick={() => setSearchExpanded(true)}
              >
                {avatars.length - MAX_AVATARS_TO_SHOW} more avatars
              </div>
            )}
        </>
      )}
    </SidebarSection>
  );
}

interface AvatarRowProps {
  avatar: AvatarListItem;
  isSelected: boolean;
  onClick: () => void;
}

function AvatarRow({ avatar, isSelected, onClick }: AvatarRowProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 px-3 py-1.5 mx-1 rounded-08 cursor-pointer transition-colors",
        isSelected
          ? "bg-accent/10 text-accent"
          : "hover:bg-background-tint-03 text-text-03 hover:text-text-04"
      )}
    >
      <div
        className={cn(
          "w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0",
          isSelected ? "bg-accent/20" : "bg-background-tint-03"
        )}
      >
        <User
          className={cn("h-3 w-3", isSelected ? "text-accent" : "text-text-03")}
        />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium truncate">
          {avatar.name || avatar.user_email}
        </div>
        {avatar.name && (
          <div className="text-[10px] text-text-02 truncate">
            {avatar.user_email}
          </div>
        )}
      </div>
    </div>
  );
}
