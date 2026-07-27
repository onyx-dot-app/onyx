import { buildEntryMenuItems } from "@/app/craft/components/buildEntryMenuItems";
import type { PickerSections } from "@/lib/skills/picker";

function sections(over: Partial<PickerSections> = {}): PickerSections {
  return { skills: [], apps: [], mcpServers: [], ...over };
}

const ACME_APP = {
  kind: "app" as const,
  externalAppId: 3,
  name: "Acme CRM",
  appType: "CUSTOM" as const,
  authenticated: true,
};

const ASANA_MCP = {
  kind: "mcp" as const,
  mcpServerId: 8,
  name: "Asana MCP",
  serverUrl: "https://mcp.asana.com/mcp",
  authenticated: true,
};

function appsFlyout(input: PickerSections) {
  const items = buildEntryMenuItems(input, {
    onAttachFiles: jest.fn(),
    onSelectEntry: jest.fn(),
    onBrowseSkills: jest.fn(),
    onBrowseApps: jest.fn(),
  });
  const apps = items.find((item) => item?.key === "apps");
  return apps?.flyoutItems ?? [];
}

describe("buildEntryMenuItems Apps flyout", () => {
  it("lists external apps and MCP servers together", () => {
    const flyout = appsFlyout(
      sections({ apps: [ACME_APP], mcpServers: [ASANA_MCP] })
    );

    expect(flyout.map((item) => item.label)).toEqual(["Acme CRM", "Asana MCP"]);
  });

  it("labels MCP rows so they are distinguishable from apps", () => {
    const flyout = appsFlyout(
      sections({ apps: [ACME_APP], mcpServers: [ASANA_MCP] })
    );

    expect(flyout.map((item) => [item.key, item.description])).toEqual([
      ["app:3", undefined],
      ["mcp:8", "MCP server"],
    ]);
  });

  it("offers a Connect affordance per row based on its own state", () => {
    const flyout = appsFlyout(
      sections({
        apps: [{ ...ACME_APP, authenticated: false }],
        mcpServers: [ASANA_MCP],
      })
    );

    expect(flyout[0]?.rightContent).toBeDefined();
    expect(flyout[1]?.rightContent).toBeUndefined();
  });

  it("selects the entry that was clicked, whichever kind it is", () => {
    const onSelectEntry = jest.fn();
    const items = buildEntryMenuItems(
      sections({ apps: [ACME_APP], mcpServers: [ASANA_MCP] }),
      {
        onAttachFiles: jest.fn(),
        onSelectEntry,
        onBrowseSkills: jest.fn(),
        onBrowseApps: jest.fn(),
      }
    );
    const flyout =
      items.find((item) => item?.key === "apps")?.flyoutItems ?? [];

    flyout[1]?.onSelect?.();
    expect(onSelectEntry).toHaveBeenCalledWith(ASANA_MCP);
  });

  it("prompts to connect only when there is neither an app nor an MCP server", () => {
    expect(appsFlyout(sections()).map((item) => item.key)).toEqual([
      "apps-empty",
    ]);
    // An MCP server alone is still something to offer, so no empty state.
    expect(appsFlyout(sections({ mcpServers: [ASANA_MCP] })).length).toBe(1);
    expect(appsFlyout(sections({ mcpServers: [ASANA_MCP] }))[0]?.key).toBe(
      "mcp:8"
    );
  });
});
