import { connectorConfigs } from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/connectors/types/source";
import { splitCredentialBoundFields } from "@/lib/connectors/utils";

describe("splitCredentialBoundFields", () => {
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
