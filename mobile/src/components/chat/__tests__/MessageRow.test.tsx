import { describe, expect, it, jest } from "@jest/globals";
import { render } from "@testing-library/react-native";

import type { Message } from "@/chat/interfaces";
import { MessageRow } from "@/components/chat/MessageRow";

// These reach native modules that jest cannot load; this row renders neither.
jest.mock("@/state/storage");
jest.mock("@/components/chat/StreamingMarkdown", () => ({}));

describe("MessageRow", () => {
  it("renders nothing for an automatic follow-up's hidden question", () => {
    const node: Message = {
      nodeId: 3,
      messageId: 3,
      message: "Subagent results",
      type: "agent_results",
      files: [],
      parentNodeId: 2,
      childrenNodeIds: [4],
      latestChildNodeId: 4,
      packets: [],
    };

    const view = render(<MessageRow node={node} agent={null} />);

    expect(view.toJSON()).toBeNull();
  });
});
