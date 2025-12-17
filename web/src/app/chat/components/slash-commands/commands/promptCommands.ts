import { InputPrompt } from "@/app/chat/interfaces";
import { SlashCommand } from "@/app/chat/components/slash-commands/types";

/**
 * Converts an InputPrompt to a slash command format
 */
function toSlashCommand(promptName: string): string {
  return (
    "/" +
    promptName
      .replace(/([a-z])([A-Z])/g, "$1-$2")
      .replace(/[\s_]+/g, "-")
      .replace(/[^a-zA-Z0-9-]/g, "")
      .toLowerCase()
  );
}

/**
 * Generates slash commands from input prompts
 * Each prompt becomes a command that inserts its content when selected
 */
export function generatePromptCommands(
  inputPrompts: InputPrompt[]
): SlashCommand[] {
  return inputPrompts
    .filter((prompt) => prompt.active)
    .map((prompt) => ({
      command: toSlashCommand(prompt.prompt),
      description:
        prompt.content
          ?.trim()
          .replace(/\n/g, " ") // Replace newlines with spaces
          .slice(0, 80) || "Insert prompt", // Reduced to 80 chars for better single-line display
      type: "prompt" as const,
      promptContent: prompt.content,
      execute: (ctx) => {
        // Insert the prompt content into the input
        ctx.clearInput();
        if (ctx.setMessage) {
          ctx.setMessage(prompt.content || "");
        }
      },
    }));
}

/**
 * Special command to create a new prompt
 */
export const createPromptCommand: SlashCommand = {
  command: "/new-prompt",
  description: "Create a new prompt shortcut",
  type: "prompt",
  execute: (ctx) => {
    ctx.navigate("/chat/input-prompts");
  },
};
