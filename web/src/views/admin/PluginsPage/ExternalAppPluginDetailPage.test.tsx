import type { ComponentProps } from "react";
import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { useSWRConfig } from "swr";
import ExternalAppPluginDetailPage from "@/views/admin/PluginsPage/ExternalAppPluginDetailPage";
import type ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import type CreateCustomAppModal from "@/views/admin/PluginsPage/components/CreateCustomAppModal";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  ExternalAppAdminResponse,
  BuiltInExternalAppDescriptor,
} from "@/app/craft/v1/apps/registry";

let mockFullAdmin = false;
let mockCraftAvailable = true;
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ onyx_craft_available: mockCraftAvailable }),
}));
const mockPush = jest.fn();
const mockReplace = jest.fn();
const onClose = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  usePathname: () => "/admin/plugins",
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({ isGlobalHolder: mockFullAdmin }),
}));
jest.mock("@/app/craft/v1/apps/admin/ConfigureProviderModal", () => {
  const { useState } = jest.requireActual<typeof import("react")>("react");
  return {
    __esModule: true,
    default: function Editor(
      props: ComponentProps<typeof ConfigureProviderModal>
    ) {
      const [name, setName] = useState(props.existingApp?.name ?? "");
      return (
        <div role="dialog" aria-label={props.existingApp?.name}>
          <input
            aria-label="App name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button onClick={props.onSaved}>Save</button>
          <button onClick={props.onClose}>Close</button>
        </div>
      );
    },
  };
});
jest.mock("@/views/admin/PluginsPage/components/CreateCustomAppModal", () => {
  const { useState } = jest.requireActual<typeof import("react")>("react");
  return {
    __esModule: true,
    default: function Editor(
      props: ComponentProps<typeof CreateCustomAppModal>
    ) {
      const [name, setName] = useState(props.existingApp?.name ?? "");
      return (
        <div role="dialog" aria-label={props.existingApp?.name}>
          <input
            aria-label="App name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button onClick={props.onSaved}>Save</button>
          <button onClick={props.onClose}>Close</button>
        </div>
      );
    },
  };
});

const app: ExternalAppAdminResponse = {
  id: 7,
  name: "Workspace service",
  app_type: "CUSTOM",
  enabled: true,
  upstream_url_patterns: [],
  auth_template: {},
  organization_credentials: {},
  credential_placeholder_keys: [],
  actions: [],
  associated_skills: [],
  is_onyx_managed: false,
};
const slack: BuiltInExternalAppDescriptor = {
  app_type: "SLACK",
  name: "Slack",
  upstream_url_patterns: [],
  auth_template: {},
  required_org_credential_fields: [],
  setup_instructions: "",
  actions: [],
};
const slackApp: ExternalAppAdminResponse = { ...app, app_type: "SLACK" };
beforeEach(() => {
  mockFullAdmin = false;
  mockCraftAvailable = true;
  mockPush.mockClear();
  mockReplace.mockClear();
  onClose.mockClear();
});
afterEach(() => jest.restoreAllMocks());

test("does not fetch Craft app data from a direct link when Craft is disabled", () => {
  mockFullAdmin = true;
  mockCraftAvailable = false;
  const network = jest.spyOn(global, "fetch");
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(network).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

function BackgroundRefresh({ resource }: { resource: string }) {
  const { mutate } = useSWRConfig();
  return <button onClick={() => void mutate(resource)}>Refresh apps</button>;
}

test("does not fetch any external app admin data before full admin authorization", () => {
  const network = jest.spyOn(global, "fetch");
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(network).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("opens custom editing without requesting or waiting for provider options", async () => {
  mockFullAdmin = true;
  const network = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      String(input) === SWR_KEYS.buildExternalAppsAdmin
        ? new Response(JSON.stringify([app]))
        : new Promise<Response>(() => {})
    );
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(await screen.findByRole("dialog", { name: app.name })).toBeVisible();
  expect(network.mock.calls).toEqual([[SWR_KEYS.buildExternalAppsAdmin]]);
});

test("retries app-list failure into the custom editor", async () => {
  mockFullAdmin = true;
  let installedRequestCount = 0;
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (String(input) === SWR_KEYS.buildExternalAppsAdmin) {
      installedRequestCount += 1;
      return installedRequestCount === 1
        ? new Response(JSON.stringify({ detail: "Unavailable" }), {
            status: 503,
          })
        : new Response(JSON.stringify([app]));
    }
    return new Response(JSON.stringify([]));
  });
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(await screen.findByText("Apps could not load")).toBeVisible();
  const dialog = screen.getByRole("dialog");
  expect(dialog).toHaveAttribute("data-position", "center");
  expect(dialog).toHaveAttribute("data-width", "md");
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("dialog", { name: app.name })).toBeVisible();
});

