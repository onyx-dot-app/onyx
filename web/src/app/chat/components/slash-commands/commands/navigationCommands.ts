import { SlashCommand } from "@/app/chat/components/slash-commands/types";

export const navigationCommands: SlashCommand[] = [
  {
    command: "/new-chat",
    description: "Start a new chat session",
    type: "navigation",
    execute: (ctx) => {
      ctx.clearInput();
      ctx.startNewChat();
    },
  },
  {
    command: "/create-agent",
    description: "Create a new AI assistant",
    type: "navigation",
    execute: (ctx) => {
      ctx.clearInput();
      ctx.navigate("/assistants/new");
    },
  },
  {
    command: "/agents",
    description: "Browse available AI assistants",
    type: "navigation",
    execute: (ctx) => {
      ctx.clearInput();
      ctx.navigate("/chat/agents");
    },
  },
  {
    command: "/add-connector",
    description: "Connect a new data source",
    type: "navigation",
    adminOnly: true,
    execute: (ctx) => {
      ctx.clearInput();
      ctx.navigate("/admin/add-connector");
    },
  },
  {
    command: "/connectors",
    description: "View and manage data connectors",
    type: "navigation",
    adminOnly: true,
    execute: (ctx) => {
      ctx.clearInput();
      ctx.navigate("/admin/indexing/status");
    },
  },
  {
    command: "/settings",
    description: "Open workspace settings",
    type: "navigation",
    adminOnly: true,
    execute: (ctx) => {
      ctx.clearInput();
      ctx.navigate("/admin/settings");
    },
  },
  {
    command: "/users",
    description: "Manage workspace users",
    type: "navigation",
    adminOnly: true,
    execute: (ctx) => {
      ctx.clearInput();
      ctx.navigate("/admin/users");
    },
  },
  {
    command: "/document-sets",
    description: "Manage document collections",
    type: "navigation",
    adminOnly: true,
    execute: (ctx) => {
      ctx.clearInput();
      ctx.navigate("/admin/documents/sets");
    },
  },
  {
    command: "/llm-config",
    description: "Configure LLM providers",
    type: "navigation",
    adminOnly: true,
    execute: (ctx) => {
      ctx.clearInput();
      ctx.navigate("/admin/configuration/llm");
    },
  },
];
