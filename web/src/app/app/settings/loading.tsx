import { PageLoader } from "@opal/loaders";

/**
 * Shown inside the settings layout (its header and tabs) the moment a
 * settings page is opened, while the page renders. The same loader
 * `SettingsLayouts.Body` shows while its root is `loading`.
 */
export default function Loading() {
  return <PageLoader />;
}
