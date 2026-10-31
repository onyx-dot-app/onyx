import { jest } from "@jest/globals";

import type { ComposerTools } from "@/state/ComposerToolsProvider";

export function makeComposerTools(
  overrides: Partial<ComposerTools> = {},
): ComposerTools {
  return {
    showDeepResearch: false,
    deepResearchEnabled: false,
    toggleDeepResearch: jest.fn(),
    actionTools: [],
    unavailableToolIds: [],
    forcedToolId: null,
    toggleForcedTool: jest.fn(),
    disabledToolIds: [],
    toggleToolEnabled: jest.fn(),
    modelOptions: [],
    effectiveModel: null,
    selectModel: jest.fn(),
    sourceToolId: null,
    sourceOptions: [],
    enabledSourceCount: 0,
    isSourceEnabled: () => false,
    toggleSource: jest.fn(),
    enableAllSources: jest.fn(),
    disableAllSources: jest.fn(),
    notePendingSend: jest.fn(),
    resolveToolOptions: () => ({
      deepResearch: false,
      allowedToolIds: null,
      forcedToolId: null,
      internalSearchFilters: null,
      llmOverride: null,
    }),
    ...overrides,
  };
}