test("closes the modal after app-list failure", async () => {
  mockFullAdmin = true;
  jest
    .spyOn(global, "fetch")
    .mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: "Unavailable" }), { status: 503 })
    );
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(await screen.findByText("Apps could not load")).toBeVisible();
  expect(screen.getByRole("dialog", { name: "Craft Apps" })).toBeVisible();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
  expect(mockPush).not.toHaveBeenCalled();
});

test("keeps loading in a closable modal without requesting provider options before the app is known", async () => {
  mockFullAdmin = true;
  const network = jest
    .spyOn(global, "fetch")
    .mockImplementation(() => new Promise<Response>(() => {}));
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(screen.getByRole("dialog", { name: "Craft Apps" })).toBeVisible();
  expect(screen.getByRole("status", { name: "Loading" })).toBeVisible();
  expect(network.mock.calls).toEqual([[SWR_KEYS.buildExternalAppsAdmin]]);
  const user = setupUser();
  await user.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
});

test("keeps a missing app in a closable modal without requesting provider options", async () => {
  mockFullAdmin = true;
  const network = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(JSON.stringify([])));
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(await screen.findByText("No plugins found")).toBeVisible();
  expect(screen.getByRole("dialog", { name: "Craft Apps" })).toBeVisible();
  expect(network.mock.calls).toEqual([[SWR_KEYS.buildExternalAppsAdmin]]);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
});

test("waits for built-in provider options inside the modal", async () => {
  mockFullAdmin = true;
  const network = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      String(input) === SWR_KEYS.buildExternalAppsAdmin
        ? new Response(JSON.stringify([slackApp]))
        : new Promise<Response>(() => {})
    );
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  await waitFor(() =>
    expect(network.mock.calls).toEqual([
      [SWR_KEYS.buildExternalAppsAdmin],
      [SWR_KEYS.buildExternalAppsBuiltInOptions],
    ])
  );
  expect(screen.getByRole("dialog", { name: "Craft Apps" })).toBeVisible();
  expect(screen.getByRole("status", { name: "Loading" })).toBeVisible();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
});

test("keeps an unavailable built-in provider in a closable modal", async () => {
  mockFullAdmin = true;
  jest
    .spyOn(global, "fetch")
    .mockImplementation(
      async (input) =>
        new Response(
          JSON.stringify(
            String(input) === SWR_KEYS.buildExternalAppsAdmin ? [slackApp] : []
          )
        )
    );
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(await screen.findByText("provider unavailable")).toBeVisible();
  expect(screen.getByRole("dialog", { name: "Craft Apps" })).toBeVisible();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
});

test("retries both resources after built-in provider options fail", async () => {
  mockFullAdmin = true;
  let descriptorRequestCount = 0;
  const network = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (String(input) === SWR_KEYS.buildExternalAppsAdmin)
        return new Response(JSON.stringify([slackApp]));
      descriptorRequestCount += 1;
      return descriptorRequestCount === 1
        ? new Response(JSON.stringify({ detail: "Unavailable" }), {
            status: 503,
          })
        : new Response(JSON.stringify([slack]));
    });
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(await screen.findByText("Apps could not load")).toBeVisible();
  expect(screen.getByRole("dialog", { name: "Craft Apps" })).toBeVisible();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("dialog", { name: app.name })).toBeVisible();
  expect(network.mock.calls).toEqual([
    [SWR_KEYS.buildExternalAppsAdmin],
    [SWR_KEYS.buildExternalAppsBuiltInOptions],
    [SWR_KEYS.buildExternalAppsAdmin],
    [SWR_KEYS.buildExternalAppsBuiltInOptions],
  ]);
});

