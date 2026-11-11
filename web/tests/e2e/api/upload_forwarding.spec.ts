import { expect, test } from "@playwright/test";

const inspectPath = "/api/skills/custom/bundle/inspect";
const instructions = "End of uploaded instructions.";
const skillMd = Buffer.from(
  "---\nname: proxy-upload-regression\ndescription: Upload forwarding regression\n---\n\n" +
    instructions
);
// SKILL.md has its own 256 KiB limit, so the large part is a supporting file.
const largeFile = Buffer.alloc(12 * 1024 * 1024, "x");

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(data: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc = (CRC_TABLE[(crc ^ byte) & 0xff] ?? 0) ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

// Uncompressed, so the upload stays as large as its files.
function storedZip(files: [string, Buffer][]): Buffer {
  const DOS_DATE_1980_01_01 = 0x21;
  const parts: Buffer[] = [];
  const directory: Buffer[] = [];
  let offset = 0;
  for (const [name, data] of files) {
    const nameBytes = Buffer.from(name);
    const crc = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(DOS_DATE_1980_01_01, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(DOS_DATE_1980_01_01, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE(offset, 42);
    parts.push(local, nameBytes, data);
    directory.push(central, nameBytes);
    offset += local.length + nameBytes.length + data.length;
  }
  const directoryBytes = Buffer.concat(directory);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(directoryBytes.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...parts, directoryBytes, end]);
}

// Inspection validates and returns the upload without creating a stored skill.
// CI reaches the backend through nginx, so this does not exercise the Next proxy.
test("accepts a Skill upload larger than 10 MiB", async ({ request }) => {
  const bundle = storedZip([
    ["SKILL.md", skillMd],
    ["reference.txt", largeFile],
  ]);
  const response = await request.post(inspectPath, {
    multipart: {
      upload: {
        name: "bundle.zip",
        mimeType: "application/zip",
        buffer: bundle,
      },
    },
  });
  expect(response.status()).toBe(200);
  const result: unknown = await response.json();
  expect(result).toMatchObject({
    instructions_markdown: instructions,
    files: expect.arrayContaining([
      { path: "reference.txt", size: largeFile.length },
    ]),
  });
});

test("returns backend validation for a large invalid upload", async ({
  request,
}) => {
  const response = await request.post(inspectPath, {
    multipart: {
      upload: {
        name: "invalid.zip",
        mimeType: "application/zip",
        buffer: largeFile,
      },
    },
  });
  expect(response.status()).toBe(400);
  const result: unknown = await response.json();
  expect(result).toMatchObject({
    detail: expect.stringContaining("not a valid zip"),
  });
});
