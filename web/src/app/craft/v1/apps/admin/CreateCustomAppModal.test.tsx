/**
 * @jest-environment jsdom
 */

import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import * as externalAppsService from "@/app/craft/services/externalAppsService";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

const mockUseUserSkills = jest.fn();
const mockRouterPush = jest.fn();
const mockInspectSkillBundle = jest.fn();

jest.mock("@/app/craft/services/externalAppsService");
jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  inspectSkillBundle: (...args: unknown[]) => mockInspectSkillBundle(...args),
}));
jest.mock("@/sections/skills/SkillBundlePicker", () => ({
  __esModule: true,
  default: ({ onChange }: { onChange: (bundle: object) => void }) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          file: new File(["bundle"], "skill.zip"),
          displayName: "skill.zip",
          source: "zip",
        })
      }
    >
      Select bundle
    </button>
  ),
}));
jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => mockUseUserSkills(),
}));
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
  usePathname: () => "/admin/craft/apps",
}));

const CUSTOM_APP: ExternalAppAdminResponse = {
  id: 17,
  name: "Acme CRM",
  app_type: "CUSTOM",
  upstream_url_patterns: ["https://api.acme.test/*"],
  auth_template: {},
  organization_credentials: {},
  enabled: true,
  actions: [],
  associated_skills: [],
  is_onyx_managed: false,
};

function renderExistingApp({
  onClose = jest.fn(),
  onSaved = jest.fn(),
}: {
  onClose?: jest.Mock;
  onSaved?: jest.Mock;
} = {}) {
  const { unmount } = render(
    <CreateCustomAppModal
      onClose={onClose}
      onSaved={onSaved}
      existingApp={CUSTOM_APP}
    />
  );
  return { onClose, onSaved, unmount };
}

