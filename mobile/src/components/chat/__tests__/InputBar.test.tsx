import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { InputBar } from "@/components/chat/InputBar";
import type { UseComposerDraft } from "@/hooks/useComposerDraft";
import { ComposerToolsProvider } from "@/state/ComposerToolsProvider";
import { makeComposerTools } from "@/state/__tests__/fixtures";

jest.mock("@/state/storage");
jest.mock("@/api/settings", () => ({ useWorkspaceSettings: jest.fn() }));
jest.mock("@/hooks/useAgentPreferences", () => ({
  useAgentPreferences: jest.fn(),
}));
jest.mock("@/hooks/useRecentFiles", () => ({
  useRecentFiles: () => ({ data: [], isLoading: false }),
}));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

const attachments: UseComposerDraft = {
  text: "Hello",
  setText: jest.fn(),
  files: [],
  descriptors: [],
  hasBlockingFiles: false,
  addDocuments: async () => {},
  addImages: async () => {},
  addRecent: jest.fn(),
  removeFile: jest.fn(),
  consume: jest.fn(),
  consumeAttachments: jest.fn(),
};

function renderInputBar(toolsFailed: boolean, onRetryTools: () => void) {
  render(
    <ComposerToolsProvider value={makeComposerTools()}>
      <InputBar
        value="Hello"
        onChangeText={jest.fn()}
        onSend={jest.fn()}
        onStop={jest.fn()}
        chatState="input"
        attachments={attachments}
        toolsReady={false}
        toolsFailed={toolsFailed}
        onRetryTools={onRetryTools}
      />
    </ComposerToolsProvider>,
  );
}

describe("InputBar", () => {
  it("offers a retry while the action settings failed to load", () => {
    const onRetryTools = jest.fn();
    renderInputBar(true, onRetryTools);

    expect(screen.getByLabelText("Send")).toBeDisabled();
    fireEvent.press(screen.getByText("Retry"));
    expect(onRetryTools).toHaveBeenCalledTimes(1);
  });

  it("shows no retry while the action settings load", () => {
    renderInputBar(false, jest.fn());
    expect(screen.queryByText("Retry")).toBeNull();
  });
});
