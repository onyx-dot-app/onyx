'use client';

import React, { useState, useEffect, createContext, useContext, ReactNode } from 'react';

const DEMO_MODE_KEY = 'dialin_demo_mode';

interface DemoModeState {
  isDemoMode: boolean;
  enableDemoMode: () => void;
  disableDemoMode: () => void;
  toggleDemoMode: () => void;
}

// Create a context for demo mode
const DemoModeContext = createContext<DemoModeState | null>(null);

// Provider component for demo mode
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

  const value = {
    isDemoMode,
    enableDemoMode,
    disableDemoMode,
    toggleDemoMode,
  };

  return (
    <DemoModeContext.Provider value={value}>
      {children}
    </DemoModeContext.Provider>
  );
}

// Hook to use demo mode
export function useDemoMode(): DemoModeState {
  const context = useContext(DemoModeContext);
  if (!context) {
    throw new Error('useDemoMode must be used within a DemoModeProvider');
  }
  return context;
}

// Helper function to check if demo mode is active (can be used outside of React components)
export function isDemoModeActive(): boolean {
  if (typeof window === 'undefined') return false;
  const storedDemoMode = localStorage.getItem(DEMO_MODE_KEY);
  return storedDemoMode ? JSON.parse(storedDemoMode) : false;
} 