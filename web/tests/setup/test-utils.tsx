import React, { ReactElement } from "react";
import { render, RenderOptions } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SWRConfig } from "swr";

/**
 * Custom render function that wraps components with common providers
 * used throughout the Onyx application.
 */

interface AllProvidersProps {
  children: React.ReactNode;
  swrConfig?: Record<string, any>;
}

/**
 * Wrapper component that provides all necessary context providers for tests.
 * Customize this as needed when you discover more global providers in the app.
 */
function AllTheProviders({ children, swrConfig = {} }: AllProvidersProps) {
  return (
    <SWRConfig
      value={{
        // Disable deduping in tests to ensure each test gets fresh data
        dedupingInterval: 0,
        // Use a Map instead of cache to avoid state leaking between tests
        provider: () => new Map(),
        // Disable error retries in tests for faster failures
        shouldRetryOnError: false,
        // Merge any custom SWR config passed from tests
        ...swrConfig,
      }}
    >
      {children}
    </SWRConfig>
  );
}

interface CustomRenderOptions extends Omit<RenderOptions, "wrapper"> {
  swrConfig?: Record<string, any>;
}

/**
 * Custom render function that wraps the component with all providers.
 * Use this instead of @testing-library/react's render in your tests.
 *
 * @example
 * import { render, screen } from '@tests/setup/test-utils';
 *
 * test('renders component', () => {
 *   render(<MyComponent />);
 *   expect(screen.getByText('Hello')).toBeInTheDocument();
 * });
 *
 * @example
 * // With custom SWR config to mock API responses
 * render(<MyComponent />, {
 *   swrConfig: {
 *     fallback: {
 *       '/api/credentials': mockCredentials,
 *     },
 *   },
 * });
 */
const customRender = (
  ui: ReactElement,
  { swrConfig, ...options }: CustomRenderOptions = {}
) => {
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <AllTheProviders swrConfig={swrConfig}>{children}</AllTheProviders>
  );

  return render(ui, { wrapper: Wrapper, ...options });
};

// Re-export everything from @testing-library/react
export * from "@testing-library/react";
export { userEvent };

// Override render with our custom render
export { customRender as render };

/**
 * Setup userEvent with optimized configuration for testing.
 * All user interactions are automatically wrapped in act() to prevent warnings.
 * Use this helper instead of userEvent.setup() directly.
 *
 * @example
 * const user = setupUser();
 * await user.click(button);
 * await user.type(input, "text");
 */
export function setupUser(options = {}) {
  const baseUser = userEvent.setup({
    // Configure for React 18 to reduce act warnings
    delay: null, // Instant typing - batches state updates better
    ...options,
  });

  // Wrap all user-event methods in act() to prevent act warnings. We add this here
  // to prevent all callsites from needing to import and wrap user events in act()
  return new Proxy(baseUser, {
    get(target, prop) {
      const value = target[prop as keyof typeof target];

      // Only wrap methods (functions), not properties
      if (typeof value === "function") {
        return async (...args: any[]) => {
          const { act } = await import("@testing-library/react");
          return act(async () => {
            return (value as Function).apply(target, args);
          });
        };
      }

      return value;
    },
  });
}
