import {
  connectorConfigs,
  translateConfiguration,
} from "@/lib/connectors/connectors";
import {
  createConnectorInitialValues,
  createConnectorValidationSchema,
} from "@/lib/connectors/utils";
import { ValidSources } from "@/lib/connectors/types/source";

const PROJECT_KEY_REQUIRED = "Project Key is required";
const CONFIG = translateConfiguration(
  connectorConfigs[ValidSources.JiraServiceManagement],
  (key) =>
    key === "connectors.jira.fields.project_key.label" ? "Project Key" : key
);

function schema() {
  return createConnectorValidationSchema(
    ValidSources.JiraServiceManagement,
    false,
    { required: (field) => `${field} is required` },
    CONFIG
  );
}

function values(overrides: Record<string, unknown> = {}) {
  return {
    ...createConnectorInitialValues(ValidSources.JiraServiceManagement),
    name: "Jira Service Management",
    jira_base_url: "https://example.atlassian.net",
    access_type: "public",
    ...overrides,
  };
}

describe("Jira Service Management scope validation", () => {
  it("accepts Everything without a project key", async () => {
    await expect(
      schema().validate(
        values({ indexing_scope: "everything", project_key: "" })
      )
    ).resolves.toMatchObject({ indexing_scope: "everything" });
  });

  it("requires a project key for Project scope", async () => {
    await expect(
      schema().validate(values({ indexing_scope: "project" }))
    ).rejects.toThrow(PROJECT_KEY_REQUIRED);
    await expect(
      schema().validate(values({ indexing_scope: "project", project_key: "" }))
    ).rejects.toThrow(PROJECT_KEY_REQUIRED);
  });

  it("rejects a whitespace-only project key", async () => {
    await expect(
      schema().validate(
        values({ indexing_scope: "project", project_key: "   " })
      )
    ).rejects.toThrow(PROJECT_KEY_REQUIRED);
  });

  it("accepts Project scope with a project key", async () => {
    await expect(
      schema().validate(
        values({ indexing_scope: "project", project_key: "PROJ" })
      )
    ).resolves.toMatchObject({ project_key: "PROJ" });
  });
});
