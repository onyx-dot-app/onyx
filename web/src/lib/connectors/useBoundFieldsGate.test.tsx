import { act, deferred, renderHook } from "@tests/setup/test-utils";
import {
  useBoundFieldsGate,
  type UseBoundFieldsGateParams,
} from "@/lib/connectors/hooks";
import { checkCredentialBinding } from "@/lib/connectors/svc";
import type { CredentialBindingCheckResponse } from "@/lib/connectors/bindingGate";
import { ValidSources } from "@/lib/connectors/types/source";

jest.mock("@/lib/connectors/svc", () => ({
  checkCredentialBinding: jest.fn(),
}));

const mockedCheck = jest.mocked(checkCredentialBinding);

const SITE = "https://acme.atlassian.net/wiki";
const VALID: CredentialBindingCheckResponse = {
  field_errors: {},
  rejection: null,
};
const REJECTED: CredentialBindingCheckResponse = {
  field_errors: {},
  rejection: {
    code: "binding_rejected",
    detail: "Authorized for another site.",
  },
};

function params(
  overrides: Partial<UseBoundFieldsGateParams> = {}
): UseBoundFieldsGateParams {
  return {
    source: ValidSources.Confluence,
    credentialId: 1,
    credentialUpdatedAt: "2026-01-01T00:00:00Z",
    credentialSelected: true,
    boundFieldNames: ["wiki_base"],
    boundFields: [
      { name: "wiki_base", label: "Site URL", missing: false, invalid: false },
    ],
    values: { wiki_base: SITE },
    ...overrides,
  };
}

/** Runs the pending timers and lets resolved responses reach the hook. */
async function flush(): Promise<void> {
  await act(async () => {
    jest.runOnlyPendingTimers();
    await Promise.resolve();
  });
}

describe("useBoundFieldsGate", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockedCheck.mockReset();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("checks once for the selected credential and unlocks", async () => {
    mockedCheck.mockResolvedValue(VALID);
    const { result } = renderHook(() => useBoundFieldsGate(params()));

    expect(result.current.status).toBe("checking");
    await flush();

    expect(mockedCheck).toHaveBeenCalledTimes(1);
    expect(mockedCheck).toHaveBeenCalledWith(1, {
      source: ValidSources.Confluence,
      connector_specific_config: { wiki_base: SITE },
    });
    expect(result.current.status).toBe("unlocked");
  });

  it("does not check while a bound value changes, only when it loses focus", async () => {
    mockedCheck.mockResolvedValue(VALID);
    const { result, rerender } = renderHook(
      (props: UseBoundFieldsGateParams) => useBoundFieldsGate(props),
      { initialProps: params() }
    );
    await flush();
    mockedCheck.mockClear();

    rerender(params({ values: { wiki_base: `${SITE}x` } }));
    await flush();
    expect(mockedCheck).not.toHaveBeenCalled();
    expect(result.current.reason).toEqual({ kind: "awaitingCheck" });

    act(() => result.current.requestCheck());
    await flush();
    expect(mockedCheck).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("unlocked");
  });

  it("checks again on blur for an input it already checked", async () => {
    mockedCheck.mockResolvedValue(VALID);
    const { result } = renderHook(() => useBoundFieldsGate(params()));
    await flush();

    act(() => result.current.requestCheck());
    await flush();

    expect(mockedCheck).toHaveBeenCalledTimes(2);
  });

  it("checks again when the credential is edited", async () => {
    mockedCheck.mockResolvedValue(VALID);
    const { rerender } = renderHook(
      (props: UseBoundFieldsGateParams) => useBoundFieldsGate(props),
      { initialProps: params() }
    );
    await flush();

    rerender(params({ credentialUpdatedAt: "2026-02-01T00:00:00Z" }));
    await flush();

    expect(mockedCheck).toHaveBeenCalledTimes(2);
  });

  it("keeps the response for the newest credential when responses arrive out of order", async () => {
    const first = deferred<CredentialBindingCheckResponse>();
    const second = deferred<CredentialBindingCheckResponse>();
    mockedCheck
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(
      (props: UseBoundFieldsGateParams) => useBoundFieldsGate(props),
      { initialProps: params() }
    );
    await flush();

    rerender(params({ credentialId: 2 }));
    await flush();
    expect(mockedCheck).toHaveBeenCalledTimes(2);

    await act(async () => {
      second.resolve(VALID);
      await second.promise;
    });
    await act(async () => {
      first.resolve(REJECTED);
      await first.promise;
    });

    expect(result.current.status).toBe("unlocked");
  });

  it("checks again after a failed check", async () => {
    mockedCheck.mockRejectedValueOnce(new Error("offline"));
    mockedCheck.mockResolvedValueOnce(REJECTED);
    const { result } = renderHook(() => useBoundFieldsGate(params()));
    await flush();
    // A failed check does not lock the form: creation checks again.
    expect(result.current.status).toBe("unlocked");

    act(() => result.current.requestCheck());
    await flush();

    expect(mockedCheck).toHaveBeenCalledTimes(2);
    expect(result.current.reason).toEqual({
      kind: "rejected",
      rejection: REJECTED.rejection,
    });
  });

  it("sends nothing and ignores a response after unmount", async () => {
    const pending = deferred<CredentialBindingCheckResponse>();
    mockedCheck.mockReturnValueOnce(pending.promise);
    const { result, unmount } = renderHook(() => useBoundFieldsGate(params()));
    await flush();

    act(() => result.current.requestCheck());
    unmount();
    await act(async () => {
      jest.runOnlyPendingTimers();
      pending.resolve(VALID);
      await pending.promise;
    });

    expect(mockedCheck).toHaveBeenCalledTimes(1);
  });
});
