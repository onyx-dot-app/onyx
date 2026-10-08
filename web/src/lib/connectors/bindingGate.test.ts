import {
  UNLOCKED_GATE,
  bindingCheckInput,
  decideBindingGate,
  isEmptyField,
  type BindingGateInput,
  type BoundFieldState,
} from "@/lib/connectors/bindingGate";

const SITE: BoundFieldState = {
  name: "wiki_base",
  label: "Site URL",
  missing: false,
  invalid: false,
};

function gateInput(
  overrides: Partial<BindingGateInput> = {}
): BindingGateInput {
  return {
    hasBoundFields: true,
    credentialSelected: true,
    boundFields: [SITE],
    binding: {
      kind: "done",
      response: { field_errors: {}, rejection: null },
    },
    ...overrides,
  };
}

describe("decideBindingGate", () => {
  it("unlocks a source without bound fields once a credential is selected", () => {
    const input = gateInput({ hasBoundFields: false, boundFields: [] });
    expect(decideBindingGate(input)).toEqual(UNLOCKED_GATE);
    expect(
      decideBindingGate({ ...input, credentialSelected: false }).reason
    ).toEqual({ kind: "selectCredential" });
  });

  it("applies the extra condition to a source without bound fields", () => {
    const extra = {
      status: "locked" as const,
      reason: { kind: "custom" as const, message: "Wait for the checks." },
    };
    const input = gateInput({ hasBoundFields: false, boundFields: [], extra });
    expect(decideBindingGate(input)).toEqual(extra);
    expect(
      decideBindingGate({ ...input, credentialSelected: false }).reason
    ).toEqual({ kind: "selectCredential" });
  });

  it("asks for a missing bound field before the credential", () => {
    expect(
      decideBindingGate(
        gateInput({
          credentialSelected: false,
          boundFields: [{ ...SITE, missing: true }],
        })
      )
    ).toEqual({
      status: "locked",
      reason: { kind: "enterField", label: "Site URL" },
    });
  });

  it("locks on a field the form rejects", () => {
    expect(
      decideBindingGate(
        gateInput({ boundFields: [{ ...SITE, invalid: true }] })
      ).reason
    ).toEqual({ kind: "fixField", label: "Site URL" });
  });

  it("locks until a credential is selected", () => {
    expect(
      decideBindingGate(gateInput({ credentialSelected: false })).reason
    ).toEqual({ kind: "selectCredential" });
  });

  it("waits for a bound field to lose focus before the first check", () => {
    expect(decideBindingGate(gateInput({ binding: { kind: "idle" } }))).toEqual(
      { status: "locked", reason: { kind: "awaitingCheck" } }
    );
  });

  it("is checking while the binding check is in flight", () => {
    expect(
      decideBindingGate(gateInput({ binding: { kind: "checking" } }))
    ).toEqual({ status: "checking", reason: { kind: "checking" } });
  });

  it("unlocks when the binding check is unavailable", () => {
    expect(
      decideBindingGate(gateInput({ binding: { kind: "unavailable" } }))
    ).toEqual(UNLOCKED_GATE);
  });

  it("names the field the backend rejected", () => {
    expect(
      decideBindingGate(
        gateInput({
          binding: {
            kind: "done",
            response: {
              field_errors: {
                wiki_base: { kind: "invalid", detail: "Bad URL" },
              },
              rejection: null,
            },
          },
        })
      ).reason
    ).toEqual({
      kind: "fieldRejected",
      label: "Site URL",
      error: { kind: "invalid", detail: "Bad URL" },
    });
  });

  it("keeps the rejection of the credential", () => {
    const rejection = {
      code: "binding_rejected" as const,
      detail: "Authorized for another site.",
    };
    expect(
      decideBindingGate(
        gateInput({
          binding: {
            kind: "done",
            response: { field_errors: {}, rejection },
          },
        })
      )
    ).toEqual({ status: "locked", reason: { kind: "rejected", rejection } });
  });

  it("applies the extra condition only after the binding passes", () => {
    const extra = {
      status: "checking" as const,
      reason: { kind: "checking" as const },
    };
    expect(decideBindingGate(gateInput({ extra }))).toEqual(extra);
    expect(
      decideBindingGate(gateInput({ extra, credentialSelected: false })).reason
    ).toEqual({ kind: "selectCredential" });
  });
});

describe("bindingCheckInput", () => {
  it("sends only the bound values and keys on the credential", () => {
    const values = { wiki_base: "https://a", is_cloud: true, space: "ENG" };
    const first = bindingCheckInput("1", ["wiki_base", "is_cloud"], values);
    expect(first.config).toEqual({ is_cloud: true, wiki_base: "https://a" });
    expect(
      bindingCheckInput("2", ["wiki_base", "is_cloud"], values).key
    ).not.toBe(first.key);
    expect(
      bindingCheckInput("1", ["is_cloud", "wiki_base"], {
        ...values,
        space: "X",
      }).key
    ).toBe(first.key);
  });
});

describe("isEmptyField", () => {
  it.each([
    [undefined, true],
    ["  ", true],
    [[], true],
    [false, false],
    [0, false],
    ["x", false],
  ])("%p is empty: %p", (value, expected) => {
    expect(isEmptyField({ field: value }, "field")).toBe(expected);
  });
});
