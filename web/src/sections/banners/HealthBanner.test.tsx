import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import HealthBanner from "@/sections/banners/HealthBanner";

const mockUseSWR = jest.fn();

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  default: (...args: unknown[]) => mockUseSWR(...args),
}));

describe("HealthBanner", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSWR.mockReturnValue({ error: undefined });
  });

  it("renders nothing when the backend is healthy", () => {
    const { container } = render(<HealthBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the unavailable banner on a health error", () => {
    mockUseSWR.mockReturnValue({ error: new Error("network error") });
    render(<HealthBanner />);
    expect(
      screen.getByText(/the backend is currently unavailable/i)
    ).toBeInTheDocument();
  });
});
