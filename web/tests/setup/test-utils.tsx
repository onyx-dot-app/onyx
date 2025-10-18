import React, { ReactElement } from "react";
import { render, RenderOptions } from "@testing-library/react";
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
export { default as userEvent } from "@testing-library/user-event";

// Override render with our custom render
export { customRender as render };

// Re-export all test helpers and API mocks for convenience
export * from "./test-helpers";
export * from "./api-mocks";
