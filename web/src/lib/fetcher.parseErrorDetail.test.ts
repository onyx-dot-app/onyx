/**
 * Pins the message each "read a failed Response's error body" helper returns
 * for the body shapes the backend and its proxies can send.
 */
import { parseErrorDetail } from "@/lib/fetcher";
import { getErrorMsg } from "@/lib/fetchUtils";
import { deleteAgent } from "@/lib/agents/svc";
import { updateAdminSettings } from "@/lib/settings/svc";
import { disconnectTracingProvider } from "@/lib/tracing/svc";
import {
  connectProviderFlow,
  ConnectProviderFlowArgs,
  disconnectProvider,
} from "@/lib/webSearch/svc";
import type { JsonValue } from "@/lib/json";

const FALLBACK = "Fallback message";
const DETAIL_OBJECT = {
  code: "RESET_PASSWORD_INVALID_PASSWORD",
  reason: "Password too short",
};
const DETAIL_ARRAY = [
  { loc: ["body", "name"], msg: "field required", type: "missing" },
];

type BodyCase =
  | "stringDetail"
  | "messageOnly"
  | "detailAndMessage"
  | "detailObject"
  | "detailArray"
  | "emptyObject"
  | "emptyStringDetail"
  | "plainText"
  | "emptyBody";

const BODY_CASES: BodyCase[] = [
  "stringDetail",
  "messageOnly",
  "detailAndMessage",
  "detailObject",
  "detailArray",
  "emptyObject",
  "emptyStringDetail",
  "plainText",
  "emptyBody",
];

function jsonResponse(body: JsonValue): Response {
  return new Response(JSON.stringify(body), {
    status: 400,
    headers: { "Content-Type": "application/json" },
  });
}

function makeResponse(bodyCase: BodyCase): Response {
  switch (bodyCase) {
    case "stringDetail":
      return jsonResponse({ detail: "Detail text" });
    case "messageOnly":
      return jsonResponse({ message: "Message text" });
    case "detailAndMessage":
      return jsonResponse({ detail: "Detail text", message: "Message text" });
    case "detailObject":
      return jsonResponse({ detail: DETAIL_OBJECT });
    case "detailArray":
      return jsonResponse({ detail: DETAIL_ARRAY });
    case "emptyObject":
      return jsonResponse({});
    case "emptyStringDetail":
      return jsonResponse({ detail: "" });
    case "plainText":
      return new Response("Internal Server Error", {
        status: 500,
        headers: { "Content-Type": "text/plain" },
      });
    case "emptyBody":
      return new Response(null, { status: 500 });
  }
}

let fetchSpy: jest.SpyInstance;

