/**
 * Jira Service Management Connector
 *
 * Pulls all tickets (issues) from a specified Jira Service Management project.
 *
 * Required configuration:
 *   - jiraDomain:   e.g. "yourcompany.atlassian.net"
 *   - email:        Atlassian account email used for API token authentication
 *   - apiToken:     Personal API token (see https://id.atlassian.com/manage-profile/security/api-tokens)
 *   - projectKey:   Jira project key (e.g. "ITSM")
 *
 * The connector implements the Danswer `BaseConnector` interface.
 */

import axios, { AxiosInstance } from "axios";
import { BaseConnector, Document } from "../baseConnector";

/** Configuration required for the connector */
export interface JiraSMConnectorConfig {
  jiraDomain: string;   // e.g. "yourcompany.atlassian.net"
  email: string;        // Atlassian account email
  apiToken: string;     // Personal API token
  projectKey: string;   // Project key to fetch tickets from
}

/** Helper to build the Jira REST API base URL */
function buildBaseUrl(domain: string): string {
  // Ensure no trailing slash
  const cleaned = domain.replace(/\/+$/, "");
  return `https://${cleaned}/rest/api/3`;
}

/** Main connector class */
export class JiraServiceManagementConnector extends BaseConnector {
  private readonly client: AxiosInstance;
  private readonly baseUrl: string;
  private readonly projectKey: string;

  constructor(private readonly config: JiraSMConnectorConfig) {
    super();

    this.baseUrl = buildBaseUrl(config.jiraDomain);
    this.projectKey = config.projectKey;

    // Basic auth using email:apiToken (Base64 encoded)
    const auth = Buffer.from(`${config.email}:${config.apiToken}`).toString(
      "base64"
    );

    this.client = axios.create({
      baseURL: this.baseUrl,
      headers: {
        Authorization: `Basic ${auth}`,
        Accept: "application/json",
      },
    });
  }

  /** Load **all** tickets from the project */
  async load(): Promise<Document[]> {
    // Use JQL to fetch all issues in the project
    const jql = `project = ${this.projectKey} ORDER BY created ASC`;
    return this.fetchIssues(jql);
  }

  /**
   * Get tickets that have been updated after the supplied timestamp.
   * If `lastUpdated` is undefined/null, behaves like `load()`.
   */
  async getUpdates(lastUpdated?: Date): Promise<Document[]> {
    if (!lastUpdated) {
      return this.load();
    }

    // JQL to fetch issues updated after the given date
    const iso = lastUpdated.toISOString();
    const jql = `project = ${this.projectKey} AND updated > "${iso}" ORDER BY updated ASC`;
    return this.fetchIssues(jql);
  }

  /** Core pagination logic – fetches issues matching the supplied JQL */
  private async fetchIssues(jql: string): Promise<Document[]> {
    const maxResults = 100; // Jira max per request
    let startAt = 0;
    const allDocs: Document[] = [];

    while (true) {
      const response = await this.client.get("/search", {
        params: {
          jql,
          startAt,
          maxResults,
          fields: [
            "summary",
            "description",
            "status",
            "created",
            "updated",
            "issuetype",
            "priority",
            "assignee",
            "reporter",
          ].join(","),
        },
      });

      const data = response.data;
      const issues = data.issues as any[];

      for (const issue of issues) {
        const fields = issue.fields;
        const doc: Document = {
          // Unique identifier for Danswer
          id: issue.id,
          // Human‑readable title
          title: fields.summary ?? "(no summary)",
          // Content – prefer description, fallback to summary
          content:
            typeof fields.description === "string"
              ? fields.description
              : this.extractPlainTextFromDescription(fields.description) ||
                fields.summary,
          // Metadata useful for downstream processing / display
          metadata: {
            issueKey: issue.key,
            url: `https://${this.config.jiraDomain}/browse/${issue.key}`,
            status: fields.status?.name,
            issueType: fields.issuetype?.name,
            priority: fields.priority?.name,
            assignee: fields.assignee?.displayName,
            reporter: fields.reporter?.displayName,
            created: fields.created,
            updated: fields.updated,
          },
        };
        allDocs.push(doc);
      }

      // Pagination termination condition
      if (data.startAt + data.maxResults >= data.total) {
        break;
      }
      startAt += maxResults;
    }

    return allDocs;
  }

  /**
   * Jira stores description as a rich‑text Atlassian Document Format (ADF).
   * This helper extracts a simple plain‑text representation.
   */
  private extractPlainTextFromDescription(description: any): string | null {
    if (!description || !Array.isArray(description.content)) {
      return null;
    }

    const walk = (nodes: any[]): string => {
      let text = "";
      for (const node of nodes) {
        if (node.type === "text") {
          text += node.text;
        } else if (node.content) {
          text += walk(node.content);
        }
        if (node.type === "paragraph") {
          text += "\n";
        }
      }
      return text;
    };

    return walk(description.content).trim();
  }
}

/* Export a factory function for easier dynamic loading */
export function createConnector(
  config: JiraSMConnectorConfig
): JiraServiceManagementConnector {
  return new JiraServiceManagementConnector(config);
}