test("reuses the custom editor for the selected ID and refreshes records after saving", async () => {
  mockFullAdmin = true;
  const network = jest
    .spyOn(global, "fetch")
    .mockImplementation(
      async (input) =>
        new Response(
          JSON.stringify(String(input).endsWith("options") ? [] : [app])
        )
    );
  render(<ExternalAppPluginDetailPage appId={7} onClose={onClose} />);
  expect(await screen.findByRole("dialog", { name: app.name })).toBeVisible();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(
      network.mock.calls.filter(
        ([input]) => String(input) === "/api/build/admin/apps"
      )
    ).toHaveLength(2)
  );
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
});

test.each([
  {
    editor: "custom",
    existingApp: app,
    resource: SWR_KEYS.buildExternalAppsAdmin,
  },
  {
    editor: "provider with app refresh failure",
    existingApp: slackApp,
    resource: SWR_KEYS.buildExternalAppsAdmin,
  },
  {
    editor: "provider with descriptor refresh failure",
    existingApp: slackApp,
    resource: SWR_KEYS.buildExternalAppsBuiltInOptions,
  },
])(
  "keeps the same $editor editor and draft",
  async ({ existingApp, resource }) => {
    mockFullAdmin = true;
    let failRefresh = false;
    const onError = jest.fn();
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      if (failRefresh && String(input) === resource)
        return new Response(JSON.stringify({ detail: "Unavailable" }), {
          status: 503,
        });
      return new Response(
        JSON.stringify(
          String(input) === SWR_KEYS.buildExternalAppsAdmin
            ? [existingApp]
            : [slack]
        )
      );
    });
    render(
      <>
        <ExternalAppPluginDetailPage appId={7} onClose={onClose} />
        <BackgroundRefresh resource={resource} />
      </>,
      { swrConfig: { onError } }
    );
    const dialog = await screen.findByRole("dialog", { name: app.name });
    const input = screen.getByRole("textbox", { name: "App name" });
    const user = setupUser();
    await user.clear(input);
    await user.type(input, "Draft workspace service");
    failRefresh = true;
    fireEvent.click(screen.getByRole("button", { name: "Refresh apps" }));
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("dialog", { name: app.name })).toBe(dialog);
    expect(screen.getByRole("textbox", { name: "App name" })).toBe(input);
    expect(input).toHaveValue("Draft workspace service");
    expect(screen.queryByText("Apps could not load")).toBeNull();
  }
);

test.each(["apps", "descriptors"])(
  "shows a failed background read when cached %s do not resolve an editor",
  async (missing) => {
    mockFullAdmin = true;
    let failRefresh = false;
    const resource =
      missing === "apps"
        ? SWR_KEYS.buildExternalAppsAdmin
        : SWR_KEYS.buildExternalAppsBuiltInOptions;
    const onError = jest.fn();
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      if (failRefresh && String(input) === resource)
        return new Response(JSON.stringify({ detail: "Unavailable" }), {
          status: 503,
        });
      return new Response(
        JSON.stringify(
          String(input) === SWR_KEYS.buildExternalAppsAdmin &&
            missing !== "apps"
            ? [slackApp]
            : []
        )
      );
    });
    render(
      <>
        <ExternalAppPluginDetailPage appId={7} onClose={onClose} />
        <BackgroundRefresh resource={resource} />
      </>,
      { swrConfig: { onError } }
    );
    expect(
      await screen.findByText(
        missing === "apps" ? "No plugins found" : "provider unavailable"
      )
    ).toBeVisible();
    failRefresh = true;
    fireEvent.click(screen.getByText("Refresh apps"));
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Apps could not load")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
  }
);
