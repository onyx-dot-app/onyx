/** @jest-environment jsdom */

import { render, screen, setupUser } from "@tests/setup/test-utils";
import OpenAPIAuthenticationModal from "@/sections/actions/modals/OpenAPIAuthenticationModal";

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));
jest.mock("@/lib/auth/hooks", () => ({
  useOAuthPassThroughEnabled: () => true,
}));

describe("OpenAPIAuthenticationModal", () => {
  it.each([
    { initialHeaders: null, passthroughOAuthEnabled: false, selected: "OAuth" },
    {
      initialHeaders: [{ key: "Authorization", value: "Bearer token" }],
      passthroughOAuthEnabled: false,
      selected: "Custom Authorization Header",
    },
    {
      initialHeaders: null,
      passthroughOAuthEnabled: true,
      selected: "OAuth Pass-through",
    },
  ])(
    "preserves $selected and offers all authentication methods",
    async ({ initialHeaders, passthroughOAuthEnabled, selected }) => {
      const user = setupUser();
      render(
        <OpenAPIAuthenticationModal
          isOpen
          onClose={jest.fn()}
          title="Configure authentication"
          initialHeaders={initialHeaders}
          passthroughOAuthEnabled={passthroughOAuthEnabled}
        />
      );

      const select = screen.getByRole("combobox");
      expect(select).toHaveValue(selected);
      await user.click(select);
      for (const option of screen.getAllByRole("option", { name: /OAuth/ })) {
        expect(option).not.toHaveAttribute("aria-disabled", "true");
      }
    }
  );
});
