// The app router is not mounted in tests, and every link and navigation goes
// through `@opal/navigation`, which reads it. `jest.setup.ts` mocks
// `next/navigation` with these; a test that mocks it itself spreads them
// first and overrides what it needs.
export const nextNavigationMock = {
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    prefetch: jest.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  useSelectedLayoutSegment: () => null,
  useSelectedLayoutSegments: () => [],
};
