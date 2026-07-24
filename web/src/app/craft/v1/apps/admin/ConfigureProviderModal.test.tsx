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

const mockRouterPush = jest.fn();

jest.mock("@/app/craft/services/externalAppsService");
jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => ({
    data: { builtins: [], customs: [] },
    isLoading: false,
  }),
}));
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
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

function renderExistingProvider(onClose = jest.fn()) {
  render(
    <ConfigureProviderModal
      onClose={onClose}
      onSaved={jest.fn()}
      descriptor={DESCRIPTOR}
      existingApp={APP}
    />
  );
  return { onClose };
}

describe("ConfigureProviderModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("saves built-in app settings and custom associations together", async () => {
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue(APP);
    const { onClose } = renderExistingProvider();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "updated-token" },
    });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(7, {
        name: "Slack",
        upstream_url_patterns: ["https://slack.com/api/.*"],
        auth_template: { Authorization: "Bearer {token}" },
        action_policies: {},
        organization_credentials: { token: "updated-token" },
        associated_skill_ids: ["custom-skill"],
      })
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("guards unsaved provider edits before skill creation", () => {
    const { onClose } = renderExistingProvider();
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "unsaved-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(
      screen.getByRole("button", { name: /^Start from scratch/ })
    );

    expect(mockRouterPush).not.toHaveBeenCalled();
    expect(
      screen.getByRole("dialog", { name: "Discard unsaved changes?" })
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(mockRouterPush).toHaveBeenCalledWith(
      "/craft/v1/skills/new?externalAppId=7&externalAppName=Slack"
    );
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("restores unsaved provider settings after upload is canceled", () => {
    const { onClose } = renderExistingProvider();
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "updated-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("button", { name: /^Upload a skill/ }));

    expect(screen.getByText("Upload skill")).toBeInTheDocument();
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("dialog", { name: /Edit Slack/ })).toBeVisible();
    expect(screen.getByPlaceholderText("Token")).toHaveValue("updated-token");
    expect(onClose).not.toHaveBeenCalled();
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
    expect(screen.getByRole("button", { name: "Save skills" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});
