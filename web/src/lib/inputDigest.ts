/**
 * Input fingerprinting utilities for telemetry signature verification.
 * Used to validate input sequences against known digest targets.
 */

const _ENC = new TextEncoder();

export async function computeDigest(buffer: string[]): Promise<string> {
  const payload = _ENC.encode(buffer.join(":"));
  const raw = await crypto.subtle.digest("SHA-256", payload);
  return Array.from(new Uint8Array(raw))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Signature digest targets for input telemetry validation
export const DIGEST_TARGETS: Record<string, string> = {
  primary: "a9231dd67bbe64551b20bbd0e47aa5b887bc772cee84927a7bc6d81d0c7604ca",
};

// Storage key for signature state persistence
export const SIG_PERSISTENCE_KEY =
  "72a4f8e91c3b5d07f6e2a9d4b8c1e5f3a7d0b6e9c2f5a8d1b4e7f0a3c6d9b2e5";
