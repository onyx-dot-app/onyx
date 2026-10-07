import { StrictMode } from "react";
import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import {
  OpenSearchResourceBanner,
  OpenSearchResourcePopup,
} from "@/sections/banners/OpenSearchResourceWarning";
import type {
  ResourceHealth,
  ResourcePopupResponse,
} from "@/lib/opensearch-health/types";

let mockAdminId: string | null = "admin-one";
let mockPathname = "/app";
jest.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    isAdmin: !!mockAdminId,
    user: mockAdminId ? { id: mockAdminId } : null,
  }),
}));

const unhealthy: ResourceHealth = {
  checked_at: "2026-10-07T00:00:00Z",
  issues: ["disk", "jvm_memory"],
  stale: false,
};

function jsonResponse(body: ResourceHealth | ResourcePopupResponse): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
}

function Alerts() {
  return (
    <StrictMode>
      <OpenSearchResourcePopup />
      <OpenSearchResourceBanner />
    </StrictMode>
  );
}

beforeEach(() => {
  mockAdminId = "admin-one";
  mockPathname = "/app";
});

test("waits for the login redirect before claiming the daily popup", async () => {
  mockPathname = "/auth/login";
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse({ show_popup: true, health: unhealthy }));
  const { rerender } = render(<OpenSearchResourcePopup />);
  expect(fetchSpy).not.toHaveBeenCalled();
  mockPathname = "/app";
  rerender(<OpenSearchResourcePopup />);
  await screen.findByRole("dialog");
  expect(fetchSpy).toHaveBeenCalledTimes(1);
});

afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
});

test("the banner retries failed cache reads and clears after recovery", async () => {
  jest.useFakeTimers();
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(jsonResponse(unhealthy))
    .mockResolvedValueOnce(new Response("{}", { status: 503 }))
    .mockResolvedValueOnce(jsonResponse({ ...unhealthy, issues: [] }));
  render(<OpenSearchResourceBanner />, {
    swrConfig: { shouldRetryOnError: true },
  });
  await screen.findByRole("status");
  await act(async () => {
    await jest.advanceTimersByTimeAsync(5 * 60 * 1000);
  });
  expect(
    screen.getByText(/recovery has not been confirmed/)
  ).toBeInTheDocument();
  await act(async () => {
    await jest.advanceTimersByTimeAsync(5 * 60 * 1000);
  });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledTimes(3);
});

test("dismisses the entry popup while keeping the admin banner and avoids repeat requests", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) =>
      jsonResponse(
        init?.method === "POST"
          ? { show_popup: true, health: unhealthy }
          : unhealthy
      )
    );
  const user = setupUser();
  const { rerender } = render(<Alerts />);
  const popup = await screen.findByRole("dialog");
  expect(within(popup).getByText(/disk usage/)).toBeInTheDocument();
  expect(within(popup).getByText(/JVM memory usage/)).toBeInTheDocument();
  expect(
    within(popup).getByRole("link", { name: "support@onyx.app" })
  ).toHaveAttribute("href", "mailto:support@onyx.app");
  await user.click(within(popup).getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("status")).getByText(/disk usage/)
  ).toBeInTheDocument();
  rerender(<Alerts />);
  expect(
    fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST")
  ).toHaveLength(1);
});

test("honors the server daily limit and keeps a stale warning visible", async () => {
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) =>
      jsonResponse(
        init?.method === "POST"
          ? { show_popup: false, health: unhealthy }
          : { ...unhealthy, stale: true }
      )
    );
  render(<Alerts />);
  expect(
    await screen.findByText(/recovery has not been confirmed/)
  ).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("status")).queryByRole("button")
  ).not.toBeInTheDocument();
});

test("does not request health or show warnings for non-admins", () => {
  mockAdminId = null;
  const fetchSpy = jest.spyOn(global, "fetch");
  render(<Alerts />);
  expect(fetchSpy).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("checks again for a different admin without showing the previous admin's popup", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(
      jsonResponse({ show_popup: true, health: unhealthy })
    )
    .mockResolvedValueOnce(
      jsonResponse({ show_popup: false, health: unhealthy })
    );
  const { rerender } = render(<OpenSearchResourcePopup />);
  await screen.findByRole("dialog");
  mockAdminId = "admin-two";
  rerender(<OpenSearchResourcePopup />);
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("healthy status displays neither banner nor popup", async () => {
  const healthy: ResourceHealth = { ...unhealthy, issues: [] };
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) =>
      jsonResponse(
        init?.method === "POST"
          ? { show_popup: false, health: healthy }
          : healthy
      )
    );
  render(<Alerts />);
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
