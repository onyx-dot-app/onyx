/**
 * @jest-environment jsdom
 */
import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import { renderHook } from "@tests/setup/test-utils";
import englishMessages from "@/i18n/messages/en.json";
import { FetchError } from "@/lib/fetcher";
import { setSkillEnabled } from "@/lib/skills/api";
import {
  skillLimitOf,
  useSkillLimitCopy,
  type SkillLimitDetails,
} from "@/lib/skills/limits";

const MB = 1024 * 1024;
const LIMITS = { max_bytes: 500 * MB, max_files: 5000 };

function body(limit: SkillLimitDetails) {
  return {
    error_code: "SKILL_LIMIT_EXCEEDED",
    detail: "This would put your skills past the limit.",
    skill_limit: limit,
  };
}

function IntlWrapper({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      {children}
    </NextIntlClientProvider>
  );
}

function copy() {
  return renderHook(() => useSkillLimitCopy(), { wrapper: IntlWrapper }).result
    .current;
}

describe("skill limit refusals", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("tells a user the limit from a skills API error", async () => {
    const limit: SkillLimitDetails = {
      ...LIMITS,
      users_over: 2,
      usage: { bytes: 600 * MB, files: 30 },
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 413,
      json: async () => body(limit),
    } as Response);

    const error = await setSkillEnabled("skill-1", true).catch(
      (caught: unknown) => caught
    );

    expect(skillLimitOf(error)).toEqual(limit);
    expect(copy().describeError(error, "fallback")).toBe(
      "This change puts you past the skill limit of 500 MB or 5,000 files. Turn off skills you do not use, then try again."
    );
  });

  it("tells an admin the number of users from a FetchError", () => {
    const limit: SkillLimitDetails = { ...LIMITS, users_over: 3, usage: null };
    const error = new FetchError("Request failed", 413, body(limit));
    expect(copy().describeError(error, "fallback")).toBe(
      "This change puts 3 users past the skill limit of 500 MB or 5,000 files. Choose a narrower setting, or ask them to turn off skills."
    );
  });
});
