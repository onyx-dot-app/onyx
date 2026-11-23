import { connectAction, requiredSignIns } from "@/lib/integrations/connect";
import {
  makeAccess,
  makeMemberIntegration,
} from "@tests/setup/memberIntegrationTestUtils";

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

test("only a Required integration the user can sign in to blocks", () => {
  const blocking = makeMemberIntegration({
    id: 1,
    access: makeAccess({ installation_policy: "REQUIRED" }),
  });
  const notRequired = makeMemberIntegration({
    id: 2,
    access: makeAccess({ installation_policy: "DEFAULT" }),
  });
  const connected = makeMemberIntegration({
    id: 3,
    status: { state: "connected", reason: null },
    access: makeAccess({ installation_policy: "REQUIRED", state: "on" }),
  });
  const adminOnly = makeMemberIntegration({
    id: 4,
    auth_mode: "shared",
    access: makeAccess({ installation_policy: "REQUIRED" }),
  });
  const noAccess = makeMemberIntegration({
    id: 5,
    access: makeAccess({ installation_policy: "REQUIRED", state: "no_access" }),
  });
  const reconnect = makeMemberIntegration({
    id: 6,
    auth_method: "api_key",
    status: { state: "needs_reconnect", reason: "Expired" },
    access: makeAccess({ installation_policy: "REQUIRED" }),
  });

  expect(
    requiredSignIns([
      blocking,
      notRequired,
      connected,
      adminOnly,
      noAccess,
      reconnect,
    ]).map((integration) => integration.id)
  ).toEqual([1, 6]);
  expect(requiredSignIns([])).toEqual([]);
});
