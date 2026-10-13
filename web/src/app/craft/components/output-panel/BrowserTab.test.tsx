import { fireEvent } from "@testing-library/react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import BrowserTab from "@/app/craft/components/output-panel/BrowserTab";
import type { RegisteredWebapp } from "@/lib/build/types";

const apps: RegisteredWebapp[] = [
  {
    id: "app",
    name: "Report app",
    url: "/api/build/sessions/session/webapp",
    state: "ready",
  },
];

test("opens the selected registered app from its home tile", async () => {
  const user = setupUser();
  const onNavigate = jest.fn();
  render(
    <BrowserTab
      resourceId="browser"
      apps={apps}
      appId={null}
      discoveryState="ready"
      onNavigate={onNavigate}
    />
  );
  await user.click(screen.getByRole("button", { name: "Report app" }));
  expect(onNavigate).toHaveBeenCalledWith("app");
});

test("retains the app frame through discovery failure and allows return home", async () => {
  const user = setupUser();
  const onNavigate = jest.fn();
  const props = {
    apps,
    appId: "app",
    discoveryState: "ready" as const,
    onNavigate,
  };
  const { rerender } = render(<BrowserTab resourceId="browser" {...props} />);
  const frame = screen.getByTitle("Report app");
  fireEvent.load(frame);
  rerender(
    <BrowserTab
      resourceId="browser"
      {...props}
      apps={[]}
      discoveryState="failed"
    />
  );
  expect(screen.getByTitle("Report app")).toBe(frame);
  expect(frame).toHaveAttribute("inert");
  expect(frame).toHaveAttribute("aria-hidden", "true");
  await user.click(screen.getByRole("button", { name: "Apps" }));
  expect(onNavigate).toHaveBeenCalledWith(null);
});

test("does not report an empty successful discovery after a failure", () => {
  render(
    <BrowserTab
      resourceId="browser"
      apps={[]}
      appId={null}
      discoveryState="failed"
      onNavigate={jest.fn()}
    />
  );
  expect(screen.queryByText("No webapps available")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Could not check local webapps"
  );
});

test("keeps the app frame mounted while navigating home and back", () => {
  const props = {
    apps,
    appId: "app",
    discoveryState: "ready" as const,
    onNavigate: jest.fn(),
  };
  const { rerender } = render(<BrowserTab resourceId="browser" {...props} />);
  const frame = screen.getByTitle("Report app");
  fireEvent.load(frame);
  rerender(<BrowserTab resourceId="browser" {...props} appId={null} />);
  expect(screen.getByTitle("Report app")).toBe(frame);
  expect(frame).toHaveAttribute("inert");
  rerender(<BrowserTab resourceId="browser" {...props} />);
  expect(screen.getByTitle("Report app")).toBe(frame);
  expect(frame).not.toHaveAttribute("inert");
});

test("releases the app frame when session access is revoked", () => {
  const props = {
    apps,
    appId: "app",
    discoveryState: "ready" as const,
    onNavigate: jest.fn(),
    onLoadingChange: jest.fn(),
  };
  const { rerender } = render(<BrowserTab resourceId="browser" {...props} />);
  expect(screen.getByTitle("Report app")).toBeInTheDocument();
  expect(props.onLoadingChange).toHaveBeenLastCalledWith("browser", true);
  rerender(
    <BrowserTab
      resourceId="browser"
      {...props}
      apps={[]}
      discoveryState="unavailable"
      accessRevoked
    />
  );
  expect(screen.queryByTitle("Report app")).not.toBeInTheDocument();
  expect(props.onLoadingChange).toHaveBeenLastCalledWith("browser", false);
  rerender(
    <BrowserTab
      resourceId="browser"
      {...props}
      apps={[]}
      discoveryState="unavailable"
      accessRevoked={false}
    />
  );
  expect(screen.queryByTitle("Report app")).not.toBeInTheDocument();
});

