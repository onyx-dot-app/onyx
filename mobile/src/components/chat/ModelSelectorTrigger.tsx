import { createElement, useEffect, useRef, useState } from "react";
import { Dimensions, Keyboard, Platform, Pressable } from "react-native";

import { Popover, Text, type PopoverTriggerRef } from "@/components/opal";
import { SvgChevronDown } from "@/components/icons/SvgChevronDown";
import { useToken } from "@/theme/ThemeProvider";
import { getModelIcon } from "@/lib/languageModels";
import { useActiveModel } from "@/chat/useActiveModel";
import { useChatSessionStore } from "@/state/chatSessionStore";
import type { LLMOption } from "@/lib/types";
import { ModelListContent } from "./ModelListContent";
import { usePopoverPlacement } from "./usePopoverPlacement";

// Single-model selector (mirror of web ModelListContent). The card grows upward
// from a trigger near the bottom, so when the search box is focused we fold the
// live keyboard height into Content insets.bottom — rn-primitives' top clamp then
// lifts the whole card above the keyboard.
interface ModelSelectorTriggerProps {
  sessionId: string;
}

export function ModelSelectorTrigger({ sessionId }: ModelSelectorTriggerProps) {
  const triggerRef = useRef<PopoverTriggerRef>(null);
  // Track open state so the keyboard listener is only active while the popover is up.
  const [open, setOpen] = useState(false);
  const [keyboardHeight, setKeyboardHeight] = useState(0);
  const { insets, contentWidth } = usePopoverPlacement({
    maxWidth: 320,
    widthMargin: 24,
    extraBottom: keyboardHeight,
  });

  const { providers, isLoading, defaultModel, selectedModel, activeModel } =
    useActiveModel(sessionId);
  const updateSelectedModel = useChatSessionStore((s) => s.updateSelectedModel);

  const labelColor = useToken("text-04");
  // Once the user explicitly picks a model we stop auto-syncing.
  const manualRef = useRef(false);

  // Sync the session's selected model to the resolved default until the user picks
  // one. Value-compared to avoid an update loop (defaultModel is a new object each render).
  useEffect(() => {
    if (manualRef.current || !defaultModel) return;
    const same =
      selectedModel != null &&
      selectedModel.name === defaultModel.name &&
      selectedModel.provider === defaultModel.provider &&
      selectedModel.modelName === defaultModel.modelName;
    if (!same) updateSelectedModel(sessionId, defaultModel);
  }, [defaultModel, selectedModel, sessionId, updateSelectedModel]);

  // Subscribe to keyboard height while open so the popover sits above it (see header).
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

  if (!isLoading && providers.length === 0) return null;

  const screenWidth = Dimensions.get("window").width;
  // Cap label width but track screen size so common names fit; long ones ellipsize.
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
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Select model"
          hitSlop={8}
          className="h-9 flex-row items-center gap-1 rounded-[12px] px-2 active:bg-background-tint-02"
        >
          {/* createElement so the linter doesn't read getModelIcon's return as a
              component declared during render (react-hooks/static-components). */}
          {createElement(
            getModelIcon(
              activeModel?.provider ?? "",
              undefined,
              activeModel?.modelName,
            ),
            { size: 16, color: labelColor },
          )}
          <Text
            font="main-ui-body"
            color="text-04"
            numberOfLines={1}
            maxFontSizeMultiplier={1.2}
            style={{ maxWidth: labelMaxWidth }}
          >
            {activeModel?.displayName ?? "Model"}
          </Text>
          <SvgChevronDown size={16} color="text-03" />
        </Pressable>
      </Popover.Trigger>

      <Popover.Content
        side="top"
        align="end"
        sideOffset={8}
        insets={insets}
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
          selected={activeModel}
          onSelect={handleSelect}
        />
      </Popover.Content>
    </Popover>
  );
}
