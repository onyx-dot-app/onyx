import { useState } from "react";
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import ModifyCredential from "@/lib/credentials/components/ModifyCredential";
import type { AnyCredential } from "@/lib/credentials/types";
import { ValidSources } from "@/lib/connectors/types/source";

function credential(id: number): AnyCredential {
  return {
    id,
    name: `account ${id}`,
    credential_json: {},
    admin_public: true,
    source: ValidSources.Confluence,
    user_id: null,
    user_email: null,
    time_created: "2026-01-01T00:00:00Z",
    time_updated: "2026-01-01T00:00:00Z",
  };
}

function rowOf(name: string): HTMLElement {
  const row = screen.getByText(name).closest("tr");
  if (row === null) throw new Error(`no row for ${name}`);
  return row;
}

// The selected row shows a mark in place of its radio button.
function isMarkedSelected(name: string): boolean {
  return within(rowOf(name)).queryByRole("radio") === null;
}

/** The page side of the credential step: it owns the selection. */
function Harness({ initial }: { initial: AnyCredential[] }) {
  const [credentials, setCredentials] = useState(initial);
  const [current, setCurrent] = useState<AnyCredential | null>(null);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          // A new credential is created and switched to, as the create
          // form does.
          const created = credential(credentials.length + 1);
          setCredentials([...credentials, created]);
          setCurrent(created);
        }}
      >
        create
      </button>
      <ModifyCredential
        showIfEmpty
        accessType="public"
        defaultedCredential={current ?? undefined}
        credentials={credentials}
        onDeleteCredential={() => {}}
        onSwitch={setCurrent}
      />
    </>
  );
}

describe("ModifyCredential with onSwitch", () => {
  it("marks the credential the caller switched to, also after a pick", async () => {
    const user = setupUser();
    render(<Harness initial={[credential(1), credential(2)]} />);

    await user.click(within(rowOf("account 2")).getByRole("radio"));
    expect(isMarkedSelected("account 2")).toBe(true);
    expect(isMarkedSelected("account 1")).toBe(false);

    await user.click(screen.getByRole("button", { name: "create" }));

    expect(isMarkedSelected("account 3")).toBe(true);
    expect(isMarkedSelected("account 2")).toBe(false);
  });
});
