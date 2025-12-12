"use client";

import React, { useState, useMemo } from "react";
import { AvatarListItem } from "@/lib/types";
import { useQueryableAvatars } from "@/lib/avatar";
import { useAvatarContextOptional } from "@/app/chat/avatars/AvatarContext";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import SvgUsers from "@/icons/users";
import SvgX from "@/icons/x";
import { Search, User, Lock, Unlock, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";

interface AvatarSectionProps {
  folded?: boolean;
}

export default function AvatarSection({ folded }: AvatarSectionProps) {
  const avatarContext = useAvatarContextOptional();
  const { avatars, loading, error } = useQueryableAvatars();
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  // If context is not available (provider not mounted), don't render
  if (!avatarContext) {
    return null;
  }

  const { isAvatarMode, selectedAvatar, enableAvatarMode, disableAvatarMode } =
    avatarContext;

  const filteredAvatars = useMemo(() => {
    if (!searchTerm) return avatars.slice(0, 5); // Show first 5 by default
    return avatars.filter(
      (avatar) =>
        avatar.user_email.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (avatar.name?.toLowerCase().includes(searchTerm.toLowerCase()) ?? false)
    );
  }, [avatars, searchTerm]);

  const handleAvatarClick = (avatar: AvatarListItem) => {
    if (selectedAvatar?.id === avatar.id) {
      disableAvatarMode();
    } else {
      enableAvatarMode(avatar);
    }
    setSearchExpanded(false);
    setSearchTerm("");
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
        <IconButton
          icon={searchExpanded ? SvgX : Search}
          internal
          tooltip={searchExpanded ? "Close Search" : "Search Avatars"}
          onClick={() => {
            setSearchExpanded(!searchExpanded);
            if (!searchExpanded) setSearchTerm("");
          }}
        />
      }
    >
      {/* Active avatar indicator */}
      {isAvatarMode && selectedAvatar && (
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
            filteredAvatars.map((avatar) => (
              <AvatarRow
                key={avatar.id}
                avatar={avatar}
                isSelected={selectedAvatar?.id === avatar.id}
                onClick={() => handleAvatarClick(avatar)}
              />
            ))
          )}

          {/* Show more if there are more avatars */}
          {!searchTerm && avatars.length > 5 && (
            <SidebarTab
              leftIcon={SvgUsers}
              lowlight
              onClick={() => setSearchExpanded(true)}
            >
              {avatars.length - 5} more avatars
            </SidebarTab>
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
      {avatar.allow_accessible_mode ? (
        <Unlock className="h-3 w-3 text-success flex-shrink-0" />
      ) : (
        <Lock className="h-3 w-3 text-text-02 flex-shrink-0" />
      )}
    </div>
  );
}
