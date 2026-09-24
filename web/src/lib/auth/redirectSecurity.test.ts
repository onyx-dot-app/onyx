import { validateInternalRedirect } from "@/lib/auth/utils";

it.each([
  "/\t/evil.example",
  "/\r/evil.example",
  "/\n/evil.example",
  "/path\x00next",
  "/path\x7fnext",
])("rejects control characters in %j before navigation", (url) => {
  expect(validateInternalRedirect(url)).toBeNull();
  expect(validateInternalRedirect("/app?next=project")).toBe(
    "/app?next=project"
  );
});
