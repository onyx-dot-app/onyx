import { connectorConfigs } from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/connectors/types/source";
import { splitCredentialBoundFields } from "@/lib/connectors/utils";

describe("splitCredentialBoundFields", () => {
  it("keeps JSM project settings separate from credential-bound fields", () => {
    const configuration = connectorConfigs[ValidSources.JiraServiceManagement];
    const split = splitCredentialBoundFields(
      ValidSources.JiraServiceManagement,
      configuration
    );

    expect(split.values.map((field) => field.name).sort()).toEqual([
      "jira_base_url",
      "scoped_token",
    ]);
    expect(split.rest.values.map((field) => field.name)).toEqual([
      "project_key",
      "jql_query",
      "comment_email_blacklist",
    ]);
  });

  it("moves the bound fields that credentialBoundFields.json names", () => {
    const configuration = connectorConfigs[ValidSources.Confluence];
    const split = splitCredentialBoundFields(
      ValidSources.Confluence,
      configuration
    );

    expect(split.values.map((field) => field.name).sort()).toEqual([
      "is_cloud",
      "scoped_token",
      "wiki_base",
    ]);
    expect(split.rest.values.some((field) => field.name === "wiki_base")).toBe(
      false
    );
    expect(split.rest.values.length + split.values.length).toBe(
      configuration.values.length
    );
  });
});
