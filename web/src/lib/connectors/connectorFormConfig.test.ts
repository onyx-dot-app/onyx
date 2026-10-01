import { buildConnectorSpecificConfig } from "@/lib/connectors/connectorFormConfig";
import type { ConnectionConfiguration } from "@/lib/connectors/types";

const configuration: ConnectionConfiguration = {
  description: "Test connector",
  values: [
    {
      type: "list",
      label: "Channels",
      name: "channels",
      transform: (values) => values.map((value) => value.toLowerCase()),
    },
    {
      type: "tab",
      label: "Scope",
      name: "indexing_scope",
      tabs: [
        {
          label: "Everything",
          value: "everything",
          fields: [{ type: "text", label: "Site", name: "site" }],
        },
      ],
    },
  ],
  advanced_values: [
    { type: "list", label: "Exclude", name: "exclude_channels" },
    { type: "checkbox", label: "Bots", name: "include_bot_messages" },
  ],
};

describe("buildConnectorSpecificConfig", () => {
  it("keeps only config fields, as the create request sends them", () => {
    expect(
      buildConnectorSpecificConfig(
        {
          name: "My connector",
          groups: [1],
          access_type: "sync",
          restrict_access_to_groups: true,
          restriction_group_ids: [2],
          pruneFreq: 10,
          indexingStart: null,
          refreshFreq: 5,
          auto_sync_options: { a: 1 },
          indexing_scope: "everything",
          channels: ["General", " ", "Support"],
          exclude_channels: ["Alerts", ""],
          include_bot_messages: false,
          site: "https://example.com",
        },
        configuration
      )
    ).toEqual({
      channels: ["general", "support"],
      exclude_channels: ["Alerts"],
      include_bot_messages: false,
      site: "https://example.com",
    });
  });
});
