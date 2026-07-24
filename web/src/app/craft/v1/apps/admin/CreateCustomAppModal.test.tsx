/**
 * @jest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import * as externalAppsService from "@/app/craft/services/externalAppsService";

jest.mock("@/app/craft/services/externalAppsService");

describe("CreateCustomAppModal", () => {
  it("creates a custom app without asking for a skill bundle", async () => {
    const onClose = jest.fn();
    const onSaved = jest.fn();
    jest.mocked(externalAppsService.createCustomExternalApp).mockResolvedValue({
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
    });

    render(
      <CreateCustomAppModal
        open
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
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
