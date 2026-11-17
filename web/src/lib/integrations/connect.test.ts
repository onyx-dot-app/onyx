import { connectAction } from "@/lib/integrations/connect";
import { makeMemberIntegration } from "@/sections/plugins/__tests__/memberIntegrationFixtures";

test("a member reconnects an own connection but not the organization one", () => {
  const needsReconnect = {
    state: "needs_reconnect" as const,
    reason: "Expired",
  };
  expect(
    connectAction(
      makeMemberIntegration({ auth_mode: "individual", status: needsReconnect })
    )
  ).toBe("reconnect");
  expect(
    connectAction(
      makeMemberIntegration({ auth_mode: "shared", status: needsReconnect })
    )
  ).toBeNull();
});
