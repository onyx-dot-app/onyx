import { externalToolLabel } from "@/app/app/message/messageComponents/toolDisplayHelpers";

describe("externalToolLabel", () => {
  it.each([
    ["custom__12__check_service_health", "check_service_health"],
    ["mcp__3__github__create_issue", "create_issue"],
    ["mcp__3____create_issue", "create_issue"],
    ["run_search", "run_search"],
    ["custom__check_service_health", "custom__check_service_health"],
  ])("labels %s as %s", (toolName, label) => {
    expect(externalToolLabel(toolName)).toBe(label);
  });
});
