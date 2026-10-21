import { useLayoutEffect, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import { SWRConfig, type State } from "swr";
import { Button, Text } from "@opal/components";
import { ToastProvider } from "@opal/layouts";
import type { MethodSpec, ToolSnapshot } from "@/lib/tools/types";
import OpenAPIPluginCreateModal from "@/sections/plugins/OpenAPIPluginCreateModal";
import messages from "@/i18n/messages/en.json";

const copy = messages.actions;
const validationError = "Each operation must have a unique operationId.";
const creationError = "A plugin named Release API already exists.";

const definition = {
  openapi: "3.0.0",
  info: { title: "Release API", version: "1.0.0" },
  servers: [{ url: "https://releases.example.com" }],
  paths: {
    "/releases": {
      get: {
        operationId: "listReleases",
        summary: "List recent releases",
        responses: { "200": { description: "Release list" } },
      },
    },
    "/deployments": {
      post: {
        operationId: "scheduleDeployment",
        summary: "Schedule a deployment",
        responses: { "200": { description: "Scheduled deployment" } },
      },
    },
    "/deployments/{id}": {
      delete: {
        operationId: "cancelDeployment",
        summary: "Cancel a pending deployment",
        responses: { "204": { description: "Deployment cancelled" } },
      },
    },
  },
};

const methods: MethodSpec[] = [
  {
    name: "listReleases",
    summary: "List recent releases",
    method: "get",
    path: "/releases",
    spec: {},
    custom_headers: [],
  },
  {
    name: "scheduleDeployment",
    summary: "Schedule a deployment",
    method: "post",
    path: "/deployments",
    spec: {},
    custom_headers: [],
  },
  {
    name: "cancelDeployment",
    summary: "Cancel a pending deployment",
    method: "delete",
    path: "/deployments/{id}",
    spec: {},
    custom_headers: [],
  },
];

const tool: ToolSnapshot = {
  id: 42,
  name: "Release API",
  display_name: "Release API",
  description: "Manage releases and deployments.",
  definition,
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  permissions: { edit: true, authenticate: true, delete: true },
};

interface CreationStoryProps {
  scenario?:
    | "ready"
    | "validating"
    | "validation-error"
    | "saving"
    | "create-error";
}

function CreationStory({ scenario = "ready" }: CreationStoryProps) {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(true);
  const [created, setCreated] = useState(false);
  const [cache] = useState(() => new Map<string, State>());

  useLayoutEffect(() => {
    const originalFetch = window.fetch;
    let saved = false;
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    const mockFetch: typeof fetch = async (input, init) => {
      const path = new URL(
        input instanceof Request ? input.url : String(input),
        window.location.origin
      ).pathname;
      if (!path.startsWith("/api/")) return originalFetch(input, init);
      if (path === "/api/admin/default-assistant/configuration")
        return json({ tool_ids: [99] });
      if (path === "/api/admin/default-assistant")
        return json({ tool_ids: [99, tool.id] });
      if (path === "/api/tool/openapi") return json(saved ? [tool] : []);
      if (path === "/api/admin/tool/custom/validate") {
        if (scenario === "validating") return new Promise<Response>(() => {});
        if (scenario === "validation-error")
          return json({ detail: validationError }, 400);
        return json({ methods });
      }
      if (path === "/api/admin/tool/custom" && init?.method === "POST") {
        if (scenario === "saving") return new Promise<Response>(() => {});
        if (scenario === "create-error")
          return json({ detail: creationError }, 409);
        saved = true;
        return json(tool);
      }
      if (path === "/api/auth/type")
        return json({ auth_type: "basic", oauth_enabled: true });
      if (path === "/api/settings")
        return json({ tier: "community", ee_features_enabled: false });
      if (path === "/api/enterprise-settings") return json({});
      return json({ detail: "No story fixture" }, 404);
    };
    window.fetch = mockFetch;
    setReady(true);
    return () => {
      if (window.fetch === mockFetch) window.fetch = originalFetch;
    };
  }, [scenario]);

  return ready ? (
    <SWRConfig
      value={{
        provider: () => cache,
        shouldRetryOnError: false,
        revalidateOnFocus: false,
      }}
    >
      <ToastProvider>
        <div className="flex h-screen items-center justify-center bg-background-tint-01">
          {open ? (
            <OpenAPIPluginCreateModal
              open
              onClose={() => setOpen(false)}
              onCreated={() => {
                setCreated(true);
                setOpen(false);
              }}
            />
          ) : (
            <div className="flex flex-col items-center gap-4">
              {created && (
                <Text font="main-content-body" color="text-05">
                  {copy.addOpenApiModal.toasts.actionCreated}
                </Text>
              )}
              <Button
                onClick={() => {
                  setCreated(false);
                  setOpen(true);
                }}
              >
                {copy.plugins.openapi.createTitle}
              </Button>
            </div>
          )}
        </div>
      </ToastProvider>
    </SWRConfig>
  ) : null;
}

const meta = {
  title: "Apps/Plugins/OpenAPI creation",
  component: CreationStory,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof CreationStory>;
export default meta;
type Story = StoryObj<typeof meta>;

async function fillSchema(value = JSON.stringify(definition, null, 2)) {
  const page = within(document.body);
  const editor = await page.findByRole("textbox");
  await fireEvent.change(editor, { target: { value } });
  return page;
}

async function reviewSchema() {
  const page = await fillSchema();
  await page.findByText("listReleases");
  await waitFor(() =>
    expect(
      page.getByRole("button", {
        name: copy.mcpSetup.continue,
      })
    ).toBeEnabled()
  );
  return page;
}

async function authorizeSchema() {
  const page = await reviewSchema();
  await userEvent.click(
    page.getByRole("button", { name: copy.mcpSetup.continue })
  );
  await page.findByRole("dialog", { name: "Connect to Release API" });
  await waitFor(() =>
    expect(
      page.getByRole("button", {
        name: copy.addOpenApiModal.submitButton.addLabel,
      })
    ).toBeEnabled()
  );
  return page;
}

async function chooseAuthorization(label: string) {
  const page = await authorizeSchema();
  await userEvent.click(page.getByRole("combobox"));
  await userEvent.click(
    await page.findByRole("option", {
      name:
        label === copy.openApiAuthModal.authMethod.oauth.label
          ? /^OAuth Each user/
          : new RegExp(label),
    })
  );
  return page;
}

export const Empty: Story = {};
export const SchemaEntered: Story = {
  play: async () => {
    await fillSchema();
  },
};
export const Review: Story = {
  name: "Schema and actions",
  play: async () => {
    const page = await reviewSchema();
    await expect(await page.findByText("listReleases")).toBeVisible();
    await expect(await page.findByText("scheduleDeployment")).toBeVisible();
    await expect(await page.findByText("cancelDeployment")).toBeVisible();
  },
};
export const BackPreservesSchema: Story = {
  play: async () => {
    const page = await authorizeSchema();
    await userEvent.click(
      page.getByRole("button", { name: copy.mcpSetup.back })
    );
    await expect(page.getByRole("textbox")).toHaveValue(
      JSON.stringify(definition, null, 2)
    );
  },
};
export const InvalidJson: Story = {
  play: async () => {
    const page = await fillSchema("{ invalid JSON");
    await userEvent.click(
      page.getByRole("button", { name: copy.mcpSetup.continue })
    );
    await expect(
      await page.findByText(copy.addOpenApiModal.definition.invalidJson)
    ).toBeVisible();
  },
};
export const ValidationError: Story = {
  args: { scenario: "validation-error" },
  play: async () => {
    const page = await fillSchema();
    await userEvent.click(
      page.getByRole("button", { name: copy.mcpSetup.continue })
    );
    await expect(await page.findByText(validationError)).toBeVisible();
  },
};
export const Validating: Story = {
  args: { scenario: "validating" },
  play: async () => {
    const page = await fillSchema();
    await userEvent.click(
      page.getByRole("button", { name: copy.mcpSetup.continue })
    );
    await expect(
      page.getByRole("button", { name: copy.mcpSetup.checking })
    ).toBeDisabled();
  },
};
export const Saving: Story = {
  args: { scenario: "saving" },
  play: async () => {
    const page = await authorizeSchema();
    await userEvent.click(
      page.getByRole("button", {
        name: copy.addOpenApiModal.submitButton.addLabel,
      })
    );
    await expect(
      await page.findByRole("button", {
        name: copy.openApiAuthModal.submitButton.pendingLabel,
      })
    ).toBeDisabled();
  },
};
export const CreationError: Story = {
  args: { scenario: "create-error" },
  play: async () => {
    const page = await authorizeSchema();
    await userEvent.click(
      page.getByRole("button", {
        name: copy.addOpenApiModal.submitButton.addLabel,
      })
    );
    await expect(await page.findByText(creationError)).toBeVisible();
    await expect(
      page.getByRole("dialog", { name: "Connect to Release API" })
    ).toBeVisible();
  },
};
export const Created: Story = {
  play: async () => {
    const page = await authorizeSchema();
    await userEvent.click(
      page.getByRole("button", {
        name: copy.addOpenApiModal.submitButton.addLabel,
      })
    );
    await waitFor(() =>
      expect(page.queryByRole("dialog")).not.toBeInTheDocument()
    );
    await expect(
      page.getByRole("button", { name: copy.plugins.openapi.createTitle })
    ).toBeVisible();
  },
};
export const CancelDiscardsSchema: Story = {
  play: async () => {
    const page = await fillSchema();
    await userEvent.click(
      page.getByRole("button", {
        name: copy.addOpenApiModal.cancelButton.label,
      })
    );
    await waitFor(() =>
      expect(page.queryByRole("dialog")).not.toBeInTheDocument()
    );
    await userEvent.click(
      page.getByRole("button", { name: copy.plugins.openapi.createTitle })
    );
    await expect(await page.findByRole("textbox")).toHaveValue("");
  },
};

export const Authorization: Story = {
  play: async () => {
    await authorizeSchema();
  },
};
export const OAuthAuthorization: Story = {
  play: async () => {
    await chooseAuthorization(copy.openApiAuthModal.authMethod.oauth.label);
  },
};
export const HeaderAuthorization: Story = {
  play: async () => {
    await chooseAuthorization(
      copy.openApiAuthModal.authMethod.customHeader.label
    );
  },
};
export const BackPreservesAuthorization: Story = {
  play: async () => {
    const page = await chooseAuthorization(
      copy.openApiAuthModal.authMethod.oauth.label
    );
    await fireEvent.change(
      await page.findByRole("textbox", {
        name: copy.openApiAuthModal.clientId.label,
      }),
      { target: { value: "release-client" } }
    );
    await userEvent.click(
      page.getByRole("button", { name: copy.mcpSetup.back })
    );
    await page.findByRole("dialog", { name: copy.plugins.openapi.createTitle });
    await userEvent.click(
      page.getByRole("button", { name: copy.mcpSetup.continue })
    );
    await expect(
      await page.findByRole("textbox", {
        name: copy.openApiAuthModal.clientId.label,
      })
    ).toHaveValue("release-client");
  },
};
