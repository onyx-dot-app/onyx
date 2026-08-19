import { describe, expect, it } from "@jest/globals";

import type { NormalizedAsset } from "@/api/files/upload";
import {
  DEFAULT_MAX_UPLOAD_MB,
  partitionBySize,
  resolveMaxUploadMb,
} from "@/lib/files";

const MB = 1024 * 1024;
const asset = (name: string, size?: number): NormalizedAsset => ({
  uri: `file:///${name}`,
  name,
  size,
});

describe("resolveMaxUploadMb", () => {
  it("returns the setting when it's a positive number", () => {
    expect(resolveMaxUploadMb(25)).toBe(25);
  });

  it("falls back to a finite default for null/0/negative (BUG2)", () => {
    expect(resolveMaxUploadMb(null)).toBe(DEFAULT_MAX_UPLOAD_MB);
    expect(resolveMaxUploadMb(0)).toBe(DEFAULT_MAX_UPLOAD_MB);
    expect(resolveMaxUploadMb(-5)).toBe(DEFAULT_MAX_UPLOAD_MB);
  });
});

describe("partitionBySize", () => {
  it("splits valid vs oversize against the resolved limit", () => {
    const { valid, rejections } = partitionBySize(
      [asset("small.pdf", 1 * MB), asset("big.pdf", 30 * MB)],
      10,
    );
    expect(valid.map((a) => a.name)).toEqual(["small.pdf"]);
    expect(rejections).toEqual(["big.pdf exceeds the 10 MB limit"]);
  });

  it("uses the finite fallback (not unlimited) when the setting is null (BUG2)", () => {
    // 150 MB is under no server cap but over the 100 MB fallback → rejected client-side.
    const { valid, rejections } = partitionBySize(
      [asset("huge.zip", 150 * MB)],
      null,
    );
    expect(valid).toEqual([]);
    expect(rejections).toEqual([
      `huge.zip exceeds the ${DEFAULT_MAX_UPLOAD_MB} MB limit`,
    ]);
  });

  it("keeps assets with unknown size (can't precheck)", () => {
    const { valid, rejections } = partitionBySize([asset("no-size.pdf")], 10);
    expect(valid.map((a) => a.name)).toEqual(["no-size.pdf"]);
    expect(rejections).toEqual([]);
  });
});
