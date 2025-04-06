'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

const DEMO_MODE_KEY = 'dialin_demo_mode';

interface DemoModeContextType {
  isDemoMode: boolean;
  enableDemoMode: () => void;
  disableDemoMode: () => void;
  toggleDemoMode: () => void;
}

const DemoModeContext = createContext<DemoModeContextType | null>(null);

export function DemoModeProvider({ children }: { children: ReactNode }) {
  const [isDemoMode, setIsDemoMode] = useState<boolean>(false);

  // Initialize demo mode from localStorage on mount
  useEffect(() => {
    const storedDemoMode = localStorage.getItem(DEMO_MODE_KEY);
    if (storedDemoMode !== null) {
      setIsDemoMode(JSON.parse(storedDemoMode));
    }
  }, []);

  // Update localStorage when demo mode changes
  useEffect(() => {
    localStorage.setItem(DEMO_MODE_KEY, JSON.stringify(isDemoMode));
  }, [isDemoMode]);

  const enableDemoMode = () => {
    setIsDemoMode(true);
  };

  const disableDemoMode = () => {
    setIsDemoMode(false);
  };

  const toggleDemoMode = () => {
    setIsDemoMode((prev) => !prev);
  };

  return (
    <DemoModeContext.Provider
      value={{
        isDemoMode,
        enableDemoMode,
        disableDemoMode,
        toggleDemoMode,
      }}
    >
      {children}
    </DemoModeContext.Provider>
  );
}

export function useDemoModeContext() {
  const context = useContext(DemoModeContext);
  if (!context) {
    throw new Error('useDemoModeContext must be used within a DemoModeProvider');
  }
  return context;
} 