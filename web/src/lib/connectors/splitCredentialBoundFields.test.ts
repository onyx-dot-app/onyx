import { connectorConfigs } from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/connectors/types/source";
import {
  connectorConfigFromForm,
  credentialBoundFieldNames,
  formOnlyFieldNames,
  splitCredentialBoundFields,
} from "@/lib/connectors/utils";
import {
  credentialMatchesBoundFields,
  getCredentialSpec,
} from "@/lib/credentials/utils";

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

  it("moves the form-only realm above the account too", () => {
    const split = splitCredentialBoundFields(
      ValidSources.Zendesk,
      connectorConfigs[ValidSources.Zendesk]
    );

    expect(split.values.map((field) => field.name)).toEqual([
      "zendesk_subdomain",
    ]);
  });
});

describe("form-only realm fields", () => {
  it("come from the credential spec's realm fields, one config field each", () => {
    const sources = [
      ValidSources.Axero,
      ValidSources.Bookstack,
      ValidSources.Egnyte,
      ValidSources.Freshdesk,
      ValidSources.GitHub,
      ValidSources.GitLab,
      ValidSources.Gong,
      ValidSources.Highspot,
      ValidSources.Loopio,
      ValidSources.Outline,
      ValidSources.TestRail,
      ValidSources.Zendesk,
    ] as const;
    for (const source of sources) {
      const names = formOnlyFieldNames(source);
      expect(names).toHaveLength(1);
      const configNames = connectorConfigs[source].values.map(
        (field) => field.name
      );
      expect(configNames).toEqual(expect.arrayContaining(names));
    }
    expect(formOnlyFieldNames(ValidSources.Confluence)).toEqual([]);
  });

  it("are left out of the create payload", () => {
    const config = connectorConfigFromForm(
      ValidSources.Zendesk,
      connectorConfigs[ValidSources.Zendesk],
      {
        zendesk_subdomain: "acme",
        content_type: "articles",
        new_account: { zendesk_token: "secret" },
      },
      new Set(["new_account"])
    );

    expect(config).toEqual({ content_type: "articles" });
  });

  it("still disable a saved account with another realm", () => {
    const spec = getCredentialSpec(ValidSources.Zendesk);
    const matches = (stored: string) =>
      credentialMatchesBoundFields(
        credentialBoundFieldNames(ValidSources.Zendesk),
        spec?.fields ?? {},
        { zendesk_subdomain: stored },
        { zendesk_subdomain: "acme" }
      );

    expect(matches("https://acme.zendesk.com")).toBe(true);
    expect(matches("other")).toBe(false);
  });
});
