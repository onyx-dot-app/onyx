import { effectiveChatPreference } from "@/lib/tools/chat";
import type { ToolSnapshot } from "@/lib/tools/types";

const search = { id: 1, in_code_tool_id: "SearchTool" } as ToolSnapshot;
const action = {
  type: "action",
  integration_id: 7,
  action: "create_issue",
} as const;

test("a built-in tool of the agent wins", () => {
  expect(
    effectiveChatPreference({
      requestedToolId: 1,
      requestedAction: null,
      agent: { tools: [search] },
      isIntegrationEnabled: () => true,
    })
  ).toEqual({ type: "capability", tool_id: 1 });
});

test("a saved action goes out while its integration is on", () => {
  const preference = (enabled: boolean) =>
    effectiveChatPreference({
      requestedToolId: null,
      requestedAction: action,
      agent: { tools: [search] },
      isIntegrationEnabled: () => enabled,
    });
  expect(preference(true)).toEqual(action);
  expect(preference(false)).toBeNull();
});
