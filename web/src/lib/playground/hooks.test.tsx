/**
 * @jest-environment jsdom
 */
import { renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import englishMessages from "@/i18n/messages/en.json";
import {
  usePlaygroundRestriction,
  usePlaygroundRestrictions,
} from "@/lib/playground/hooks";
import { PlaygroundRestrictedFeature } from "@/lib/playground/types";
import { useSettings } from "@/lib/settings/hooks";
import { Tier } from "@/lib/tiers/types";

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: jest.fn(),
}));

const mockUseSettings = useSettings as jest.MockedFunction<typeof useSettings>;

function stubRestrictions(
  restrictions: PlaygroundRestrictedFeature[] | undefined
) {
  mockUseSettings.mockReturnValue({
    playground_restrictions: restrictions,
  } as ReturnType<typeof useSettings>);
}

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      {children}
    </NextIntlClientProvider>
  );
}

// ---------------------------------------------------------------------------
// usePlaygroundRestrictions
// ---------------------------------------------------------------------------

test("is empty when the server reports no restrictions", () => {
  stubRestrictions(undefined);
  const { result } = renderHook(() => usePlaygroundRestrictions(), { wrapper });
  expect(result.current.size).toBe(0);
});

test("holds what the server reports", () => {
  stubRestrictions([
    PlaygroundRestrictedFeature.SSO,
    PlaygroundRestrictedFeature.LLM_GATEWAY,
  ]);
  const { result } = renderHook(() => usePlaygroundRestrictions(), { wrapper });
  expect(result.current.has(PlaygroundRestrictedFeature.SSO)).toBe(true);
  expect(result.current.has(PlaygroundRestrictedFeature.SCIM)).toBe(false);
});

// ---------------------------------------------------------------------------
// usePlaygroundRestriction
// ---------------------------------------------------------------------------

test("an Enterprise-only feature is restricted with the Enterprise plan", () => {
  stubRestrictions([PlaygroundRestrictedFeature.SSO]);
  const { result } = renderHook(
    () => usePlaygroundRestriction(PlaygroundRestrictedFeature.SSO),
    {
      wrapper,
    }
  );
  expect(result.current.restricted).toBe(true);
  expect(result.current.plan).toBe(Tier.ENTERPRISE);
  expect(result.current.title).toBe("Playground Limit");
  expect(result.current.tooltip).toContain("Not available on the playground");
});

test("a switched-off feature is restricted without a plan badge", () => {
  stubRestrictions([PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS]);
  const { result } = renderHook(
    () =>
      usePlaygroundRestriction(
        PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS
      ),
    { wrapper }
  );
  expect(result.current.restricted).toBe(true);
  expect(result.current.plan).toBeUndefined();
});

test("a feature the server does not list is not restricted", () => {
  stubRestrictions([PlaygroundRestrictedFeature.SSO]);
  const { result } = renderHook(
    () => usePlaygroundRestriction(PlaygroundRestrictedFeature.SCIM),
    {
      wrapper,
    }
  );
  expect(result.current.restricted).toBe(false);
});

test("a surface without a feature key is never restricted", () => {
  stubRestrictions([
    PlaygroundRestrictedFeature.SSO,
    PlaygroundRestrictedFeature.SCIM,
  ]);
  const { result } = renderHook(() => usePlaygroundRestriction(undefined), {
    wrapper,
  });
  expect(result.current.restricted).toBe(false);
  expect(result.current.plan).toBeUndefined();
});
