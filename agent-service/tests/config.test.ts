import { expect, test } from "bun:test";
import { validateWorkerConnection } from "../src/config";

const token = "synthetic-test-deployment-token-32-characters";
test("worker requires protected transport and a deployment secret", () => {
  expect(() =>
    validateWorkerConnection({
      apiUrl: "https://api.internal/internal/agent",
      token,
    }),
  ).not.toThrow();
  for (const apiUrl of [
    "http://api.internal/internal/agent",
    "ftp://api.internal",
    "https://user:secret@api.internal",
    "https://api.internal?secret=value",
    "https://api.internal#fragment",
    "invalid",
  ]) {
    expect(() => validateWorkerConnection({ apiUrl, token })).toThrow();
  }
  expect(() =>
    validateWorkerConnection({
      apiUrl: "http://127.0.0.1:8080/internal/agent",
      token,
      allowInsecureHttp: true,
    }),
  ).not.toThrow();
  for (const weak of ["", "onyx-local-agent", token + "\n"]) {
    expect(() =>
      validateWorkerConnection({ apiUrl: "https://api.internal", token: weak }),
    ).toThrow();
  }
});
