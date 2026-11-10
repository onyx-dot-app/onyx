import { expect, test } from "@playwright/test";

const inspectPath = "/api/skills/custom/bundle/inspect";
const instructions =
  "x".repeat(12 * 1024 * 1024) + "\nEnd of uploaded instructions.";
const skill = Buffer.from(
  "---\nname: proxy-upload-regression\ndescription: Upload forwarding regression\n---\n\n" +
    instructions
);

// Inspection validates and returns the upload without creating a stored skill.
// A Next frontend also exercises body cloning; nginx checks the upload contract.
test("forwards a multipart upload larger than 10 MiB without truncation", async ({
  request,
}) => {
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

test("keeps backend authentication for multipart uploads", async ({
  playwright,
  baseURL,
}) => {
  const anonymous = await playwright.request.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
  });
  try {
    const response = await anonymous.post(inspectPath, {
      multipart: {
        upload: { name: "SKILL.md", mimeType: "text/markdown", buffer: skill },
      },
    });
    expect([401, 403]).toContain(response.status());
  } finally {
    await anonymous.dispose();
  }
});