describe("CreateCustomAppModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockInspectSkillBundle.mockReset();
    mockUseUserSkills.mockReturnValue({
      data: { builtins: [], customs: [] },
      isLoading: false,
    });
  });

  it("focuses the name only when creating an app", () => {
    const { unmount } = renderExistingApp();
    expect(screen.getByPlaceholderText("My Custom App")).not.toHaveFocus();
    unmount();

    render(
      <CreateCustomAppModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        existingApp={null}
      />
    );
    expect(screen.getByPlaceholderText("My Custom App")).toHaveFocus();
  });

  it("persists the app before offering the optional skills step", async () => {
    const onClose = jest.fn();
    const onSaved = jest.fn();
    jest
      .mocked(externalAppsService.createCustomExternalApp)
      .mockResolvedValue(CUSTOM_APP);

    render(
      <CreateCustomAppModal
        onClose={onClose}
        onSaved={onSaved}
        existingApp={null}
      />
    );

    expect(screen.queryByText(/bundle/i)).not.toBeInTheDocument();
    const createButton = screen.getByRole("button", { name: "Create" });
    expect(createButton).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("My Custom App"), {
      target: { value: "Acme CRM" },
    });
    const patternInput = screen.getByPlaceholderText(
      "https://api.example.com/*"
    );
    fireEvent.change(patternInput, {
      target: { value: "https://api.acme.test/*" },
    });
    fireEvent.keyDown(patternInput, { key: "Enter", code: "Enter" });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Create" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(externalAppsService.createCustomExternalApp).toHaveBeenCalledWith({
        name: "Acme CRM",
        upstream_url_patterns: ["https://api.acme.test/*"],
        auth_template: {},
        organization_credentials: {},
      });
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Add skills to Acme CRM")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Associate existing" })
    ).toBeInTheDocument();

    const beforeUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(beforeUnload);
    expect(beforeUnload.defaultPrevented).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
  });

  it("confirms visibility promotion and batches association with app edits", async () => {
    const editableSkill = customFixture({
      id: "skill-a",
      name: "acme-lookup",
      description: "Looks up Acme records",
      enabled: false,
      author_user_id: "admin-id",
      author_email: "admin@example.com",
      owner: { id: "admin-id", email: "admin@example.com" },
      ownership_vacant: false,
      public_permission: null,
      is_personal: true,
      user_permission: "OWNER",
    });
    const otherAppSkill = customFixture({
      id: "other-app-skill",
      name: "other-app-skill",
      description: "Already used by another app",
      user_permission: "OWNER",
      external_app: {
        external_app_id: 99,
        name: "Other CRM",
        enabled: true,
        ready: true,
      },
    });
    mockUseUserSkills.mockReturnValue({
      data: {
        builtins: [],
        customs: [
          editableSkill,
          { ...editableSkill, id: "skill-b" },
          {
            ...editableSkill,
            id: "invalid-skill",
            name: "broken-skill",
            is_valid: false,
          },
          otherAppSkill,
        ],
      },
      isLoading: false,
    });
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue({
      ...CUSTOM_APP,
      associated_skills: [
        { id: "skill-a", name: "acme-lookup", is_valid: true },
      ],
    });

    const { onClose, onSaved } = renderExistingApp();

    const appModal = screen.getByRole("dialog", { name: /Edit Acme CRM/ });
    fireEvent.click(screen.getByRole("button", { name: "Associate existing" }));
    expect(appModal).not.toContainElement(
      screen.getByPlaceholderText("Search editable skills...")
    );
    fireEvent.click(screen.getAllByRole("button", { name: /acme-lookup/ })[0]!);
    expect(
      screen.getByText(
        "App-associated skills must be available to everyone. This change is applied when you save the app."
      )
    ).toBeInTheDocument();
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "Make organization-wide" })
    );
    fireEvent.click(screen.getByRole("button", { name: "Associate existing" }));
    const sameNamedSkills = screen.getAllByRole("button", {
      name: "Associate acme-lookup",
    });
    expect(sameNamedSkills).toHaveLength(2);
    const disabledSameNamedSkill = sameNamedSkills.find(
      (item) => item.getAttribute("aria-disabled") === "true"
    );
    expect(disabledSameNamedSkill).toHaveTextContent(
      "A skill named “acme-lookup” is already associated."
    );
    const invalidSkill = screen.getByRole("button", {
      name: "Associate broken-skill",
    });
    expect(invalidSkill).toHaveAttribute("aria-disabled", "true");
    expect(invalidSkill).toHaveTextContent(
      "Invalid skill — fix it before associating."
    );
    const otherAppAssociation = screen.getByRole("button", {
      name: "Associate other-app-skill",
    });
    expect(otherAppAssociation).toHaveAttribute("aria-disabled", "true");
    expect(otherAppAssociation).toHaveTextContent(
      "Already associated with app “Other CRM”."
    );
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(17, {
        name: "Acme CRM",
        upstream_url_patterns: ["https://api.acme.test/*"],
        auth_template: {},
        organization_credentials: {},
        associated_skill_ids: ["skill-a"],
      })
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("guards unsaved edits before skill creation without persisting them", () => {
    const { onClose, onSaved } = renderExistingApp();

    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Unsaved Acme CRM" },
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
      "/craft/v1/skills/new?externalAppId=17&externalAppName=Acme+CRM"
    );
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("warns before discarding dirty app settings", () => {
    const { onClose } = renderExistingApp();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Unsaved Acme CRM" },
    });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).not.toHaveBeenCalled();
    let confirmation = screen.getByRole("dialog", {
      name: "Discard unsaved changes?",
    });
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "Cancel" })
    );
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Unsaved Acme CRM")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Unsaved Acme CRM")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    confirmation = screen.getByRole("dialog", {
      name: "Discard unsaved changes?",
    });
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "Close" })
    );
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Unsaved Acme CRM")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
  });

  it("cannot discard an app edit while its save is in flight", async () => {
    const save = deferred<ExternalAppAdminResponse>();
    jest
      .mocked(externalAppsService.updateExternalApp)
      .mockReturnValue(save.promise);
    const { onClose } = renderExistingApp();
    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Updated Acme CRM" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledTimes(1)
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      save.resolve({ ...CUSTOM_APP, name: "Updated Acme CRM" });
      await save.promise;
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("restores unsaved app settings after upload is canceled", () => {
    const { onClose } = renderExistingApp();
    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Edited Acme CRM" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("button", { name: /^Upload a skill/ }));

    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    expect(screen.getByText("Upload skill")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByDisplayValue("Edited Acme CRM")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("preserves a selected upload when accidental close is canceled", () => {
    renderExistingApp();
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("button", { name: /^Upload a skill/ }));
    fireEvent.click(screen.getByRole("button", { name: "Select bundle" }));

    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.getByRole("dialog", { name: "Discard unsaved changes?" })
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Upload skill")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review skill" })).toBeEnabled();
  });

  it("returns to the uploaded draft when navigation is canceled", async () => {
    mockInspectSkillBundle.mockResolvedValue({
      name: "new-skill",
      description: "Uses Acme",
      instructions_markdown: "Use the Acme API.",
      files: [{ path: "SKILL.md", size: 64 }],
    });
    renderExistingApp();
    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Unsaved Acme CRM" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("button", { name: /^Upload a skill/ }));
    fireEvent.click(screen.getByRole("button", { name: "Select bundle" }));
    fireEvent.click(screen.getByRole("button", { name: "Review skill" }));

    const confirmation = await screen.findByRole("dialog", {
      name: "Discard unsaved changes?",
    });
    expect(mockRouterPush).not.toHaveBeenCalled();
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "Cancel" })
    );

    expect(screen.getByText("Upload skill")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Review skill" })).toBeEnabled()
    );
    expect(mockRouterPush).not.toHaveBeenCalled();
  });

  it("rejects an uploaded skill whose name is already associated", async () => {
    mockInspectSkillBundle.mockResolvedValue({
      name: "hubspot-crm",
      description: "Uses HubSpot",
      instructions_markdown: "Use the HubSpot API.",
      files: [{ path: "SKILL.md", size: 64 }],
    });
    render(
      <CreateCustomAppModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        existingApp={{
          ...CUSTOM_APP,
          associated_skills: [
            { id: "existing-skill", name: "hubspot-crm", is_valid: true },
          ],
        }}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("button", { name: /^Upload a skill/ }));
    fireEvent.click(screen.getByRole("button", { name: "Select bundle" }));
    fireEvent.click(screen.getByRole("button", { name: "Review skill" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "App “Acme CRM” already has an associated skill named “hubspot-crm”. Upload a skill with a different name."
    );
    expect(mockRouterPush).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Review skill" })).toBeEnabled();
  });

  it("preserves the draft and displays a newly persisted association", async () => {
    const props = {
      onClose: jest.fn(),
      onSaved: jest.fn(),
      existingApp: CUSTOM_APP,
    };
    const { rerender } = render(<CreateCustomAppModal {...props} />);
    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Unsaved Acme CRM" },
    });

    rerender(
      <CreateCustomAppModal
        {...props}
        existingApp={{
          ...CUSTOM_APP,
          associated_skills: [
            { id: "new-skill", name: "newly-created", is_valid: true },
          ],
        }}
      />
    );

    expect(screen.getByDisplayValue("Unsaved Acme CRM")).toBeInTheDocument();
    expect(await screen.findByText("newly-created")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("does not overwrite a pending association when app data refreshes", async () => {
    const pendingSkill = customFixture({
      id: "pending-skill",
      name: "pending-skill",
      description: "Selected locally",
      public_permission: "VIEWER",
      is_personal: false,
      user_permission: "OWNER",
    });
    mockUseUserSkills.mockReturnValue({
      data: { builtins: [], customs: [pendingSkill] },
      isLoading: false,
    });
    const props = {
      onClose: jest.fn(),
      onSaved: jest.fn(),
      existingApp: CUSTOM_APP,
    };
    const { rerender } = render(<CreateCustomAppModal {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Associate existing" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Associate pending-skill" })
    );
    expect(screen.getByText("pending-skill")).toBeInTheDocument();

    rerender(
      <CreateCustomAppModal
        {...props}
        existingApp={{
          ...CUSTOM_APP,
          associated_skills: [
            { id: "server-skill", name: "server-skill", is_valid: true },
          ],
        }}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(
        CUSTOM_APP.id,
        expect.objectContaining({
          associated_skill_ids: ["pending-skill"],
        })
      )
    );
  });
});
