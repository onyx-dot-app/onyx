import { createElement, useEffect, useRef, useState } from "react";
import { Dimensions, Keyboard, Platform, Pressable } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Popover, Text, type PopoverTriggerRef } from "@/components/opal";
import { ChevronDownIcon } from "@/components/ui/icons";
import { useToken } from "@/theme/ThemeProvider";
import { getModelIcon, resolveDefaultModel } from "@/lib/languageModels";
import { useLlmProviders } from "@/query/llmProviders";
import { useChatSessionStore } from "@/state/chatSessionStore";
import type { LLMOption } from "@/lib/types";
import { ModelListContent } from "./ModelListContent";

// Single-model selector in the input bar's right cluster (left of Send). Shows the
// active model (provider icon + name + chevron); tapping opens an anchored popover
// (@rn-primitives/popover) with the model list. The popover is anchored to the
// trigger: rn-primitives measures the trigger on press (Trigger.measure → pageX/
// pageY/width/height) and positions Content against it — opening upward (side="top")
// and right-aligned (align="end") since the trigger lives in the bottom-right of the
// composer, with avoidCollisions + safe-area insets keeping it on screen. Selecting a
// model stores it on the session (sent as llm_override) and dismisses the popover.
//
// Keyboard handling: the card grows upward from a trigger near the very bottom, so
// when the in-popover search box is focused the soft keyboard would otherwise cover
// the lower rows. We add the live keyboard height to Content `insets.bottom` while
// the popover is open — rn-primitives' top clamp (min(max(insetTop, natural),
// screenH - insetBottom - cardH)) then lifts the whole card above the keyboard.
//
// Renders nothing when the workspace has no configured providers.

interface ModelSelectorTriggerProps {
  sessionId: string;
}

export function ModelSelectorTrigger({ sessionId }: ModelSelectorTriggerProps) {
  const triggerRef = useRef<PopoverTriggerRef>(null);
  const insets = useSafeAreaInsets();
  // Track open state so the keyboard listener is only active while the popover is up
  // (otherwise typing in the main composer would needlessly re-render this control).
  const [open, setOpen] = useState(false);
  const [keyboardHeight, setKeyboardHeight] = useState(0);

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

  // While open, subscribe to the keyboard height so the popover can sit above it (see
  // header). Pure subscription effect — the close-time reset lives in onOpenChange.
  useEffect(() => {
    if (!open) return;
    const showEvent = Platform.OS === "ios" ? "keyboardWillShow" : "keyboardDidShow";
    const hideEvent = Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide";
    const show = Keyboard.addListener(showEvent, (e) =>
      setKeyboardHeight(e.endCoordinates?.height ?? 0),
    );
    const hide = Keyboard.addListener(hideEvent, () => setKeyboardHeight(0));
    return () => {
      show.remove();
      hide.remove();
    };
  }, [open]);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) setKeyboardHeight(0);
  }

  // Nothing to choose from yet.
  if (!isLoading && providers.length === 0) return null;

  const active = selectedModel ?? defaultModel;

  const screenWidth = Dimensions.get("window").width;
  // Cap the popover width so it never overflows a narrow screen — rn-primitives'
  // avoidCollisions repositions the card but does not shrink its measured width.
  const contentWidth = Math.min(320, screenWidth - 24);
  // Label width tracks screen width (web shrink-wraps with no cap); long names still
  // truncate with an ellipsis, but common ones like "Claude 3.5 Sonnet" fit in full.
  const labelMaxWidth = Math.min(180, Math.round(screenWidth * 0.4));

  function handleSelect(o: LLMOption) {
    manualRef.current = true;
    updateSelectedModel(sessionId, {
      name: o.name,
      provider: o.provider,
      modelName: o.modelName,
      displayName: o.displayName,
    });
    triggerRef.current?.close();
  }

  return (
    <Popover onOpenChange={handleOpenChange}>
      <Popover.Trigger ref={triggerRef} asChild>
        {/* h-9 (36px) matches the web `lg` control + the sibling Send button; the
            label is main-ui-body/14px (web SelectButton `lg`). maxFontSizeMultiplier
            caps OS text-scaling so the label stays close to the design size without
            fully disabling Dynamic Type, and hitSlop lifts the tap target to the
            44pt iOS minimum. */}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Select model"
          hitSlop={8}
          className="h-9 flex-row items-center gap-1 rounded-[12px] px-2 active:bg-background-tint-02"
        >
          {/* getModelIcon returns a stable, module-level logo component; render it
              via createElement so the linter doesn't read it as a component declared
              during render (react-hooks/static-components). */}
          {createElement(
            getModelIcon(active?.provider ?? "", undefined, active?.modelName),
            { size: 16, color: labelColor },
          )}
          <Text
            font="main-ui-body"
            color="text-04"
            numberOfLines={1}
            maxFontSizeMultiplier={1.2}
            style={{ maxWidth: labelMaxWidth }}
          >
            {active?.displayName ?? "Model"}
          </Text>
          <ChevronDownIcon size={16} color={chevronColor} />
        </Pressable>
      </Popover.Trigger>

      <Popover.Content
        side="top"
        align="end"
        sideOffset={8}
        insets={{
          top: insets.top + 8,
          bottom: insets.bottom + 8 + keyboardHeight,
          left: 12,
          right: 12,
        }}
        style={{ width: contentWidth }}
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
        />
      </Popover.Content>
    </Popover>
  );
}
