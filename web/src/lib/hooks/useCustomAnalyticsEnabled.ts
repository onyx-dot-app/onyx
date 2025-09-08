import { CUSTOM_ANALYTICS_ENABLED } from "@/lib/constants";

export type CustomAnalyticsStatus = {
  customAnalyticsEnabled: boolean;
  isLoading: boolean;
};

/**
 * Hook to check if custom analytics is enabled.
 * Returns the status and loading state for consistency with other hooks.
 * Since this is based on an environment variable, there's no actual loading state.
 */
export function useCustomAnalyticsEnabled(): CustomAnalyticsStatus {
  return {
    customAnalyticsEnabled: CUSTOM_ANALYTICS_ENABLED,
    isLoading: false,
  };
}
