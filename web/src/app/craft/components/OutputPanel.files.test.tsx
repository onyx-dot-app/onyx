import { act, fireEvent, render, screen } from "@tests/setup/test-utils";
import BuildOutputPanel from "@/app/craft/components/OutputPanel";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import {
  fetchDirectoryListing,
  fetchFileContent,
} from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchDirectoryListing: jest.fn(),
  fetchFileContent: jest.fn(),
  fetchWebappInfo: jest
    .fn()
    .mockResolvedValue({ has_webapp: false, ready: false }),
}));

it.each([false, true])(
  "reloads the welcome inline file and releases the toolbar (after handoff: %s)",
  async (afterHandoff) => {
    const sessionId = `inline-refresh-${afterHandoff}`;
    const store = () => useBuildSessionStore.getState();
    useBuildSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
      preProvisioning: { status: "ready", sessionId },
    });
    store().createSession(sessionId);
    jest.mocked(fetchDirectoryListing).mockResolvedValue({
      path: "",
      entries: [
        {
          name: "notes.txt",
          path: "outputs/notes.txt",
          is_directory: false,
          size: 10,
          mime_type: "text/plain",
        },
      ],
    });
    jest.mocked(fetchFileContent).mockResolvedValue({
      content: "Before refresh",
      isImage: false,
      mimeType: "text/plain",
    });
    render(<BuildOutputPanel isOpen />);
    fireEvent.click(await screen.findByRole("button", { name: /notes.txt/ }));
    expect(await screen.findByText("Before refresh")).toBeInTheDocument();
    if (afterHandoff) act(() => store().setCurrentSession(sessionId));
    jest.mocked(fetchFileContent).mockResolvedValue({
      content: "After refresh",
      isImage: false,
      mimeType: "text/plain",
    });
    const readsBefore = jest.mocked(fetchFileContent).mock.calls.length;
    await act(async () => store().triggerFilesRefresh(sessionId));
    expect(fetchFileContent).toHaveBeenCalledTimes(readsBefore);
    expect(screen.getByText("Before refresh")).toBeInTheDocument();
    const refresh = screen.getByRole("button", { name: "Refresh" });
    fireEvent.click(refresh);
    expect(await screen.findByText("After refresh")).toBeInTheDocument();
    expect(refresh).toBeEnabled();
    expect(refresh).toHaveAttribute("aria-busy", "false");
  }
);
