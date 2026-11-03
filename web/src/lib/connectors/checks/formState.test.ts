import { connectorFormState } from "@/lib/connectors/checks/formState";
import { connectorConfigs } from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/connectors/types/source";

test("takes config fields, tab contents included, and drops form controls", () => {
  const state = connectorFormState(
    ValidSources.Confluence,
    connectorConfigs.confluence,
    {
      name: "my connector",
      access_type: "public",
      wiki_base: "https://acme.atlassian.net",
      is_cloud: true,
      indexing_scope: "space",
      space: "ENG",
    }
  );

  expect(state).toEqual({
    wiki_base: "https://acme.atlassian.net",
    is_cloud: true,
    space: "ENG",
  });
});

test("drops blank list entries, as the create request does", () => {
  const state = connectorFormState(ValidSources.Zoom, connectorConfigs.zoom, {
    meeting_ids: ["111", " ", ""],
  });

  expect(state.meeting_ids).toEqual(["111"]);
});

test("drops the realm, which lives in the credential only", () => {
  const state = connectorFormState(
    ValidSources.Zendesk,
    connectorConfigs.zendesk,
    { zendesk_subdomain: "acme", content_type: "articles" }
  );

  expect(state).toEqual({ content_type: "articles" });
});
