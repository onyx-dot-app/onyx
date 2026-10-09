import type { IconFunctionComponent } from "@opal/types";

// Normalized govern-list view of anything granted to the Craft agent.
// External apps and MCP servers map into this shape (see integrations.ts), so
// both render and behave through the same card — only where the data comes
// from differs.
export interface ConfiguredIntegration {
  key: string;
  /** Custom apps keep a row tag; the tabs already say app vs MCP server. */
  isCustom: boolean;
  logo: IconFunctionComponent;
  name: string;
  /** Row summary, rendered " · "-separated: counts, credentials, skills. */
  facts: string[];
  /** Problem chips (invalid skill, orphaned provider); empty when healthy. */
  warnings: string[];
  enabled: boolean;
  toggleEnabled: () => Promise<void>;
  /** Null → no Edit action (e.g. orphaned app types). */
  edit: (() => void) | null;
  /** Null → not deletable (MCP servers, Onyx-managed apps). */
  remove: {
    run: () => Promise<void>;
    retainedCustomSkillCount: number;
  } | null;
}
