"use client";

import React, { createContext, useState, useContext, ReactNode, useCallback } from 'react';

interface KrokiFeatureContextType {
  isKrokiDisabled: boolean;
  disableKrokiFeature: () => void;
}

const KrokiFeatureContext = createContext<KrokiFeatureContextType | undefined>(undefined);

export const KrokiFeatureProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [isKrokiDisabled, setIsKrokiDisabled] = useState(false);

  const disableKrokiFeature = useCallback(() => {
    setIsKrokiDisabled(true);
  }, []);

  return (
    <KrokiFeatureContext.Provider value={{ isKrokiDisabled, disableKrokiFeature }}>
      {children}
    </KrokiFeatureContext.Provider>
  );
};

export const useKrokiFeature = (): KrokiFeatureContextType => {
  const context = useContext(KrokiFeatureContext);
  if (context === undefined) {
    throw new Error('useKrokiFeature must be used within a KrokiFeatureProvider');
  }
  return context;
};
