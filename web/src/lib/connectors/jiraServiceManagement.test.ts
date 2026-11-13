import {
  createConnectorInitialValues,
  createConnectorValidationSchema,
} from "@/lib/connectors/utils";
import { ValidSources } from "@/lib/connectors/types/source";

const PROJECT_KEY_REQUIRED = "Project key cannot be blank.";
const JQL_REQUIRED = "JQL query cannot be blank.";

function schema() {
  return createConnectorValidationSchema(
    ValidSources.JiraServiceManagement,
    false,
    {
      jiraServiceManagementProjectKeyRequired: PROJECT_KEY_REQUIRED,
      jiraServiceManagementJqlRequired: JQL_REQUIRED,
    }
  );
}

function values(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    ...createConnectorInitialValues(ValidSources.JiraServiceManagement),
    name: "Service desk",
    access_type: "public",
    jira_base_url: "https://jira.example.com",
    ...overrides,
  };
}

describe("Jira Service Management connector form", () => {
  it("accepts every service desk without a project key or a query", async () => {
    await expect(
      schema().validate(values({ indexing_scope: "everything" }))
    ).resolves.toMatchObject({ indexing_scope: "everything" });
  });

  it("requires a project key on the project tab", async () => {
    await expect(
      schema().validate(
        values({ indexing_scope: "project", project_key: "  " })
      )
    ).rejects.toThrow(PROJECT_KEY_REQUIRED);
    await expect(
      schema().validate(
        values({ indexing_scope: "project", project_key: "IT" })
      )
    ).resolves.toMatchObject({ project_key: "IT" });
  });

  it("requires a query on the JQL tab", async () => {
    await expect(
      schema().validate(values({ indexing_scope: "jql", jql_query: " " }))
    ).rejects.toThrow(JQL_REQUIRED);
    await expect(
      schema().validate(
        values({ indexing_scope: "jql", jql_query: "project = IT" })
      )
    ).resolves.toMatchObject({ jql_query: "project = IT" });
  });

  it("does not require a Jira project key", async () => {
    await expect(
      createConnectorValidationSchema(ValidSources.Jira).validate({
        ...createConnectorInitialValues(ValidSources.Jira),
        name: "Jira",
        access_type: "public",
        jira_base_url: "https://jira.example.com",
        indexing_scope: "project",
      })
    ).resolves.toMatchObject({ indexing_scope: "project" });
  });
});
