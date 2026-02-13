import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { expectScreenshot } from "./utils/visualRegression";

test.use({ storageState: "admin_auth.json" });
test.describe.configure({ mode: "parallel" });

interface AdminPageSnapshot {
  name: string;
  path: string;
  pageTitle: string;
  options?: {
    paragraphText?: string | RegExp;
    buttonName?: string;
    subHeaderText?: string;
  };
}

const ADMIN_PAGES: AdminPageSnapshot[] = [
  {
    name: "Document Management - Explorer",
    path: "documents/explorer",
    pageTitle: "Document Explorer",
  },
  {
    name: "Connectors - Add Connector",
    path: "add-connector",
    pageTitle: "Add Connector",
  },
  {
    name: "Custom Assistants - Assistants",
    path: "assistants",
    pageTitle: "Assistants",
    options: {
      paragraphText:
        "Assistants are a way to build custom search/question-answering experiences for different use cases.",
    },
  },
  {
    name: "Configuration - Document Processing",
    path: "configuration/document-processing",
    pageTitle: "Document Processing",
  },
  {
    name: "Document Management - Document Sets",
    path: "documents/sets",
    pageTitle: "Document Sets",
    options: {
      paragraphText:
        "Document Sets allow you to group logically connected documents into a single bundle. These can then be used as a filter when performing searches to control the scope of information Onyx searches over.",
    },
  },
  {
    name: "Custom Assistants - Slack Bots",
    path: "bots",
    pageTitle: "Slack Bots",
    options: {
      paragraphText:
        "Setup Slack bots that connect to Onyx. Once setup, you will be able to ask questions to Onyx directly from Slack. Additionally, you can:",
    },
  },
  {
    name: "Custom Assistants - Standard Answers",
    path: "standard-answer",
    pageTitle: "Standard Answers",
  },
  {
    name: "Performance - Usage Statistics",
    path: "performance/usage",
    pageTitle: "Usage Statistics",
  },
  {
    name: "Document Management - Feedback",
    path: "documents/feedback",
    pageTitle: "Document Feedback",
  },
  {
    name: "Configuration - LLM",
    path: "configuration/llm",
    pageTitle: "LLM Setup",
  },
  {
    name: "Connectors - Existing Connectors",
    path: "indexing/status",
    pageTitle: "Existing Connectors",
  },
  {
    name: "User Management - Groups",
    path: "groups",
    pageTitle: "Manage User Groups",
  },
  {
    name: "Appearance & Theming",
    path: "theme",
    pageTitle: "Appearance & Theming",
  },
  {
    name: "Configuration - Search Settings",
    path: "configuration/search",
    pageTitle: "Search Settings",
  },
  {
    name: "Custom Assistants - MCP Actions",
    path: "actions/mcp",
    pageTitle: "MCP Actions",
  },
  {
    name: "Custom Assistants - OpenAPI Actions",
    path: "actions/open-api",
    pageTitle: "OpenAPI Actions",
  },
  {
    name: "User Management - Token Rate Limits",
    path: "token-rate-limits",
    pageTitle: "Token Rate Limits",
    options: {
      paragraphText:
        "Token rate limits enable you control how many tokens can be spent in a given time period. With token rate limits, you can:",
      buttonName: "Create a Token Rate Limit",
    },
  },
];

async function verifyAdminPageNavigation(
  page: Page,
  path: string,
  pageTitle: string,
  options?: {
    paragraphText?: string | RegExp;
    buttonName?: string;
    subHeaderText?: string;
  }
) {
  await page.goto(`/admin/${path}`);

  try {
    await expect(page.locator('[aria-label="admin-page-title"]')).toHaveText(
      pageTitle,
      {
        timeout: 10000,
      }
    );
  } catch (error) {
    console.error(
      `Failed to find admin-page title with text "${pageTitle}" for path "${path}"`
    );
    // NOTE: This is a temporary measure for debugging the issue
    console.error(await page.content());
    throw error;
  }

  if (options?.paragraphText) {
    await expect(page.locator("p.text-sm").nth(0)).toHaveText(
      options.paragraphText
    );
  }

  if (options?.buttonName) {
    await expect(
      page.getByRole("button", { name: options.buttonName })
    ).toHaveCount(1);
  }
}

const THEMES = ["light", "dark"] as const;

for (const theme of THEMES) {
  test.describe(`Admin pages (${theme} mode)`, () => {
    // Inject the theme into localStorage before every navigation so
    // next-themes picks it up on first render.
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((t: string) => {
        localStorage.setItem("theme", t);
      }, theme);
    });

    for (const snapshot of ADMIN_PAGES) {
      test(`Admin - ${snapshot.name}`, async ({ page }) => {
        await verifyAdminPageNavigation(
          page,
          snapshot.path,
          snapshot.pageTitle,
          snapshot.options
        );

        // Wait for all network requests to settle before capturing the screenshot.
        await page.waitForLoadState("networkidle");

        // Capture a screenshot for visual regression review.
        // The screenshot name includes the theme to keep light/dark baselines separate.
        const screenshotName = `admin-${theme}-${snapshot.path.replace(
          /\//g,
          "-"
        )}`;
        await expectScreenshot(page, { name: screenshotName });
      });
    }
  });
}
