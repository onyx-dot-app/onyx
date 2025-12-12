"use client";

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  ReactNode,
} from "react";
import {
  AvatarListItem,
  AvatarQueryMode,
  AvatarQueryResponse,
} from "@/lib/types";

interface AvatarContextState {
  // Avatar mode state
  isAvatarMode: boolean;
  isBroadcastMode: boolean;
  selectedAvatar: AvatarListItem | null; // Single avatar for non-broadcast
  selectedAvatars: AvatarListItem[]; // Multiple avatars for broadcast
  queryMode: AvatarQueryMode;

  // Query state (legacy - kept for backward compatibility)
  isQuerying: boolean;
  lastResult: AvatarQueryResponse | null;
  queryError: string | null;

  // Actions
  enableAvatarMode: (avatar: AvatarListItem) => void;
  disableAvatarMode: () => void;
  setQueryMode: (mode: AvatarQueryMode) => void;
  clearResult: () => void;

  // Broadcast mode actions - automatically includes all avatars
  enableBroadcastMode: (allAvatars: AvatarListItem[]) => void;
  toggleAvatarSelection: (avatar: AvatarListItem) => void;
  selectAllAvatars: (avatars: AvatarListItem[]) => void;
  clearAvatarSelection: () => void;
}

const AvatarContext = createContext<AvatarContextState | null>(null);

export function AvatarProvider({ children }: { children: ReactNode }) {
  const [isAvatarMode, setIsAvatarMode] = useState(false);
  const [isBroadcastMode, setIsBroadcastMode] = useState(false);
  const [selectedAvatar, setSelectedAvatar] = useState<AvatarListItem | null>(
    null
  );
  const [selectedAvatars, setSelectedAvatars] = useState<AvatarListItem[]>([]);
  const [queryMode, setQueryMode] = useState<AvatarQueryMode>(
    AvatarQueryMode.OWNED_DOCUMENTS
  );
  const [isQuerying, setIsQuerying] = useState(false);
  const [lastResult, setLastResult] = useState<AvatarQueryResponse | null>(
    null
  );
  const [queryError, setQueryError] = useState<string | null>(null);

  // Single avatar mode
  const enableAvatarMode = useCallback((avatar: AvatarListItem) => {
    setIsAvatarMode(true);
    setIsBroadcastMode(false);
    setSelectedAvatar(avatar);
    setSelectedAvatars([]);
    setQueryMode(avatar.default_query_mode);
    setLastResult(null);
    setQueryError(null);
  }, []);

  const disableAvatarMode = useCallback(() => {
    setIsAvatarMode(false);
    setIsBroadcastMode(false);
    setSelectedAvatar(null);
    setSelectedAvatars([]);
    setLastResult(null);
    setQueryError(null);
  }, []);

  // Broadcast mode actions - automatically includes all avatars
  const enableBroadcastMode = useCallback((allAvatars: AvatarListItem[]) => {
    setIsAvatarMode(true);
    setIsBroadcastMode(true);
    setSelectedAvatar(null);
    // Automatically select all avatars for broadcast
    setSelectedAvatars(allAvatars);
    setLastResult(null);
    setQueryError(null);
  }, []);

  const toggleAvatarSelection = useCallback((avatar: AvatarListItem) => {
    setSelectedAvatars((prev) => {
      const isSelected = prev.some((a) => a.id === avatar.id);
      if (isSelected) {
        return prev.filter((a) => a.id !== avatar.id);
      } else {
        return [...prev, avatar];
      }
    });
  }, []);

  const selectAllAvatars = useCallback((avatars: AvatarListItem[]) => {
    setSelectedAvatars(avatars);
  }, []);

  const clearAvatarSelection = useCallback(() => {
    setSelectedAvatars([]);
  }, []);

  const clearResult = useCallback(() => {
    setLastResult(null);
    setQueryError(null);
  }, []);

  return (
    <AvatarContext.Provider
      value={{
        isAvatarMode,
        isBroadcastMode,
        selectedAvatar,
        selectedAvatars,
        queryMode,
        isQuerying,
        lastResult,
        queryError,
        enableAvatarMode,
        disableAvatarMode,
        setQueryMode,
        clearResult,
        enableBroadcastMode,
        toggleAvatarSelection,
        selectAllAvatars,
        clearAvatarSelection,
      }}
    >
      {children}
    </AvatarContext.Provider>
  );
}

export function useAvatarContext() {
  const context = useContext(AvatarContext);
  if (!context) {
    throw new Error("useAvatarContext must be used within an AvatarProvider");
  }
  return context;
}

export function useAvatarContextOptional() {
  return useContext(AvatarContext);
}
