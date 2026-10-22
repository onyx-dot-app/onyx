import { render, screen, waitFor } from "@tests/setup/test-utils";
import { SWRConfig } from "swr";
import HtmlFilePreview from "@/app/craft/components/output-panel/HtmlFilePreview";
import { createStaticPreview } from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices", () => ({
  createStaticPreview: jest.fn(),
  downloadArtifactFile: jest.fn(),
}));

test("loads a scoped document URL with an opaque sandbox origin", async () => {
  const url = "/api/build/static-preview/token/index.html";
  jest
    .mocked(createStaticPreview)
    .mockResolvedValue({ url, expiresAt: Date.now() + 3600_000 });
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
  jest
    .mocked(createStaticPreview)
    .mockResolvedValue({ url: refreshedUrl, expiresAt: Date.now() + 3600_000 });
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
