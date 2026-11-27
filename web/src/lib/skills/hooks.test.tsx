import useSWR, { SWRConfig } from "swr";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import { useSkillBulkSelection, useSkillEnablement } from "@/lib/skills/hooks";
import type { CustomSkill, SkillsList } from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { toast } from "@opal/layouts";

const mockBulkUpdateSkills = jest.fn();
const mockSetSkillEnabled = jest.fn();
jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  bulkUpdateSkills: (...args: unknown[]) => mockBulkUpdateSkills(...args),
  setSkillEnabled: (...args: unknown[]) => mockSetSkillEnabled(...args),
}));
jest.mock("@/lib/skills/cache", () => ({
  refreshSkillListsChecked: () => Promise.resolve(true),
}));

const toggling = customFixture({ id: "toggling", name: "toggling" });
const target = customFixture({ id: "target", name: "target" });
const locked = customFixture({
  id: "locked",
  name: "locked",
  enabled: false,
  can_toggle: false,
});

function Harness({ items }: { items: CustomSkill[] }) {
  const bulk = useSkillBulkSelection({
    items,
    noun: "plugin",
    enablement: {
      isPending: (id) => id === toggling.id,
      enabledOf: (skill) => skill.enabled,
    },
  });
  return (
    <>
      <button onClick={() => bulk.select(new Set([toggling.id]))}>
        select toggling
      </button>
      <button onClick={() => bulk.confirmDelete([target])}>
        delete target
      </button>
      <button onClick={() => void bulk.run("delete")}>run delete</button>
      <button onClick={() => bulk.select(new Set([target.id]))}>
        select target
      </button>
      <button onClick={() => bulk.select(new Set([target.id, locked.id]))}>
        select target and locked
      </button>
      <button onClick={() => bulk.select(new Set([locked.id]))}>
        select locked
      </button>
      <button onClick={() => void bulk.run("enable")}>run enable</button>
      <p data-testid="delete-open">{String(bulk.deleteModal.isOpen)}</p>
      <p data-testid="selection">{[...bulk.selectedIds].join(",")}</p>
      <p data-testid="busy">{String(bulk.busy)}</p>
    </>
  );
}

async function deleteTarget(user: ReturnType<typeof setupUser>) {
  await user.click(screen.getByRole("button", { name: "delete target" }));
  await user.click(screen.getByRole("button", { name: "run delete" }));
}

test("a pending toggle of a selected plugin does not block deleting another", async () => {
  mockBulkUpdateSkills.mockResolvedValue({
    succeeded: [target.id],
    failed: [],
  });
  const user = setupUser();
  render(<Harness items={[toggling, target]} />);

  await user.click(screen.getByRole("button", { name: "select toggling" }));
  await deleteTarget(user);

  await waitFor(() =>
    expect(mockBulkUpdateSkills).toHaveBeenCalledWith({
      action: "delete",
      skill_ids: [target.id],
    })
  );
});

test("a finished enable keeps a delete confirmation open", async () => {
  let finish: (value: unknown) => void = () => undefined;
  mockBulkUpdateSkills.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  const user = setupUser();
  render(<Harness items={[toggling, target]} />);

  await user.click(screen.getByRole("button", { name: "select target" }));
  await user.click(screen.getByRole("button", { name: "run enable" }));
  await user.click(screen.getByRole("button", { name: "delete target" }));
  finish({ succeeded: [target.id], failed: [] });

  await waitFor(() =>
    expect(screen.getByTestId("busy")).toHaveTextContent("false")
  );
  expect(screen.getByTestId("delete-open")).toHaveTextContent("true");
});

test("a row delete keeps the selection of other plugins", async () => {
  mockBulkUpdateSkills.mockResolvedValue({
    succeeded: [target.id],
    failed: [],
  });
  const user = setupUser();
  render(<Harness items={[toggling, target]} />);

  await user.click(screen.getByRole("button", { name: "select toggling" }));
  await deleteTarget(user);

  await waitFor(() => expect(mockBulkUpdateSkills).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.getByTestId("busy")).toHaveTextContent("false")
  );
  expect(screen.getByTestId("selection")).toHaveTextContent(toggling.id);
});

