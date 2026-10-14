import {
  SOURCE_DESCRIPTION_KEYS,
  SOURCE_METADATA_MAP,
} from "@/lib/connectors/constants";
import { SourceCategory, ValidSources } from "@/lib/connectors/types/source";

describe("source catalog metadata", () => {
  it.each(Object.values(ValidSources))("registers %s", (source) => {
    expect(SOURCE_METADATA_MAP[source]).toBeDefined();
    expect(SOURCE_METADATA_MAP[source].displayName).toBeTruthy();
  });

  it("keeps Jira Service Management in the ticketing catalog", () => {
    expect(
      SOURCE_METADATA_MAP[ValidSources.JiraServiceManagement]
    ).toMatchObject({
      displayName: "Jira Service Management",
      category: SourceCategory.TicketingAndTaskManagement,
      docs: "https://docs.onyx.app/admins/connectors/official/jira_service_management",
    });
    expect(SOURCE_DESCRIPTION_KEYS[ValidSources.JiraServiceManagement]).toBe(
      "sources.jira_service_management.description"
    );
  });
});
