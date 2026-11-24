/**
 * @jest-environment jsdom
 */
import { renderHook } from "@testing-library/react";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { NextIntlClientProvider } from "next-intl";
import englishMessages from "@/i18n/messages/en.json";
import {
  usePlaygroundRestriction,
  usePlaygroundRestrictions,
} from "@/lib/playground/hooks";
import {
  PlaygroundRestrictedFeature,
  PlaygroundRestrictionReason,
} from "@/lib/playground/types";
import { useSettings } from "@/lib/settings/hooks";

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

test("an Enterprise-only feature is restricted with the Enterprise reason", () => {
  stubRestrictions([PlaygroundRestrictedFeature.SSO]);
  const { result } = renderHook(
    () => usePlaygroundRestriction(PlaygroundRestrictedFeature.SSO),
    {
      wrapper,
    }
  );
  expect(result.current.restricted).toBe(true);
  expect(result.current.reason).toBe(PlaygroundRestrictionReason.ENTERPRISE);
  expect(result.current.title).toBe("Playground Limit");
  expect(toPlainString(result.current.description)).toContain(
    "Enterprise feature"
  );
  expect(result.current.tooltip).toContain("Not available on the playground");
});

test("a switched-off feature says it is off on the playground", () => {
  stubRestrictions([PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS]);
  const { result } = renderHook(
    () =>
      usePlaygroundRestriction(
        PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS
      ),
    { wrapper }
  );
  expect(result.current.restricted).toBe(true);
  expect(result.current.reason).toBe(PlaygroundRestrictionReason.SWITCHED_OFF);
  expect(toPlainString(result.current.description)).toContain("switched off");
});

test("the model pages say the playground runs on our keys", () => {
  stubRestrictions([PlaygroundRestrictedFeature.LLM_PROVIDERS]);
  const { result } = renderHook(
    () => usePlaygroundRestriction(PlaygroundRestrictedFeature.LLM_PROVIDERS),
    { wrapper }
  );
  expect(result.current.reason).toBe(PlaygroundRestrictionReason.OWN_KEYS);
  expect(toPlainString(result.current.description)).toContain(
    "our own model keys"
  );
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
  expect(result.current.reason).toBeUndefined();
});
