export type SlashCommandType = "prompt" | "navigation" | "tool";

export interface SlashCommand {
  command: string;
  description: string;
  type: SlashCommandType;
  hidden?: boolean;
  adminOnly?: boolean;
  toolId?: number;
  promptContent?: string; // For prompt commands - the content to insert
  execute: (context: CommandContext) => void | Promise<void>;
}

export interface CommandContext {
  clearInput: () => void;
  startNewChat: () => void;
  navigate: (path: string) => void;
  isAdmin: boolean;
  toggleForcedTool: (toolId: number) => void;
  setMessage?: (message: string) => void; // For prompt commands to set input content
  triggerFileUpload?: () => void; // For triggering file upload dialog
}
