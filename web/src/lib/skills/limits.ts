/**
 * Per-user Skill limit contract; mirrors `backend/onyx/skills/limits.py`.
 */

import * as yup from "yup";
import type { useFormatter } from "next-intl";
import { FetchError } from "@/lib/fetcher";

const count = yup.number().integer().min(0).defined();

const skillLimitKind = yup
  .string<SkillLimitKind>()
  .oneOf(["bytes", "files"])
  .defined();

export type SkillLimitKind = "bytes" | "files";

/** `bytes`/`files` are measured; `charged_*` add an allowance per unmeasured Skill. */
export const skillUsageSummarySchema = yup
  .object({
    bytes: count,
    files: count,
    unknown_skill_count: count,
    charged_bytes: count,
    charged_files: count,
    max_bytes: count,
    max_files: count,
  })
  .defined();

export type SkillUsageSummary = yup.InferType<typeof skillUsageSummarySchema>;

/** `usage` is present only when the requesting user goes over. */
export const skillLimitViolationSchema = yup
  .object({
    failed_limit: skillLimitKind,
    affected_user_count: yup.number().integer().min(1).defined(),
    usage: skillUsageSummarySchema.nullable().defined(),
  })
  .defined();

export type SkillLimitViolation = yup.InferType<
  typeof skillLimitViolationSchema
>;

export const skillLimitUserUsageSchema = yup
  .object({
    user: yup
      .object({ id: yup.string().defined(), email: yup.string().defined() })
      .defined(),
    usage: skillUsageSummarySchema,
    // Null: no successful delivery is recorded, which is not zero omissions.
    last_delivery_omitted_skill_count: count.nullable(),
  })
  .defined();

export type SkillLimitUserUsage = yup.InferType<
  typeof skillLimitUserUsageSchema
>;

export const skillLimitUsersSchema = yup
  .array(skillLimitUserUsageSchema)
  .defined();

/** A structured Skill limit from untrusted data; null when absent or malformed. */
export function parseSkillLimitViolation(
  // oxlint-disable-next-line anti-slop/no-unknown-parameters -- This is the boundary parser for response JSON.
  value: unknown
): SkillLimitViolation | null {
  if (value === null || value === undefined) return null;
  try {
    return skillLimitViolationSchema.validateSync(value, { strict: true });
  } catch {
    return null;
  }
}

/** The structured Skill limit of a refused write; null for any other error. */
export function skillLimitViolationOf(
  error: unknown
): SkillLimitViolation | null {
  if (
    !(error instanceof FetchError) ||
    error.status !== 413 ||
    error.info?.error_code !== "PAYLOAD_TOO_LARGE"
  ) {
    return null;
  }
  return parseSkillLimitViolation(error.info.skill_limit);
}

const BYTE_UNITS = ["B", "KiB", "MiB", "GiB"] as const;

/** Localized numbers with binary units that match the byte limits. */
export function formatSkillSize(
  format: ReturnType<typeof useFormatter>,
  bytes: number
): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${format.number(value, { maximumFractionDigits: 1 })} ${BYTE_UNITS[unit]}`;
}