// Navigation identity
test("requires a fresh load when returning before another app loads", () => {
  const secondApp = {
    id: "second",
    name: "Second app",
    url: "/second",
    state: "ready" as const,
  };
  const props = {
    resourceId: "browser",
    apps: [...apps, secondApp],
    discoveryState: "ready" as const,
    onNavigate: jest.fn(),
    onLoadingChange: jest.fn(),
  };
  const { rerender } = render(<BrowserTab {...props} appId="app" />);
  fireEvent.load(screen.getByTitle("Report app"));
  expect(props.onLoadingChange).toHaveBeenLastCalledWith("browser", false);
  rerender(<BrowserTab {...props} appId="second" />);
  rerender(<BrowserTab {...props} appId="app" />);
  const frame = screen.getByTitle("Report app");
  expect(frame).toHaveAttribute("inert");
  expect(props.onLoadingChange).toHaveBeenLastCalledWith("browser", true);
  fireEvent.load(frame);
  expect(frame).not.toHaveAttribute("inert");
  expect(props.onLoadingChange).toHaveBeenLastCalledWith("browser", false);
});

test("keeps reload pending through frame replacement and clears it on tab removal", () => {
  const onLoadingChange = jest.fn();
  const props = {
    resourceId: "browser",
    apps,
    appId: "app",
    discoveryState: "ready" as const,
    onNavigate: jest.fn(),
    onLoadingChange,
  };
  const { rerender, unmount } = render(<BrowserTab {...props} />);
  fireEvent.load(screen.getByTitle("Report app"));
  onLoadingChange.mockClear();
  rerender(<BrowserTab {...props} refreshKey={1} />);
  expect(onLoadingChange.mock.calls).toEqual([["browser", true]]);
  unmount();
  expect(onLoadingChange).toHaveBeenLastCalledWith("browser", false);
});

// Accepted frame identity
test("keeps the accepted URL until a replacement reports readiness", () => {
  const props = {
    resourceId: "browser",
    apps,
    appId: "app",
    discoveryState: "ready" as const,
    onNavigate: jest.fn(),
  };
  const { rerender } = render(<BrowserTab {...props} />);
  const accepted = screen.getByTitle("Report app");
  fireEvent.load(accepted);
  const replacement: RegisteredWebapp = {
    id: "app",
    name: "Report app",
    url: "/replacement",
    state: "starting",
  };
  rerender(<BrowserTab {...props} apps={[replacement]} />);
  expect(screen.getByTitle("Report app")).toBe(accepted);
  expect(accepted).toHaveAttribute("src", "/api/build/sessions/session/webapp");
  expect(accepted).toHaveAttribute("inert");
  rerender(
    <BrowserTab {...props} apps={[{ ...replacement, state: "ready" }]} />
  );
  const updated = screen.getByTitle("Report app");
  expect(updated).not.toBe(accepted);
  expect(updated).toHaveAttribute("src", "/replacement");
  expect(updated).toHaveAttribute("inert");
  fireEvent.load(updated);
  expect(updated).not.toHaveAttribute("inert");
});

test("does not clear an in-flight frame reload when the reporting callback changes", () => {
  const onLoadingChange = jest.fn();
  const props = {
    resourceId: "browser",
    apps,
    appId: "app",
    discoveryState: "ready" as const,
    onNavigate: jest.fn(),
  };
  const { rerender, unmount } = render(
    <BrowserTab {...props} onLoadingChange={onLoadingChange} />
  );
  expect(onLoadingChange).toHaveBeenLastCalledWith("browser", true);
  onLoadingChange.mockClear();
  const nextCallback = jest.fn();
  rerender(<BrowserTab {...props} onLoadingChange={nextCallback} />);
  expect(onLoadingChange).not.toHaveBeenCalled();
  expect(nextCallback).not.toHaveBeenCalled();
  fireEvent.load(screen.getByTitle("Report app"));
  expect(nextCallback).toHaveBeenLastCalledWith("browser", false);
  nextCallback.mockClear();
  unmount();
  expect(nextCallback).toHaveBeenCalledWith("browser", false);
});
