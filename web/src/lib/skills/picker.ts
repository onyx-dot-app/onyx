import type { ExternalAppType } from "@/app/craft/v1/apps/registry";
import type { CraftApp, CraftMcpServer } from "@/lib/integrations/craft";
import type { Skill } from "@/lib/skills/types";
import type { CaretText } from "@/lib/contentEditable";
import { CRAFT_APPS_TAB_PARAM } from "@/app/craft/v1/apps/connectableApps";
import { CRAFT_APPS_PATH } from "@/app/craft/v1/constants";

export interface PickerSkill {
  kind: "skill";
  slug: string;
  name: string;
  description: string;
}

export interface PickerApp {
  kind: "app";
  externalAppId: number;
  name: string;
  appType: ExternalAppType;
  authenticated: boolean;
}

/** A craft-enabled MCP server. Kept a distinct kind from `PickerApp` rather
 * than folded in: the two are connected differently, reach the agent by
 * different channels, and the user is told which is which. */
export interface PickerMcpServer {
  kind: "mcp";
  mcpServerId: number;
  name: string;
  serverUrl: string;
  authenticated: boolean;
}

export type PickerEntry = PickerSkill | PickerApp | PickerMcpServer;

export interface PickerSections {
  skills: PickerSkill[];
  apps: PickerApp[];
  mcpServers: PickerMcpServer[];
}

const EMPTY_SECTIONS: PickerSections = { skills: [], apps: [], mcpServers: [] };

/** Case-insensitive name ordering, shared so every surface listing apps and MCP
 * servers sorts them the same way. */
export function compareByName<T extends { name: string }>(a: T, b: T): number {
  return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
}

export interface PickerSkillSources {
  builtins?: readonly Skill[];
  /** The custom skills the sandbox gets, one per skill of a plugin, from
   * `useChatSkills`. */
  customs?: readonly PickerSkill[];
}

export function toPickerSections(
  skillSources: PickerSkillSources | undefined,
  externalApps: CraftApp[] | undefined,
  mcpServers?: CraftMcpServer[] | undefined
): PickerSections {
  if (
    !skillSources?.builtins &&
    !skillSources?.customs &&
    !externalApps &&
    !mcpServers
  )
    return EMPTY_SECTIONS;

  const skills: PickerSkill[] = [];
  const apps: PickerApp[] = [];
  const mcp: PickerMcpServer[] = [];
  for (const b of skillSources?.builtins ?? []) {
    if (!b.is_available || !b.enabled) continue;
    skills.push({
      kind: "skill",
      slug: b.name,
      name: b.name,
      description: b.description,
    });
  }

  const builtinSlugs = new Set(skills.map((skill) => skill.slug));
  for (const custom of skillSources?.customs ?? []) {
    if (!builtinSlugs.has(custom.slug)) skills.push(custom);
  }

  for (const app of externalApps ?? []) {
    apps.push({
      kind: "app",
      externalAppId: app.id,
      name: app.name,
      appType: app.app_type,
      authenticated: app.authenticated,
    });
  }

  for (const server of mcpServers ?? []) {
    mcp.push({
      kind: "mcp",
      mcpServerId: server.id,
      name: server.name,
      serverUrl: server.server_url,
      // Whether Craft can actually authenticate this user against the server,
      // not whether a credential row exists. See `craft_connected`.
      authenticated: server.craft_connected,
    });
  }

  skills.sort((a, b) => a.slug.localeCompare(b.slug));
  apps.sort((a, b) => compareByName(a, b) || a.externalAppId - b.externalAppId);
  mcp.sort((a, b) => compareByName(a, b) || a.mcpServerId - b.mcpServerId);

  return { skills, apps, mcpServers: mcp };
}

export interface PickerTrigger {
  triggerIndex: number;
  /** The whole word after the trigger, through the caret to the next
   * whitespace. */
  query: string;
  /** The trigger and query split at the caret: the text a pick replaces. */
  token: CaretText;
}

/** Opens Craft's picker; a picked skill becomes a `/slug` prompt prefix. */
export const CRAFT_PICKER_TRIGGER = "/";

// The trigger must start the caret's word, before the caret. The query runs
// from the trigger to the next whitespace, so the caret can sit inside it.
export function detectPickerTrigger(
  text: CaretText,
  trigger: string
): PickerTrigger | null {
  const triggerIndex = text.before.lastIndexOf(trigger);
  if (
    triggerIndex === -1 ||
    (triggerIndex > 0 && !/\s/.test(text.before.charAt(triggerIndex - 1)))
  )
    return null;

  const before = text.before.slice(triggerIndex);
  if (/\s/.test(before)) return null;
  const after = text.after.slice(0, text.after.search(/\s|$/));

  return {
    triggerIndex,
    query: before.slice(trigger.length) + after,
    token: { before, after },
  };
}

function matchesQuery(entry: PickerEntry, query: string): boolean {
  if (!query) return true;
  let fields: string[];
  switch (entry.kind) {
    case "skill":
      fields = [entry.slug, entry.name, entry.description];
      break;
    case "app":
      fields = [String(entry.externalAppId), entry.name];
      break;
    case "mcp":
      fields = [String(entry.mcpServerId), entry.name];
      break;
  }
  return fields.some((field) => field.toLowerCase().includes(query));
}

export function pickerEntryKey(entry: PickerEntry): string {
  switch (entry.kind) {
    case "skill":
      return `skill:${entry.slug}`;
    case "app":
      return `app:${entry.externalAppId}`;
    case "mcp":
      return `mcp:${entry.mcpServerId}`;
  }
}

export function pickerEntryPromptPrefix(entry: PickerEntry): string {
  switch (entry.kind) {
    case "skill":
      return `${CRAFT_PICKER_TRIGGER}${entry.slug}`;
    case "app":
      return `[Use external app ${JSON.stringify(entry.name)} (ID: ${entry.externalAppId})]`;
    case "mcp":
      // The server's tools are already wired into the session, so this only
      // points the agent at them.
      return `[Use the MCP server ${JSON.stringify(entry.name)} and its tools]`;
  }
}

type PickerConnectionPath =
  | `${typeof CRAFT_APPS_PATH}?connect=${number}`
  | `${typeof CRAFT_APPS_PATH}?${typeof CRAFT_APPS_TAB_PARAM}=mcp`;

export function pickerEntryConnectionPath(
  entry: PickerEntry
): PickerConnectionPath | null {
  switch (entry.kind) {
    case "skill":
      return null;
    case "app":
      return entry.authenticated
        ? null
        : `${CRAFT_APPS_PATH}?connect=${entry.externalAppId}`;
    // MCP servers have no per-server deep link; land on the MCP tab instead.
    case "mcp":
      return entry.authenticated
        ? null
        : `${CRAFT_APPS_PATH}?${CRAFT_APPS_TAB_PARAM}=mcp`;
  }
}

export function filterPickerSections(
  sections: PickerSections,
  query: string
): PickerSections {
  const q = query.trim().toLowerCase();
  if (!q) return sections;
  return {
    skills: sections.skills.filter((s) => matchesQuery(s, q)),
    apps: sections.apps.filter((a) => matchesQuery(a, q)),
    mcpServers: sections.mcpServers.filter((m) => matchesQuery(m, q)),
  };
}

// Skills, then apps, then MCP servers; must match the popover's visual render
// order so keyboard nav indices line up.
export function flattenSections(sections: PickerSections): PickerEntry[] {
  return [...sections.skills, ...sections.apps, ...sections.mcpServers];
}
