import { connectorFormState } from "@/lib/connectors/checks/formState";
import { connectorConfigs } from "@/lib/connectors/connectors";

test("takes config fields, tab contents included, and drops form controls", () => {
  const state = connectorFormState(connectorConfigs.confluence, {
    name: "my connector",
    access_type: "public",
    wiki_base: "https://acme.atlassian.net",
    is_cloud: true,
    indexing_scope: "space",
    space: "ENG",
  });

  expect(state).toEqual({
    wiki_base: "https://acme.atlassian.net",
    is_cloud: true,
    space: "ENG",
  });
});

test("drops blank list entries, as the create request does", () => {
  const state = connectorFormState(connectorConfigs.zoom, {
    meeting_ids: ["111", " ", ""],
  });

  expect(state.meeting_ids).toEqual(["111"]);
});
