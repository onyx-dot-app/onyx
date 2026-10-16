/** @jest-environment jsdom */
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import OpenApiAppPolicyModal from "@/app/craft/v1/apps/admin/OpenApiAppPolicyModal";
import { updateExternalApp } from "@/app/craft/services/externalAppsService";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  usePathname: () => "/admin/craft/apps",
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("@/app/craft/services/externalAppsService", () => ({
  updateExternalApp: jest.fn(),
}));
const app: ExternalAppAdminResponse = {
  id: 7,
  openapi_tool_id: 42,
  name: "API",
  app_type: "CUSTOM",
  available_in_craft: true,
  enabled: true,
  upstream_url_patterns: [],
  auth_template: {},
  organization_credentials: {},
  credential_placeholder_keys: [],
  associated_skills: [],
  is_onyx_managed: false,
  actions: [
    {
      action_id: "GET https://example.com/api/items",
      normalised_name: "listItems",
      description: "List items",
      method: "GET",
      path: "/items",
      state: "ASK",
    },
    {
      action_id: "POST https://example.com/api/items",
      normalised_name: "createItem",
      description: "Create item",
      method: "POST",
      path: "/items",
      state: "ALWAYS",
    },
  ],
};
function policyRow(name: string) {
  const row = screen.getByText(name).parentElement?.parentElement;
  if (!row) throw new Error("Missing policy row");
  return within(row);
}

it("saves only changed policies using the server action ID", async () => {
  const user = setupUser();
  const onChanged = jest.fn();
  const onClose = jest.fn();
  render(
    <OpenApiAppPolicyModal app={app} onChanged={onChanged} onClose={onClose} />
  );
  expect(policyRow("listItems").getByText(/GET \/items/)).toBeInTheDocument();
  await user.click(
    policyRow("listItems").getByRole("button", { name: "Deny" })
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(updateExternalApp).toHaveBeenCalledWith(7, {
      action_policies: { "GET https://example.com/api/items": "DENY" },
    })
  );
  expect(onChanged).toHaveBeenCalledTimes(1);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("explains how to repair an empty operation catalog", () => {
  render(
    <OpenApiAppPolicyModal
      app={{ ...app, actions: [] }}
      onChanged={jest.fn()}
      onClose={jest.fn()}
    />
  );
  expect(
    screen.getByText(
      "No API operations are available. Check the configuration under Manage OpenAPI app."
    )
  ).toBeInTheDocument();
});

it("does not replace the open draft baseline during background refresh", () => {
  const props = { onChanged: jest.fn(), onClose: jest.fn() };
  const { rerender } = render(<OpenApiAppPolicyModal app={app} {...props} />);
  rerender(
    <OpenApiAppPolicyModal
      app={{
        ...app,
        actions: app.actions.map((action) => ({ ...action, state: "DENY" })),
      }}
      {...props}
    />
  );
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(
    policyRow("listItems").getByRole("button", { name: "Ask" })
  ).toHaveAttribute("aria-pressed", "true");
});
