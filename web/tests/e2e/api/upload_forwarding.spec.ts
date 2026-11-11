import { expect, test } from "@playwright/test";

const inspectPath = "/api/skills/custom/bundle/inspect";
const instructions =
  "x".repeat(12 * 1024 * 1024) + "\nEnd of uploaded instructions.";
const skill = Buffer.from(
  "---\nname: proxy-upload-regression\ndescription: Upload forwarding regression\n---\n\n" +
    instructions
);

// Inspection validates and returns the upload without creating a stored skill.
// CI reaches the backend through nginx, so this does not exercise the Next proxy.
test("accepts a Skill upload larger than 10 MiB", async ({ request }) => {
  const response = await request.post(inspectPath, {
    multipart: {
      upload: { name: "SKILL.md", mimeType: "text/markdown", buffer: skill },
    },
  });
  expect(response.status()).toBe(200);
  const result: unknown = await response.json();
  expect(result).toMatchObject({ instructions_markdown: instructions });
});

test("returns backend validation for a large invalid upload", async ({
  request,
}) => {
  const response = await request.post(inspectPath, {
    multipart: {
      upload: {
        name: "invalid.zip",
        mimeType: "application/zip",
        buffer: skill,
      },
    },
  });
  expect(response.status()).toBe(400);
  const result: unknown = await response.json();
  expect(result).toMatchObject({
    detail: expect.stringContaining("not a valid zip"),
  });
});
