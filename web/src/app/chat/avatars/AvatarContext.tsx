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
import { querySingleAvatar } from "@/lib/avatar/avatarApi";

interface AvatarContextState {
  // Avatar mode state
  isAvatarMode: boolean;
  selectedAvatar: AvatarListItem | null;
  queryMode: AvatarQueryMode;

  // Query state
  isQuerying: boolean;
  lastResult: AvatarQueryResponse | null;
  queryError: string | null;

  // Actions
  enableAvatarMode: (avatar: AvatarListItem) => void;
  disableAvatarMode: () => void;
  setQueryMode: (mode: AvatarQueryMode) => void;
  queryAvatar: (queryText: string) => Promise<AvatarQueryResponse>;
  clearResult: () => void;
}

const AvatarContext = createContext<AvatarContextState | null>(null);

export function AvatarProvider({ children }: { children: ReactNode }) {
  const [isAvatarMode, setIsAvatarMode] = useState(false);
  const [selectedAvatar, setSelectedAvatar] = useState<AvatarListItem | null>(
    null
  );
  const [queryMode, setQueryMode] = useState<AvatarQueryMode>(
    AvatarQueryMode.OWNED_DOCUMENTS
  );
  const [isQuerying, setIsQuerying] = useState(false);
  const [lastResult, setLastResult] = useState<AvatarQueryResponse | null>(
    null
  );
  const [queryError, setQueryError] = useState<string | null>(null);

  const enableAvatarMode = useCallback((avatar: AvatarListItem) => {
    setIsAvatarMode(true);
    setSelectedAvatar(avatar);
    setQueryMode(avatar.default_query_mode);
    setLastResult(null);
    setQueryError(null);
  }, []);

  const disableAvatarMode = useCallback(() => {
    setIsAvatarMode(false);
    setSelectedAvatar(null);
    setLastResult(null);
    setQueryError(null);
  }, []);

  const queryAvatar = useCallback(
    async (queryText: string): Promise<AvatarQueryResponse> => {
      if (!selectedAvatar) {
        throw new Error("No avatar selected");
      }

      setIsQuerying(true);
      setQueryError(null);

      try {
        const result = await querySingleAvatar(
          selectedAvatar.id,
          queryText,
          queryMode
        );
        setLastResult(result);
        return result;
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Query failed";
        setQueryError(errorMessage);
        throw err;
      } finally {
        setIsQuerying(false);
      }
    },
    [selectedAvatar, queryMode]
  );

  const clearResult = useCallback(() => {
    setLastResult(null);
    setQueryError(null);
  }, []);

  return (
    <AvatarContext.Provider
      value={{
        isAvatarMode,
        selectedAvatar,
        queryMode,
        isQuerying,
        lastResult,
        queryError,
        enableAvatarMode,
        disableAvatarMode,
        setQueryMode,
        queryAvatar,
        clearResult,
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
