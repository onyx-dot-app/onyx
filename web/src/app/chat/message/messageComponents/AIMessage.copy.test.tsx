import React from "react";
import { render, screen } from "@testing-library/react";

import AIMessage from "./AIMessage";
import { Packet, PacketType } from "@/app/chat/services/streamingModels";
import { FullChatState } from "./interfaces";

let lastCopyProps: any = null;

jest.mock("@/app/chat/message/copyingUtils", () => ({
  __esModule: true,
  handleCopy: jest.fn(),
  convertMarkdownTablesToTsv: (content: string) => content,
}));

jest.mock("@/refresh-components/buttons/CopyIconButton", () => ({
  __esModule: true,
  default: (props: any) => {
    lastCopyProps = props;
    return <button data-testid="mock-copy-button" />;
  },
}));

jest.mock("@/app/chat/message/messageComponents/MultiToolRenderer", () => ({
  __esModule: true,
  default: () => <div>3 steps</div>,
}));

jest.mock(
  "@/app/chat/message/messageComponents/renderMessageComponent",
  () => ({
    __esModule: true,
    RendererComponent: ({ children }: any) =>
      children({
        icon: null,
        status: null,
        content: <div>FINAL ANSWER</div>,
      }),
  })
);

jest.mock("@/refresh-components/avatars/AgentAvatar", () => ({
  __esModule: true,
  default: () => <div />,
}));

jest.mock("@/components/tooltip/CustomTooltip", () => ({
  __esModule: true,
  TooltipGroup: ({ children }: any) => <>{children}</>,
}));

jest.mock("@/refresh-components/popovers/LLMPopover", () => ({
  __esModule: true,
  default: () => <div />,
}));

jest.mock("@/app/chat/message/messageComponents/CitedSourcesToggle", () => ({
  __esModule: true,
  default: () => <div />,
}));

jest.mock("@/components/admin/connectors/Popup", () => ({
  __esModule: true,
  usePopup: () => ({ popup: null, setPopup: jest.fn() }),
}));

jest.mock("../../hooks/useFeedbackController", () => ({
  __esModule: true,
  useFeedbackController: () => ({ handleFeedbackChange: jest.fn() }),
}));

jest.mock("../../components/modal/FeedbackModal", () => ({
  __esModule: true,
  default: () => <div />,
}));

jest.mock("@/app/chat/stores/useChatSessionStore", () => ({
  __esModule: true,
  useChatSessionStore: (selector: any) =>
    selector({
      updateCurrentDocumentSidebarVisible: jest.fn(),
      updateCurrentSelectedNodeForDocDisplay: jest.fn(),
    }),
  useDocumentSidebarVisible: () => false,
  useSelectedNodeForDocDisplay: () => null,
  useCurrentChatState: () => "input",
}));

describe("AIMessage copy button", () => {
  beforeEach(() => {
    lastCopyProps = null;
  });

  test("copies only final answer (no tool steps / thinking)", () => {
    const rawPackets: Packet[] = [
      {
        placement: { turn_index: 0, tab_index: 0 },
        obj: { type: PacketType.SEARCH_TOOL_START, is_internet_search: false },
      },
      {
        placement: { turn_index: 1, tab_index: 0 },
        obj: {
          type: PacketType.MESSAGE_START,
          id: "m1",
          content: "Hello <thinking>secret</thinking> World",
          final_documents: null,
        },
      },
      {
        placement: { turn_index: 1, tab_index: 0 },
        obj: { type: PacketType.MESSAGE_END },
      },
      {
        placement: { turn_index: 2, tab_index: 0 },
        obj: { type: PacketType.STOP },
      },
    ];

    const chatState: FullChatState = {
      assistant: {
        id: 1,
        name: "Assistant",
        description: "",
        tools: [],
        starter_messages: null,
        document_sets: [],
        is_public: true,
        is_visible: true,
        display_priority: null,
        is_default_persona: true,
        builtin_persona: true,
        owner: null,
      },
    };

    render(
      <AIMessage
        rawPackets={rawPackets}
        chatState={chatState}
        nodeId={1}
        llmManager={null}
      />
    );

    expect(screen.getByText("3 steps")).toBeInTheDocument();
    expect(lastCopyProps).not.toBeNull();

    const html = lastCopyProps.getHtmlContent?.() || "";
    expect(html).toContain("FINAL ANSWER");
    expect(html).not.toContain("3 steps");

    const text = lastCopyProps.getCopyText?.() || "";
    expect(text).not.toContain("3 steps");
    expect(text).not.toContain("<thinking>");
    expect(text).not.toContain("secret");
  });
});
