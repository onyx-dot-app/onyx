"use client";

import { useCallback, useMemo } from "react";
import {
  SlashCommand,
  CommandContext,
} from "@/app/chat/components/slash-commands/types";
import { navigationCommands } from "@/app/chat/components/slash-commands/commands/navigationCommands";
import { generateToolCommands } from "@/app/chat/components/slash-commands/commands/toolCommands";
import {
  generatePromptCommands,
  createPromptCommand,
} from "@/app/chat/components/slash-commands/commands/promptCommands";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { InputPrompt } from "@/app/chat/interfaces";

interface UseSlashCommandsOptions {
  isAdmin?: boolean;
  tools?: ToolSnapshot[];
  disabledToolIds?: number[];
  inputPrompts?: InputPrompt[];
  shortcutsEnabled?: boolean;
}

/**
 * Hook for managing slash commands in chat input
 *
 * Combines navigation commands, tool toggle commands, and prompt shortcuts into a unified menu.
 *
 * @param options.isAdmin - Whether the current user is an admin (for admin-only commands)
 * @param options.tools - Available tools for the current assistant
 * @param options.disabledToolIds - Tool IDs that are disabled for the current assistant
 * @param options.inputPrompts - User's saved prompt shortcuts
 * @param options.shortcutsEnabled - Whether prompt shortcuts feature is enabled
 */
export function useSlashCommands(options: UseSlashCommandsOptions = {}) {
  const {
    isAdmin = false,
    tools = [],
    disabledToolIds = [],
    inputPrompts = [],
    shortcutsEnabled = false,
  } = options;

  const allCommands = useMemo(() => {
    const toolCommands = generateToolCommands(tools, disabledToolIds);
    const promptCommands =
      shortcutsEnabled && inputPrompts.length > 0
        ? generatePromptCommands(inputPrompts)
        : [];

    // Add "create new prompt" command if shortcuts are enabled
    const createCommand = shortcutsEnabled ? [createPromptCommand] : [];

    return [
      ...toolCommands,
      ...navigationCommands,
      ...promptCommands,
      ...createCommand,
    ];
  }, [tools, disabledToolIds, inputPrompts, shortcutsEnabled]);

  const getFilteredCommands = useCallback(
    (input: string): SlashCommand[] => {
      const trimmed = input.trim().toLowerCase();
      if (!trimmed.startsWith("/")) return [];

      return allCommands.filter((cmd) => {
        if (!cmd.command.toLowerCase().startsWith(trimmed)) return false;
        if (cmd.adminOnly && !isAdmin) return false;
        if (cmd.hidden && cmd.command.toLowerCase() !== trimmed) return false;
        return true;
      });
    },
    [allCommands, isAdmin]
  );

  const executeCommand = useCallback(
    (message: string, context: CommandContext): SlashCommand | undefined => {
      const trimmed = message.trim().toLowerCase();
      const command = allCommands.find(
        (cmd) => cmd.command.toLowerCase() === trimmed
      );

      if (!command) return undefined;
      if (command.adminOnly && !isAdmin) return undefined;

      command.execute(context);
      return command;
    },
    [allCommands, isAdmin]
  );

  const isSlashCommand = useCallback(
    (message: string): boolean => {
      const trimmed = message.trim().toLowerCase();
      return allCommands.some(
        (cmd) =>
          cmd.command.toLowerCase() === trimmed && (!cmd.adminOnly || isAdmin)
      );
    },
    [allCommands, isAdmin]
  );

  return {
    executeCommand,
    isSlashCommand,
    getFilteredCommands,
  };
}
