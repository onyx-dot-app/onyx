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

describe("InviteOnlyCard", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest.spyOn(global, "fetch");
    mockUseSettingsContext.mockReturnValue({ settings: baseSettings });
    mockMutate.mockImplementation(async (_key, fn) => {
      if (typeof fn === "function") return fn();
    });
  });

  afterEach(() => {
    fetchSpy.mockRestore();
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

  test("clicking switch PUTs /api/admin/settings with invite_only_enabled toggled", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    const user = userEvent.setup();
    render(<InviteOnlyCard />);

    await user.click(screen.getByRole("switch"));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/settings",
        expect.objectContaining({
          method: "PUT",
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    const callArgs = fetchSpy.mock.calls[0];
    const body = JSON.parse(callArgs[1].body as string);
    expect(body.invite_only_enabled).toBe(true);
    expect(mockToastSuccess).toHaveBeenCalledWith("Settings updated");
  });

  test("shows error toast when PUT fails", async () => {
    const consoleErrorSpy = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: "boom" }),
    } as Response);

    const user = userEvent.setup();
    render(<InviteOnlyCard />);

    await user.click(screen.getByRole("switch"));

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith("boom");
    });
    expect(consoleErrorSpy).toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });

  test("falls back to generic message when error has no detail", async () => {
    const consoleErrorSpy = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      json: async () => ({}),
    } as Response);

    const user = userEvent.setup();
    render(<InviteOnlyCard />);

    await user.click(screen.getByRole("switch"));

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith("Request failed");
    });
    consoleErrorSpy.mockRestore();
  });
});
