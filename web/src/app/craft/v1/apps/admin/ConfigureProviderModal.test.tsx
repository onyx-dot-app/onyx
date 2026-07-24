/**
 * @jest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import type {
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import * as externalAppsService from "@/app/craft/services/externalAppsService";

jest.mock("@/app/craft/services/externalAppsService");
jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => ({
    data: { builtins: [], customs: [] },
    isLoading: false,
  }),
}));
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => "/admin/craft/apps",
}));

const DESCRIPTOR: BuiltInExternalAppDescriptor = {
  app_type: "SLACK",
  name: "Slack",
  upstream_url_patterns: ["https://slack.com/api/.*"],
  auth_template: { Authorization: "Bearer {token}" },
  required_org_credential_fields: [
    {
      key: "token",
      label: "Token",
      description: "Slack organization token",
      secret: true,
    },
  ],
  setup_instructions: "Configure Slack.",
  actions: [],
};

const APP: ExternalAppAdminResponse = {
  id: 7,
  name: "Slack",
  app_type: "SLACK",
  upstream_url_patterns: DESCRIPTOR.upstream_url_patterns,
  auth_template: DESCRIPTOR.auth_template,
  organization_credentials: { token: "masked-token" },
  enabled: true,
  actions: [],
  associated_skills: [
    { id: "custom-skill", name: "slack-workflow", is_valid: true },
  ],
  is_onyx_managed: false,
};

describe("ConfigureProviderModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("saves built-in app settings and custom associations together", async () => {
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue(APP);
    const onClose = jest.fn();

    render(
      <ConfigureProviderModal
        onClose={onClose}
        onSaved={jest.fn()}
        descriptor={DESCRIPTOR}
        existingApp={APP}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(7, {
        name: "Slack",
        upstream_url_patterns: ["https://slack.com/api/.*"],
        auth_template: { Authorization: "Bearer {token}" },
        action_policies: {},
        organization_credentials: { token: "masked-token" },
        associated_skill_ids: ["custom-skill"],
      })
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps a newly created provider durable while skills are skipped", async () => {
    jest
      .mocked(externalAppsService.createBuiltInExternalApp)
      .mockResolvedValue({ ...APP, associated_skills: [] });
    const onClose = jest.fn();

    render(
      <ConfigureProviderModal
        onClose={onClose}
        onSaved={jest.fn()}
        descriptor={DESCRIPTOR}
        existingApp={null}
      />
    );
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "org-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByText("Add skills to Slack")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
