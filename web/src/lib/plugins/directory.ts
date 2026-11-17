import type {
  MemberIntegration,
  MemberPluginRef,
} from "@/lib/integrations/types";
import type { CustomSkill, Skill } from "@/lib/skills/types";

/** Where a plugin sits: the Organization library, the user's own uploads, or
 * a personal plugin of someone else that the user can see. */
export type PluginSection = "organization" | "mine" | "shared";

export type PluginFilter = "all" | "skills" | "integrations";

/** One plugin of the member Plugins page: a custom skill, the plugin that
 * holds integrations, or both. A custom skill's id is its plugin id. */
export interface MemberPluginEntry {
  id: string;
  name: string;
  description: string | null;
  section: PluginSection;
  ownerEmail: string | null;
  skills: CustomSkill[];
  integrations: MemberIntegration[];
  /** The plugin ref of a plugin that holds only integrations. */
  ref: MemberPluginRef | null;
}

function isCustomSkill(skill: Skill): skill is CustomSkill {
  return skill.source === "custom";
}

/** Joins the custom skills and the integration plugin refs by plugin id. */
export function memberPluginEntries(
  skills: readonly Skill[],
  integrations: readonly MemberIntegration[],
  userEmail: string | null,
  locale: string
): MemberPluginEntry[] {
  const entries = new Map<string, MemberPluginEntry>();
  function personal(ownerEmail: string | null): PluginSection {
    return ownerEmail === null || ownerEmail === userEmail ? "mine" : "shared";
  }
  for (const skill of skills) {
    if (!isCustomSkill(skill)) continue;
    const ownerEmail = skill.owner?.email ?? null;
    entries.set(skill.id, {
      id: skill.id,
      name: skill.name,
      description: skill.description || null,
      section:
        skill.published_version_number !== null
          ? "organization"
          : personal(ownerEmail),
      ownerEmail,
      skills: [skill],
      integrations: [],
      ref: null,
    });
  }
  for (const integration of integrations) {
    for (const ref of integration.plugins) {
      if (ref.installation_policy === "NOT_AVAILABLE") continue;
      const entry = entries.get(ref.plugin_id);
      if (entry) {
        if (!entry.integrations.includes(integration))
          entry.integrations.push(integration);
        continue;
      }
      entries.set(ref.plugin_id, {
        id: ref.plugin_id,
        name: ref.plugin_name,
        description: integration.description,
        section:
          ref.scope === "organization"
            ? "organization"
            : personal(ref.owner_email),
        ownerEmail: ref.owner_email,
        skills: [],
        integrations: [integration],
        ref,
      });
    }
  }
  return [...entries.values()].sort((a, b) =>
    a.name.localeCompare(b.name, locale)
  );
}

/** Why the user cannot use the on/off switch of a plugin. */
export type PluginSwitchBlock = "required" | "notAvailable" | "unavailable";

export interface PluginSwitch {
  enabled: boolean;
  blocked: PluginSwitchBlock | null;
}

/** The user's on/off switch: a skill's switch, else the plugin ref's. */
export function pluginSwitch(entry: MemberPluginEntry): PluginSwitch {
  const skill = entry.skills[0];
  if (skill)
    return {
      enabled: skill.enabled,
      blocked: skill.can_toggle
        ? null
        : skill.required_for_user
          ? "required"
          : "unavailable",
    };
  const policy = entry.ref?.installation_policy ?? null;
  return {
    enabled: entry.ref?.enabled ?? false,
    blocked:
      policy === "REQUIRED"
        ? "required"
        : policy === "NOT_AVAILABLE"
          ? "notAvailable"
          : null,
  };
}

/** The owner shares and publishes a private plugin that holds only
 * integrations. */
export function ownsPrivateIntegrationPlugin(
  entry: MemberPluginEntry,
  userEmail: string | null
): boolean {
  return (
    entry.ref?.scope === "personal" &&
    userEmail !== null &&
    entry.ref.owner_email === userEmail
  );
}

export function filterPlugins(
  entries: readonly MemberPluginEntry[],
  filter: PluginFilter,
  query: string
): MemberPluginEntry[] {
  const search = query.trim().toLocaleLowerCase();
  return entries.filter(
    (entry) =>
      (filter === "all" ||
        (filter === "skills" ? entry.skills : entry.integrations).length > 0) &&
      [
        entry.name,
        entry.description ?? "",
        ...entry.integrations.map((integration) => integration.name),
      ]
        .join(" ")
        .toLocaleLowerCase()
        .includes(search)
  );
}

/** The integrations of a plugin that the user needs to connect or reconnect. */
export function pendingIntegrations(
  integrations: readonly MemberIntegration[]
): MemberIntegration[] {
  return integrations.filter(
    (integration) =>
      integration.status.state === "not_connected" ||
      integration.status.state === "needs_reconnect"
  );
}

export function memberPluginHref(
  pluginId: string,
  tab?: MemberPluginTab
): `/app/plugins/${string}` {
  return tab && tab !== "overview"
    ? `/app/plugins/${pluginId}?tab=${tab}`
    : `/app/plugins/${pluginId}`;
}

export type MemberPluginTab =
  | "overview"
  | "skills"
  | "integrations"
  | "versions";

export function parseMemberPluginTab(value: string | null): MemberPluginTab {
  return value === "skills" || value === "integrations" || value === "versions"
    ? value
    : "overview";
}
