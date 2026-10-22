import { FetchError } from "@/lib/fetcher";
import { act, render, screen, waitFor } from "@tests/setup/test-utils";
import { SWRConfig } from "swr";
import HtmlFilePreview from "@/app/craft/components/output-panel/HtmlFilePreview";
import { createStaticPreview } from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices", () => ({
  createStaticPreview: jest.fn(),
  downloadArtifactFile: jest.fn(),
}));

test("loads a scoped document URL with an opaque sandbox origin", async () => {
  const url = "/api/build/static-preview/token/index.html";
  jest.mocked(createStaticPreview).mockResolvedValue({
    url,
    token: "token",
    expiresAt: Date.now() + 3600_000,
  });
  const { rerender } = render(
    <SWRConfig value={{ provider: () => new Map() }}>
      <HtmlFilePreview sessionId="session" filePath="outputs/site/index.html" />
    </SWRConfig>
  );
  const frame = await screen.findByTitle("index.html");
  expect(frame).toHaveAttribute("src", url);
  expect(frame).not.toHaveAttribute("srcdoc");
  expect(frame).toHaveAttribute("sandbox", "allow-scripts");
  expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
  expect(createStaticPreview).toHaveBeenCalledWith(
    "session",
    "outputs/site/index.html"
  );
  const refreshedUrl = "/api/build/static-preview/new-token/index.html";
  jest.mocked(createStaticPreview).mockResolvedValue({
    url: refreshedUrl,
    token: "token",
    expiresAt: Date.now() + 3600_000,
  });
  rerender(
    <SWRConfig value={{ provider: () => new Map() }}>
      <HtmlFilePreview
        sessionId="session"
        filePath="outputs/site/index.html"
        refreshKey={1}
      />
    </SWRConfig>
  );
  await waitFor(() =>
    expect(screen.getByTitle("index.html")).toHaveAttribute("src", refreshedUrl)
  );
});

test.each([
  new Error("Network unavailable"),
  new FetchError("Service unavailable", 503, null),
])(
  "retains the accepted frame after a transient refresh failure: %s",
  async (error) => {
    const cache = new Map();
    const view = (refreshKey: number) => (
      <SWRConfig value={{ provider: () => cache }}>
        <HtmlFilePreview
          sessionId="refresh"
          filePath="outputs/site/index.html"
          refreshKey={refreshKey}
        />
      </SWRConfig>
    );
    jest.mocked(createStaticPreview).mockResolvedValue({
      url: "/api/build/static-preview/token/index.html",
      token: "token",
      expiresAt: Date.now() + 3600_000,
    });
    const { rerender } = render(view(0));
    const frame = await screen.findByTitle("index.html");
    jest.mocked(createStaticPreview).mockRejectedValue(error);
    rerender(view(1));
    await screen.findByRole("alert");
    expect(screen.getByTitle("index.html")).toBe(frame);
    expect(frame).toHaveAttribute(
      "src",
      "/api/build/static-preview/token/index.html"
    );

    jest
      .mocked(createStaticPreview)
      .mockRejectedValue(new FetchError("Forbidden", 403, null));
    rerender(view(2));
    await waitFor(() =>
      expect(screen.queryByTitle("index.html")).not.toBeInTheDocument()
    );
  }
);

test.each([true, false])(
  "renews retained capabilities with isActive=%s",
  async (isActive) => {
    jest.useFakeTimers();
    try {
      const url = "/api/build/static-preview/stable-token/index.html";
      jest
        .mocked(createStaticPreview)
        .mockResolvedValueOnce({
          url,
          token: "stable-token",
          expiresAt: Date.now() + 61_000,
        })
        .mockImplementation(async () => ({
          url,
          token: "stable-token",
          expiresAt: Date.now() + 3600_000,
        }));
      render(
        <SWRConfig value={{ provider: () => new Map() }}>
          <HtmlFilePreview
            sessionId="renew"
            filePath="outputs/site/index.html"
            isActive={isActive}
          />
        </SWRConfig>
      );
      const frame = await screen.findByTitle("index.html");
      for (const elapsed of [1000, 3540_000, 60_000]) {
        await act(async () => {
          await jest.advanceTimersByTimeAsync(elapsed);
        });
      }
      expect(createStaticPreview).toHaveBeenLastCalledWith(
        "renew",
        "outputs/site/index.html",
        "stable-token"
      );
      expect(screen.getByTitle("index.html")).toBe(frame);
      expect(frame).toHaveAttribute("src", url);
    } finally {
      jest.useRealTimers();
    }
  }
);

test("requests a fresh grant when browser suspension outlasts expiry", async () => {
  jest.useFakeTimers();
  try {
    const url = "/api/build/static-preview/old-token/index.html";
    jest
      .mocked(createStaticPreview)
      .mockResolvedValueOnce({
        url,
        token: "old-token",
        expiresAt: Date.now() + 61_000,
      })
      .mockImplementation(async () => ({
        url: "/api/build/static-preview/new-token/index.html",
        token: "new-token",
        expiresAt: Date.now() + 3600_000,
      }));
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <HtmlFilePreview
          sessionId="suspend"
          filePath="outputs/site/index.html"
        />
      </SWRConfig>
    );
    await screen.findByTitle("index.html");
    jest.setSystemTime(Date.now() + 2 * 3600_000);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(createStaticPreview).toHaveBeenLastCalledWith(
      "suspend",
      "outputs/site/index.html"
    );
    expect(screen.getByTitle("index.html")).toHaveAttribute(
      "src",
      "/api/build/static-preview/new-token/index.html"
    );
  } finally {
    jest.useRealTimers();
  }
});