test("a failed delete shows an error toast", async () => {
  mockBulkUpdateSkills.mockResolvedValue({
    succeeded: [],
    failed: [{ skill_id: target.id, detail: "In use" }],
  });
  const error = jest.spyOn(toast, "error");
  const user = setupUser();
  render(<Harness items={[toggling, target]} />);

  await deleteTarget(user);

  await waitFor(() =>
    expect(error).toHaveBeenCalledWith("1 plugin could not be updated")
  );
  error.mockRestore();
});

function CachedNames() {
  const { data } = useSWR<SkillsList>(SWR_KEYS.userSkills, null);
  return (
    <p data-testid="cached">
      {(data?.customs ?? []).map((skill) => skill.name).join(",")}
    </p>
  );
}

test("a delete drops the deleted plugin from the cached list", async () => {
  mockBulkUpdateSkills.mockResolvedValue({
    succeeded: [target.id],
    failed: [],
  });
  const list: SkillsList = { builtins: [], customs: [toggling, target] };
  const user = setupUser();
  render(
    <SWRConfig
      value={{
        provider: () => new Map([[SWR_KEYS.userSkills, { data: list }]]),
      }}
    >
      <Harness items={[toggling, target]} />
      <CachedNames />
    </SWRConfig>
  );
  expect(screen.getByTestId("cached")).toHaveTextContent("toggling,target");

  await deleteTarget(user);

  await waitFor(() =>
    expect(screen.getByTestId("cached")).toHaveTextContent(/^toggling$/)
  );
});

test("a bulk enable sends only the plugins the user can turn on and reports the rest", async () => {
  mockBulkUpdateSkills.mockResolvedValue({ succeeded: [], failed: [] });
  const info = jest.spyOn(toast, "info");
  const offTarget = { ...target, enabled: false };
  const user = setupUser();
  render(<Harness items={[offTarget, locked]} />);

  await user.click(
    screen.getByRole("button", { name: "select target and locked" })
  );
  await user.click(screen.getByRole("button", { name: "run enable" }));

  await waitFor(() =>
    expect(mockBulkUpdateSkills).toHaveBeenCalledWith({
      action: "enable",
      skill_ids: [target.id],
    })
  );
  await waitFor(() =>
    expect(info).toHaveBeenCalledWith(
      "1 plugin cannot be turned on or off by you and was skipped"
    )
  );
  info.mockRestore();
});

test("a bulk enable of only locked plugins sends nothing and says so", async () => {
  mockBulkUpdateSkills.mockReset();
  const info = jest.spyOn(toast, "info");
  const user = setupUser();
  render(<Harness items={[locked]} />);

  await user.click(screen.getByRole("button", { name: "select locked" }));
  await user.click(screen.getByRole("button", { name: "run enable" }));

  await waitFor(() =>
    expect(info).toHaveBeenCalledWith(
      "1 plugin cannot be turned on or off by you and was skipped"
    )
  );
  expect(mockBulkUpdateSkills).not.toHaveBeenCalled();
  info.mockRestore();
});

function EnablementHarness({ items }: { items: CustomSkill[] }) {
  const enablement = useSkillEnablement(items, jest.fn());
  return (
    <>
      <button onClick={() => void enablement.setEnabled(items[1]!, true)}>
        turn on second
      </button>
      <p data-testid="switch-open">{String(enablement.switchModal.isOpen)}</p>
    </>
  );
}

test("turning on a skill whose name a required skill holds does not offer a switch", async () => {
  const error = jest.spyOn(toast, "error");
  const required = customFixture({
    id: "required",
    name: "shared",
    enabled: true,
    can_toggle: false,
    required_for_user: true,
  });
  const candidate = customFixture({
    id: "candidate",
    name: "shared",
    enabled: false,
  });
  const user = setupUser();
  render(<EnablementHarness items={[required, candidate]} />);

  await user.click(screen.getByRole("button", { name: "turn on second" }));

  await waitFor(() =>
    expect(error).toHaveBeenCalledWith(
      "shared cannot be turned on. A required skill already has this name."
    )
  );
  expect(screen.getByTestId("switch-open")).toHaveTextContent("false");
  expect(mockSetSkillEnabled).not.toHaveBeenCalled();
  error.mockRestore();
});
