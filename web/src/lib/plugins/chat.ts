import type { MinimalAgent } from "@/lib/agents/types";
import { parsePluginId } from "@/lib/plugins/routes";
import type { MemberPlugin, useMemberPlugins } from "@/lib/plugins/member";
import type { ChatPluginReference } from "@/lib/plugins/types";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import type { ToolSnapshot } from "@/lib/tools/types";
import { DEFAULT_AGENT_ID } from "@/lib/constants";

export interface ChatPlugin {
  plugin: Exclude<MemberPlugin, { kind: "external-app" }>;
  toolIds: number[];
}

export function effectiveChatForcedToolId({
  requestedToolId,
  agent,
  plugins,
}: {
  requestedToolId: number | null;
  agent: Pick<MinimalAgent, "id" | "tools"> | undefined;
  plugins: readonly MemberPlugin[];
}): number | null {
  const tool = agent?.tools.find((entry) => entry.id === requestedToolId);
  if (!tool) return null;
  if (agent?.id === DEFAULT_AGENT_ID && !tool.in_code_tool_id) {
    const available = plugins.some((plugin) => {
      switch (plugin.kind) {
        case "mcp":
          return (
            plugin.server.id === tool.mcp_server_id &&
            plugin.server.user_enabled_in_chat !== false
          );
        case "openapi":
          return (
            tool.mcp_server_id == null &&
            plugin.tool.id === tool.id &&
            plugin.tool.user_enabled_in_chat !== false
          );
        case "external-app":
          return false;
      }
    });
    if (!available) return null;
  }
  return tool.id;
}

export function chatPluginsForAgent(
  plugins: readonly MemberPlugin[],
  agent: Pick<MinimalAgent, "id" | "tools">
): ChatPlugin[] {
  const tools = agent.tools.filter(
    (tool) => tool.enabled && tool.chat_selectable && !tool.in_code_tool_id
  );
  return plugins.flatMap((plugin) => {
    if (plugin.kind === "external-app") return [];
    if (
      agent.id === DEFAULT_AGENT_ID &&
      (plugin.kind === "mcp"
        ? plugin.server.user_enabled_in_chat === false
        : plugin.tool.user_enabled_in_chat === false)
    )
      return [];
    const toolIds = tools
      .filter((tool) =>
        plugin.kind === "mcp"
          ? tool.mcp_server_id === plugin.server.id
          : tool.mcp_server_id == null && tool.id === plugin.tool.id
      )
      .map((tool) => tool.id);
    return toolIds.length > 0 ? [{ plugin, toolIds }] : [];
  });
}

export function isChatPluginEnabled(
  plugin: ChatPlugin,
  configuration: Pick<ToolConfigurationHandle, "stateOf">
): boolean {
  return plugin.toolIds.some((id) => configuration.stateOf(id) !== "disabled");
}

export function setChatPluginEnabled(
  plugin: ChatPlugin,
  enabled: boolean,
  configuration: Pick<ToolConfigurationHandle, "setToolState">
): void {
  for (const id of plugin.toolIds) {
    configuration.setToolState(id, (current) =>
      enabled ? (current === "disabled" ? null : current) : "disabled"
    );
  }
}

export function parseChatPluginIntent(
  params: Pick<URLSearchParams, "get">
): ChatPluginReference | null {
  const kind = params.get("pluginKind");
  const id = parsePluginId(params.get("pluginId") ?? undefined);
  return (kind === "mcp" || kind === "openapi") && id !== null
    ? { kind, id }
    : null;
}

export function chatPluginIntentLoadState(
  reference: ChatPluginReference,
  {
    plugins,
    loading,
    errors,
  }: {
    plugins: readonly MemberPlugin[];
    loading: Pick<
      ReturnType<typeof useMemberPlugins>["loading"],
      "servers" | "tools"
    >;
    errors: Pick<
      ReturnType<typeof useMemberPlugins>["errors"],
      "servers" | "tools"
    >;
  }
): "loading" | "error" | "loaded" {
  if (reference.kind === "mcp") {
    if (errors.servers) return "error";
    return loading.servers ? "loading" : "loaded";
  }
  if (errors.tools) return "error";
  if (loading.tools) return "loading";
  const target = plugins.find(
    (plugin) => plugin.kind === "openapi" && plugin.tool.id === reference.id
  );
  if (target?.connection.kind === "checking") return "loading";
  return target?.connection.kind === "unavailable" ? "error" : "loaded";
}

export function applyChatPluginIntent(
  reference: ChatPluginReference,
  plugins: readonly ChatPlugin[],
  configuration: ToolConfigurationHandle
): boolean {
  if (reference.kind !== "mcp" && reference.kind !== "openapi") return false;
  if (!configuration.ready) return false;
  const attached = plugins.find(({ plugin }) =>
    reference.kind === "mcp"
      ? plugin.kind === "mcp" && plugin.server.id === reference.id
      : plugin.kind === "openapi" && plugin.tool.id === reference.id
  );
  if (!attached) return false;
  setChatPluginEnabled(attached, true, configuration);
  return true;
}

export function withoutChatPluginIntent(
  params: URLSearchParams
): URLSearchParams {
  const next = new URLSearchParams(params);
  next.delete("pluginKind");
  next.delete("pluginId");
  return next;
}

export function safeChatReturnTo(
  value: string | null | undefined
): "/app" | `/app?${string}` {
  if (!value || !value.startsWith("/app") || value.includes("\\"))
    return "/app";
  const parsed = new URL(value, "https://onyx.invalid");
  if (parsed.origin !== "https://onyx.invalid" || parsed.pathname !== "/app") {
    return "/app";
  }
  const query = new URLSearchParams();
  const chatId = parsed.searchParams.get("chatId");
  if (chatId && chatId.length <= 256) query.set("chatId", chatId);
  for (const key of ["agentId", "projectId"]) {
    const id = parsePluginId(parsed.searchParams.get(key) ?? undefined);
    if (id !== null) query.set(key, String(id));
  }
  const search = query.toString();
  return search ? `/app?${search}` : "/app";
}

export function memberPluginsHref(returnTo: string): `/app/plugins?${string}` {
  return `/app/plugins?${new URLSearchParams({ returnTo: safeChatReturnTo(returnTo) })}`;
}

export function memberPluginChatHref(
  reference: ChatPluginReference,
  returnTo?: string | null
): `/app?${string}` {
  const target = new URL(safeChatReturnTo(returnTo), "https://onyx.invalid");
  target.searchParams.set("pluginKind", reference.kind);
  target.searchParams.set("pluginId", String(reference.id));
  return `/app?${target.searchParams}`;
}

export function enabledChatToolIds(
  tools: readonly ToolSnapshot[],
  configuration: Pick<ToolConfigurationHandle, "disabledToolIds">
): number[] | undefined {
  if (configuration.disabledToolIds.length === 0) return undefined;
  return tools
    .filter((tool) => !configuration.disabledToolIds.includes(tool.id))
    .map((tool) => tool.id);
}