beforeEach(() => {
  fetchSpy = jest.spyOn(global, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
});

function mockFailedFetch(bodyCase: BodyCase): void {
  fetchSpy.mockImplementation(() => Promise.resolve(makeResponse(bodyCase)));
}

async function thrownMessage(action: () => Promise<void>): Promise<string> {
  try {
    await action();
  } catch (error) {
    if (error instanceof Error) return error.message;
    throw error;
  }
  throw new Error("expected the action to throw");
}

// `detail` passes through as-is (even when it is not a string); callers that
// wrap it in `new Error(...)` show its string form.
const PASSTHROUGH_EXPECTED: Record<BodyCase, JsonValue> = {
  stringDetail: "Detail text",
  messageOnly: FALLBACK,
  detailAndMessage: "Detail text",
  detailObject: DETAIL_OBJECT,
  detailArray: DETAIL_ARRAY,
  emptyObject: FALLBACK,
  emptyStringDetail: "",
  plainText: FALLBACK,
  emptyBody: FALLBACK,
};

const PASSTHROUGH_ERROR_MESSAGE: Record<BodyCase, string> = {
  stringDetail: "Detail text",
  messageOnly: FALLBACK,
  detailAndMessage: "Detail text",
  detailObject: "[object Object]",
  detailArray: "[object Object]",
  emptyObject: FALLBACK,
  emptyStringDetail: "",
  plainText: FALLBACK,
  emptyBody: FALLBACK,
};

// Only a string `detail` is used; anything else gives the fallback.
const STRING_ONLY_EXPECTED: Record<BodyCase, string> = {
  stringDetail: "Detail text",
  messageOnly: FALLBACK,
  detailAndMessage: "Detail text",
  detailObject: FALLBACK,
  detailArray: FALLBACK,
  emptyObject: FALLBACK,
  emptyStringDetail: "",
  plainText: FALLBACK,
  emptyBody: FALLBACK,
};

function withFallback(expected: string, fallback: string): string {
  return expected === FALLBACK ? fallback : expected;
}

describe("fetcher parseErrorDetail", () => {
  test.each(BODY_CASES)("%s", async (bodyCase) => {
    await expect(
      parseErrorDetail(makeResponse(bodyCase), FALLBACK)
    ).resolves.toEqual(PASSTHROUGH_EXPECTED[bodyCase]);
  });
});

describe("settings updateAdminSettings error", () => {
  test.each(BODY_CASES)("%s", async (bodyCase) => {
    mockFailedFetch(bodyCase);
    await expect(thrownMessage(() => updateAdminSettings({}))).resolves.toBe(
      withFallback(
        PASSTHROUGH_ERROR_MESSAGE[bodyCase],
        "Failed to update settings"
      )
    );
  });
});

describe("tracing disconnectTracingProvider error", () => {
  test.each(BODY_CASES)("%s", async (bodyCase) => {
    mockFailedFetch(bodyCase);
    await expect(
      thrownMessage(() => disconnectTracingProvider("langfuse", {}))
    ).resolves.toBe(
      withFallback(
        PASSTHROUGH_ERROR_MESSAGE[bodyCase],
        "Failed to disconnect provider."
      )
    );
  });
});

describe("webSearch disconnectProvider error", () => {
  test.each(BODY_CASES)("%s", async (bodyCase) => {
    mockFailedFetch(bodyCase);
    await expect(
      thrownMessage(() => disconnectProvider(1, "search"))
    ).resolves.toBe(
      withFallback(
        PASSTHROUGH_ERROR_MESSAGE[bodyCase],
        "Failed to disconnect provider."
      )
    );
  });
});

describe("agents deleteAgent error", () => {
  test.each(BODY_CASES)("%s", async (bodyCase) => {
    mockFailedFetch(bodyCase);
    await expect(thrownMessage(() => deleteAgent(1))).resolves.toBe(
      withFallback(STRING_ONLY_EXPECTED[bodyCase], "Failed to delete agent")
    );
  });
});

describe("webSearch connectProviderFlow error", () => {
  function flowArgs(
    isNewProvider: boolean,
    onError: (message: string) => void
  ): ConnectProviderFlowArgs {
    return {
      category: "search",
      providerType: "exa",
      existingProviderId: isNewProvider ? null : 1,
      existingProviderName: isNewProvider ? null : "Exa",
      existingProviderHasApiKey: false,
      displayName: "Exa",
      providerRequiresApiKey: false,
      apiKeyChangedForProvider: false,
      apiKey: "",
      config: {},
      configChanged: false,
      onValidating: () => undefined,
      onSaving: () => undefined,
      onError,
      onClose: () => undefined,
      mutate: () => Promise.resolve(),
    };
  }

  test.each(BODY_CASES)("validation %s", async (bodyCase) => {
    mockFailedFetch(bodyCase);
    const onError = jest.fn();
    await connectProviderFlow(flowArgs(true, onError));
    expect(onError).toHaveBeenCalledWith(
      withFallback(
        STRING_ONLY_EXPECTED[bodyCase],
        "Failed to validate configuration."
      )
    );
  });

  test.each(BODY_CASES)("activation %s", async (bodyCase) => {
    mockFailedFetch(bodyCase);
    const onError = jest.fn();
    await connectProviderFlow(flowArgs(false, onError));
    expect(onError).toHaveBeenCalledWith(
      withFallback(
        STRING_ONLY_EXPECTED[bodyCase],
        "Failed to activate provider."
      )
    );
  });
});

describe("fetchUtils getErrorMsg", () => {
  const expected: Record<BodyCase, JsonValue> = {
    stringDetail: "Detail text",
    messageOnly: "Message text",
    detailAndMessage: "Message text",
    detailObject: DETAIL_OBJECT,
    detailArray: DETAIL_ARRAY,
    emptyObject: "Unknown error",
    emptyStringDetail: "Unknown error",
    plainText: FALLBACK,
    emptyBody: FALLBACK,
  };

  test.each(BODY_CASES)("%s", async (bodyCase) => {
    const result = getErrorMsg(makeResponse(bodyCase));
    if (bodyCase === "plainText" || bodyCase === "emptyBody") {
      // A non-JSON body rejects instead of returning a message. The error
      // comes from another realm, so match by name, not by constructor.
      await expect(result).rejects.toHaveProperty("name", "SyntaxError");
    } else {
      await expect(result).resolves.toEqual(expected[bodyCase]);
    }
  });

  test("returns null for an OK response", async () => {
    await expect(getErrorMsg(new Response("{}"))).resolves.toBeNull();
  });
});
