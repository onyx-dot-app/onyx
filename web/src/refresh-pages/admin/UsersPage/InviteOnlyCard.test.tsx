import React from "react";
import { render, screen, waitFor, userEvent } from "@tests/setup/test-utils";
import InviteOnlyCard from "./InviteOnlyCard";
import { Settings } from "@/interfaces/settings";

const baseSettings: Partial<Settings> = {
  invite_only_enabled: false,
};

const mockUseSettingsContext = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();
const mockMutate = jest.fn();
const mockUpdateAdminSettings = jest.fn();

jest.mock("@/providers/SettingsProvider", () => ({
  useSettingsContext: () => mockUseSettingsContext(),
}));

jest.mock("@/hooks/useToast", () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  mutate: (...args: unknown[]) => mockMutate(...args),
}));

jest.mock("@/lib/settings/svc", () => ({
  updateAdminSettings: (...args: unknown[]) => mockUpdateAdminSettings(...args),
}));

describe("InviteOnlyCard", () => {
  beforeEach(() => {
    mockUseSettingsContext.mockReturnValue({ settings: baseSettings });
    mockMutate.mockImplementation(async (_key, fn) => {
      if (typeof fn === "function") return fn();
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test("renders with copy and reflects current invite_only_enabled state", () => {
    render(<InviteOnlyCard />);
    expect(screen.getByText("Restrict Open Sign-Up")).toBeInTheDocument();
    expect(
      screen.getByText("New users must be invited to join this workspace.")
    ).toBeInTheDocument();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  test("reflects checked state when invite_only_enabled is true", () => {
    mockUseSettingsContext.mockReturnValue({
      settings: { ...baseSettings, invite_only_enabled: true },
    });
    render(<InviteOnlyCard />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  test("clicking switch calls updateAdminSettings with the merged payload", async () => {
    mockUpdateAdminSettings.mockResolvedValueOnce(undefined);

    const user = userEvent.setup();
    render(<InviteOnlyCard />);

    await user.click(screen.getByRole("switch"));

    await waitFor(() => {
      expect(mockUpdateAdminSettings).toHaveBeenCalledWith(
        expect.objectContaining({ invite_only_enabled: true })
      );
    });
    expect(mockToastSuccess).toHaveBeenCalledWith("Settings updated");
  });

  test("surfaces error message in toast when service throws", async () => {
    const consoleErrorSpy = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});

    mockUpdateAdminSettings.mockRejectedValueOnce(new Error("boom"));

    const user = userEvent.setup();
    render(<InviteOnlyCard />);

    await user.click(screen.getByRole("switch"));

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith("boom");
    });
    expect(consoleErrorSpy).toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });

  test("falls back to generic message when error has no message", async () => {
    const consoleErrorSpy = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});

    mockUpdateAdminSettings.mockRejectedValueOnce(new Error(""));

    const user = userEvent.setup();
    render(<InviteOnlyCard />);

    await user.click(screen.getByRole("switch"));

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith("Failed to update settings");
    });
    consoleErrorSpy.mockRestore();
  });
});
