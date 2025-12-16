"use client";

import React, { useState } from "react";
import { AvatarListItem, AvatarQueryMode } from "@/lib/types";
import { useQueryableAvatars } from "@/lib/avatar";
import { User, Search, Lock, Unlock } from "lucide-react";

interface AvatarSelectorProps {
  onSelect: (avatar: AvatarListItem) => void;
  selectedAvatarId?: number | null;
}

export function AvatarSelector({
  onSelect,
  selectedAvatarId,
}: AvatarSelectorProps) {
  const { avatars, loading, error } = useQueryableAvatars();
  const [searchTerm, setSearchTerm] = useState("");

  const filteredAvatars = avatars.filter(
    (avatar) =>
      avatar.user_email.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (avatar.name?.toLowerCase().includes(searchTerm.toLowerCase()) ?? false)
  );

  if (loading) {
    return (
      <div className="p-4 text-center text-text-subtle">Loading avatars...</div>
    );
  }

  if (error) {
    return <div className="p-4 text-center text-error">{error}</div>;
  }

  if (avatars.length === 0) {
    return (
      <div className="p-4 text-center text-text-subtle">
        No avatars available to query
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Search input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-subtle" />
        <input
          type="text"
          placeholder="Search avatars..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full pl-9 pr-3 py-2 border border-border rounded-lg bg-background text-sm focus:outline-none focus:ring-2 focus:ring-accent"
        />
      </div>

      {/* Avatar list */}
      <div className="max-h-64 overflow-y-auto border border-border rounded-lg">
        {filteredAvatars.length === 0 ? (
          <div className="p-4 text-center text-text-subtle">
            No avatars match your search
          </div>
        ) : (
          filteredAvatars.map((avatar) => (
            <AvatarListRow
              key={avatar.id}
              avatar={avatar}
              isSelected={avatar.id === selectedAvatarId}
              onClick={() => onSelect(avatar)}
            />
          ))
        )}
      </div>
    </div>
  );
}

interface AvatarListRowProps {
  avatar: AvatarListItem;
  isSelected: boolean;
  onClick: () => void;
}

function AvatarListRow({ avatar, isSelected, onClick }: AvatarListRowProps) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 p-3 text-left hover:bg-hover transition-colors border-b border-border last:border-b-0 ${
        isSelected ? "bg-accent/10" : ""
      }`}
    >
      {/* Avatar icon */}
      <div className="flex-shrink-0 w-10 h-10 rounded-full bg-accent/20 flex items-center justify-center">
        <User className="h-5 w-5 text-accent" />
      </div>

      {/* Avatar info */}
      <div className="flex-1 min-w-0">
        <div className="font-medium text-text truncate">
          {avatar.name || avatar.user_email}
        </div>
        {avatar.name && (
          <div className="text-sm text-text-subtle truncate">
            {avatar.user_email}
          </div>
        )}
        {avatar.description && (
          <div className="text-xs text-text-subtle truncate mt-0.5">
            {avatar.description}
          </div>
        )}
      </div>

      {/* Query mode indicator */}
      <div className="flex-shrink-0 flex items-center gap-1">
        {avatar.allow_accessible_mode ? (
          <span
            className="flex items-center gap-1 text-xs text-success"
            title="Supports accessible documents mode"
          >
            <Unlock className="h-3 w-3" />
          </span>
        ) : (
          <span
            className="flex items-center gap-1 text-xs text-text-subtle"
            title="Only owned documents mode"
          >
            <Lock className="h-3 w-3" />
          </span>
        )}
      </div>
    </button>
  );
}

export default AvatarSelector;
