"use client";

import { useEffect, useState } from "react";
import { useHotkey } from "@opal/hooks";
import useBrowserInfo from "@/hooks/useBrowserInfo";
import {
  CHAT_SHORTCUTS,
  JUMP_TO_CHAT_SHORTCUTS,
} from "@/lib/shortcuts/constants";
import { useChatShortcutActions } from "@/lib/shortcuts/hooks";
import { isModalOpen } from "@/lib/shortcuts/utils";

export function useChatJumpHintModifier(): "ctrl+alt" | "mod+alt" | null {
  const { isMac } = useBrowserInfo();
  const [modifier, setModifier] = useState<"ctrl+alt" | "mod+alt" | null>(null);

  useEffect(() => {
    const hide = () => setModifier(null);
    const update = (event: KeyboardEvent) => {
      if (
        !event.altKey ||
        event.getModifierState("AltGraph") ||
        isModalOpen()
      ) {
        hide();
      } else if (event.ctrlKey && !event.metaKey) {
        setModifier("ctrl+alt");
      } else if (isMac && event.metaKey && !event.ctrlKey) {
        setModifier("mod+alt");
      } else {
        hide();
      }
    };
    window.addEventListener("keydown", update, true);
    window.addEventListener("keyup", update, true);
    window.addEventListener("blur", hide);
    document.addEventListener("visibilitychange", hide);
    return () => {
      window.removeEventListener("keydown", update, true);
      window.removeEventListener("keyup", update, true);
      window.removeEventListener("blur", hide);
      document.removeEventListener("visibilitychange", hide);
    };
  }, [isMac]);

  return modifier;
}

interface ShortcutBindingProps {
  hotkey: string;
  onPress: () => void;
  /** Whether the shortcut also runs from a text field. @default true */
  whileTyping?: boolean;
}

// Most chat shortcuts have a modifier that types no text, so they also work
// from the chat input. No chat shortcut runs while a modal is open; the modal
// keeps its own keys.
function ShortcutBinding({
  hotkey,
  onPress,
  whileTyping = true,
}: ShortcutBindingProps) {
  useHotkey(
    hotkey,
    () => {
      if (!isModalOpen()) onPress();
    },
    { whileTyping }
  );
  return null;
}

/** Binds the chat shortcuts in `CHAT_SHORTCUTS` while the app sidebar is mounted. */
export default function ChatShortcuts() {
  const actions = useChatShortcutActions();
  const { isMac } = useBrowserInfo();

  return (
    <>
      <ShortcutBinding
        hotkey={CHAT_SHORTCUTS.newChat}
        onPress={actions.newChat}
      />
      <ShortcutBinding
        hotkey={CHAT_SHORTCUTS.openModelPicker}
        onPress={actions.toggleModelPicker}
      />
      {/* In a text field, Alt+Up/Down moves the caret by paragraph on macOS. */}
      <ShortcutBinding
        hotkey={CHAT_SHORTCUTS.previousChat}
        onPress={actions.previousChat}
        whileTyping={false}
      />
      <ShortcutBinding
        hotkey={CHAT_SHORTCUTS.nextChat}
        onPress={actions.nextChat}
        whileTyping={false}
      />
      {JUMP_TO_CHAT_SHORTCUTS.map((hotkey, index) => (
        <ShortcutBinding
          key={hotkey}
          hotkey={hotkey}
          onPress={() => actions.jumpToChat(index)}
        />
      ))}
      {isMac &&
        JUMP_TO_CHAT_SHORTCUTS.map((hotkey, index) => (
          <ShortcutBinding
            key={`ctrl:${hotkey}`}
            hotkey={`ctrl+alt+${index + 1}`}
            onPress={() => actions.jumpToChat(index)}
          />
        ))}
    </>
  );
}
