"use client";

import React, { createContext, useContext, useState, useCallback } from "react";

interface AnimatingMessage {
  content: string;
  startRect: DOMRect;
  timestamp: number;
}

interface MessageAnimationContextType {
  animatingMessage: AnimatingMessage | null;
  startMessageAnimation: (content: string, startRect: DOMRect) => void;
  clearAnimation: () => void;
}

const MessageAnimationContext = createContext<
  MessageAnimationContextType | undefined
>(undefined);

export function MessageAnimationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [animatingMessage, setAnimatingMessage] =
    useState<AnimatingMessage | null>(null);

  const startMessageAnimation = useCallback(
    (content: string, startRect: DOMRect) => {
      setAnimatingMessage({
        content,
        startRect,
        timestamp: Date.now(),
      });
    },
    []
  );

  const clearAnimation = useCallback(() => {
    setAnimatingMessage(null);
  }, []);

  return (
    <MessageAnimationContext.Provider
      value={{
        animatingMessage,
        startMessageAnimation,
        clearAnimation,
      }}
    >
      {children}
    </MessageAnimationContext.Provider>
  );
}

export function useMessageAnimation() {
  const context = useContext(MessageAnimationContext);
  if (!context) {
    throw new Error(
      "useMessageAnimation must be used within MessageAnimationProvider"
    );
  }
  return context;
}
