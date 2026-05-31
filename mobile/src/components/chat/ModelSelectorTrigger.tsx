import { useEffect, useRef } from "react";
import { Pressable } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  BottomSheetScrollView,
  BottomSheetTextInput,
  BottomSheetView,
} from "@gorhom/bottom-sheet";

import { BottomSheet, Text, type BottomSheetRef } from "@/components/opal";
import { ChevronDownIcon } from "@/components/ui/icons";
import { useToken } from "@/theme/ThemeProvider";
import { getModelIcon, resolveDefaultModel } from "@/lib/languageModels";
import { useLlmProviders } from "@/query/llmProviders";
import { useChatSessionStore } from "@/state/chatSessionStore";
import type { LLMOption } from "@/lib/types";
import { ModelListContent } from "./ModelListContent";

// Single-model selector in the input bar's right cluster (left of Send). Shows the
// active model (provider icon + name + chevron); tapping opens a bottom sheet
// (@gorhom/bottom-sheet) with the model list. A sheet — not an anchored popover —
// because rn-primitives popover positioning is unreliable on RN; a modal sheet
// always renders correctly regardless of where the trigger sits. Selecting a model
// stores it on the session (sent as llm_override) and dismisses the sheet.
//
// Renders nothing when the workspace has no configured providers.

interface ModelSelectorTriggerProps {
  sessionId: string;
}

export function ModelSelectorTrigger({ sessionId }: ModelSelectorTriggerProps) {
  const sheetRef = useRef<BottomSheetRef>(null);
  const insets = useSafeAreaInsets();

  const { data, isLoading } = useLlmProviders();
  const providers = data?.providers ?? [];
  const defaultModel = resolveDefaultModel(providers, data?.default_text ?? null);

  const selectedModel = useChatSessionStore(
    (s) => s.sessions.get(sessionId)?.selectedModel,
  );
  const updateSelectedModel = useChatSessionStore((s) => s.updateSelectedModel);

  const labelColor = useToken("text-04");
  const chevronColor = useToken("text-03");
  // True once the user explicitly picks a model — after that we stop auto-syncing.
  const manualRef = useRef(false);

  // Keep the session's selected model in sync with the resolved default until the
  // user picks one, so every send carries an explicit llm_override that tracks fresh
  // provider data (value-compared to avoid an update loop, since defaultModel is a new
  // object each render).
  useEffect(() => {
    if (manualRef.current || !defaultModel) return;
    const same =
      selectedModel != null &&
      selectedModel.name === defaultModel.name &&
      selectedModel.provider === defaultModel.provider &&
      selectedModel.modelName === defaultModel.modelName;
    if (!same) updateSelectedModel(sessionId, defaultModel);
  }, [defaultModel, selectedModel, sessionId, updateSelectedModel]);

  // Nothing to choose from yet.
  if (!isLoading && providers.length === 0) return null;

  const active = selectedModel ?? defaultModel;
  const Icon = getModelIcon(active?.provider ?? "", undefined, active?.modelName);

  function handleSelect(o: LLMOption) {
    manualRef.current = true;
    updateSelectedModel(sessionId, {
      name: o.name,
      provider: o.provider,
      modelName: o.modelName,
      displayName: o.displayName,
    });
    sheetRef.current?.dismiss();
  }

  return (
    <>
      <Pressable
        onPress={() => sheetRef.current?.present()}
        accessibilityRole="button"
        accessibilityLabel="Select model"
        className="h-8 flex-row items-center gap-1 rounded-[12px] px-2 active:bg-background-tint-02"
      >
        <Icon size={16} color={labelColor} />
        <Text
          font="main-ui-body"
          color="text-04"
          numberOfLines={1}
          style={{ maxWidth: 140 }}
        >
          {active?.displayName ?? "Model"}
        </Text>
        <ChevronDownIcon size={16} color={chevronColor} />
      </Pressable>

      <BottomSheet ref={sheetRef} enableDynamicSizing>
        <BottomSheetView
          style={{
            paddingHorizontal: 12,
            paddingBottom: Math.max(insets.bottom, 12),
          }}
        >
          <Text
            font="main-ui-action"
            color="text-05"
            style={{ paddingHorizontal: 4, paddingBottom: 8, paddingTop: 4 }}
          >
            Select a model
          </Text>
          <ModelListContent
            providers={providers}
            isLoading={isLoading}
            selected={active}
            onSelect={handleSelect}
            ScrollComponent={BottomSheetScrollView}
            InputComponent={BottomSheetTextInput}
          />
        </BottomSheetView>
      </BottomSheet>
    </>
  );
}
