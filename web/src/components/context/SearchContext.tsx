"use client";

import React, { createContext, useContext } from "react";
import { CCPairBasicInfo, DocumentSet, Tag } from "@/lib/types";
import { Persona } from "@/app/admin/assistants/interfaces";
import { ChatSession } from "@/app/chat/interfaces";

interface SearchContextProps {
  querySessions: ChatSession[];
  ccPairs: CCPairBasicInfo[];
  documentSets: DocumentSet[];
  assistants: Persona[];
  tags: Tag[];
  agenticSearchEnabled: boolean;
  disabledAgentic: boolean;
  initiallyToggled: boolean;
  shouldShowWelcomeModal: boolean;
  shouldDisplayNoSources: boolean;
}

const SearchContext = createContext<SearchContextProps | undefined>(undefined);

export const SearchProvider: React.FC<{
  value: SearchContextProps;
  children: React.ReactNode;
}> = ({ value, children }) => {
  return (
    <SearchContext.Provider value={value}>{children}</SearchContext.Provider>
  );
};

export const useSearchContext = (): SearchContextProps => {
  const context = useContext(SearchContext);
  if (!context) {
    throw new Error("useSearchContext must be used within a SearchProvider");
  }
  return context;
};
