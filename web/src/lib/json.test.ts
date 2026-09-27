import {
  isJsonArray,
  isJsonObject,
  readArray,
  readNumber,
  readObject,
  readString,
} from "@/lib/json";
import type { JsonObject } from "@/lib/json";

describe("isJsonObject", () => {
  it("accepts plain objects only", () => {
    expect(isJsonObject({ a: 1 })).toBe(true);
    expect(isJsonObject([])).toBe(false);
    expect(isJsonObject(null)).toBe(false);
    expect(isJsonObject(undefined)).toBe(false);
    expect(isJsonObject("text")).toBe(false);
  });
});

describe("isJsonArray", () => {
  it("accepts arrays only", () => {
    expect(isJsonArray([1, "two"])).toBe(true);
    expect(isJsonArray({ 0: 1 })).toBe(false);
    expect(isJsonArray(null)).toBe(false);
  });
});

describe("readers", () => {
  const packet: JsonObject = {
    session_id: "abc",
    sessionId: "ignored",
    request_id: null,
    requestId: "req-1",
    used_tokens: 42,
    count: "7",
    meta: { parent: "p" },
    items: [1, 2],
  };

  it("uses the first key whose value is set", () => {
    expect(readString(packet, "session_id", "sessionId")).toBe("abc");
    expect(readString(packet, "request_id", "requestId")).toBe("req-1");
  });

  it("returns null when no key is set", () => {
    expect(readString(packet, "missing", "also_missing")).toBeNull();
  });

  it("returns null when the first set value has a different type", () => {
    expect(readString(packet, "used_tokens", "session_id")).toBeNull();
    expect(readNumber(packet, "count")).toBeNull();
    expect(readObject(packet, "items")).toBeNull();
    expect(readArray(packet, "meta")).toBeNull();
  });

  it("reads each JSON type", () => {
    expect(readNumber(packet, "used_tokens")).toBe(42);
    expect(readObject(packet, "meta")).toEqual({ parent: "p" });
    expect(readArray(packet, "items")).toEqual([1, 2]);
  });
});
