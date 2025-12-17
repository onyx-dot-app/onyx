import { SlashCommand } from "@/app/chat/components/slash-commands/types";
import { InputPrompt } from "@/app/chat/interfaces";

/**
 * Keyboard handler for slash command menu navigation
 *
 * Handles arrow keys for navigation, Enter/Tab for selection, and Escape to dismiss
 * @returns true if event was handled and should not propagate
 */
export function handleSlashCommandKeyDown(
  e: React.KeyboardEvent,
  options: {
    filteredSlashCommands: SlashCommand[];
    slashMenuIndex: number;
    setSlashMenuIndex: (index: number | ((prev: number) => number)) => void;
    onSelectCommand: (command: SlashCommand) => void;
    onEscape: () => void;
  }
): boolean {
  const {
    filteredSlashCommands,
    slashMenuIndex,
    setSlashMenuIndex,
    onSelectCommand,
    onEscape,
  } = options;

  if (filteredSlashCommands.length === 0) return false;

  switch (e.key) {
    case "ArrowDown":
      e.preventDefault();
      setSlashMenuIndex((idx) =>
        Math.min(idx + 1, filteredSlashCommands.length - 1)
      );
      return true;

    case "ArrowUp":
      e.preventDefault();
      setSlashMenuIndex((idx) => Math.max(idx - 1, 0));
      return true;

    case "Tab":
    case "Enter": {
      e.preventDefault();
      const selectedCommand = filteredSlashCommands[slashMenuIndex];
      if (selectedCommand) {
        onSelectCommand(selectedCommand);
      }
      return true;
    }

    case "Escape":
      e.preventDefault();
      onEscape();
      return true;

    default:
      return false;
  }
}

/**
 * Keyboard handler for input prompts menu navigation
 *
 * Handles arrow keys for navigation, Enter/Tab for selection
 * The last index triggers "Create new prompt" action
 * @returns true if event was handled and should not propagate
 */
export function handleInputPromptsKeyDown(
  e: React.KeyboardEvent,
  options: {
    filteredPrompts: InputPrompt[];
    tabbingIconIndex: number;
    setTabbingIconIndex: (index: number | ((prev: number) => number)) => void;
    onSelectPrompt: (prompt: InputPrompt) => void;
    onCreateNew: () => void;
  }
): boolean {
  const {
    filteredPrompts,
    tabbingIconIndex,
    setTabbingIconIndex,
    onSelectPrompt,
    onCreateNew,
  } = options;

  switch (e.key) {
    case "Tab":
    case "Enter": {
      e.preventDefault();
      // Last index is the "Create new prompt" option
      if (tabbingIconIndex === filteredPrompts.length) {
        onCreateNew();
      } else {
        const selectedPrompt =
          filteredPrompts[tabbingIconIndex >= 0 ? tabbingIconIndex : 0];
        if (selectedPrompt) {
          onSelectPrompt(selectedPrompt);
        }
      }
      return true;
    }

    case "ArrowDown":
      e.preventDefault();
      setTabbingIconIndex((idx) => Math.min(idx + 1, filteredPrompts.length));
      return true;

    case "ArrowUp":
      e.preventDefault();
      setTabbingIconIndex((idx) => Math.max(idx - 1, 0));
      return true;

    default:
      return false;
  }
}
