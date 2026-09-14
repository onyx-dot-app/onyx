// The cell measures how many group tags fit, and re-measures when the
// container width changes. The ResizeObserver that reports those changes is
// attached once per `groups` value, so the observed node must survive the
// render that follows the first measurement.
import { render, screen, waitFor } from "@tests/setup/test-utils";
import { AccountType, UserStatus } from "@/lib/types";
import GroupsCell from "./GroupsCell";
import type { UserRow } from "./interfaces";

/** Every node handed to a ResizeObserver, in observe order. */
const observedNodes: Element[] = [];

beforeEach(() => {
  observedNodes.length = 0;
  global.ResizeObserver = class {
    observe(node: Element) {
      observedNodes.push(node);
    }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

const user: UserRow = {
  id: "1",
  email: "user@example.com",
  account_type: AccountType.STANDARD,
  is_admin: false,
  status: UserStatus.ACTIVE,
  is_active: true,
  is_scim_synced: false,
  craft_enabled: null,
  personal_name: null,
  created_at: null,
  updated_at: null,
  groups: [],
};

it("keeps observing the container after the overflow tooltip appears", async () => {
  const groups = [
    { id: 1, name: "Alpha" },
    { id: 2, name: "Beta" },
  ];

  render(<GroupsCell groups={groups} user={user} onMutate={() => {}} />);

  // jsdom reports zero widths, so one tag "fits" and the rest overflow. The
  // "+N" counter marks the end of the measurement phase.
  await waitFor(() => {
    expect(screen.getByText("+1")).toBeInTheDocument();
  });

  const observed = observedNodes[observedNodes.length - 1];
  expect(observed).toBeDefined();
  // A detached node reports no resizes, so the cell would stop re-measuring.
  expect(observed!.isConnected).toBe(true);
});
