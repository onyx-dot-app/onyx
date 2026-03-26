import * as SettingsLayouts from "@/layouts/settings-layouts";
import { CUSTOM_ANALYTICS_ENABLED } from "@/lib/constants";
import { Callout } from "@/components/ui/callout";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Text } from "@opal/components";
import Spacer from "@/refresh-components/Spacer";
import { CustomAnalyticsUpdateForm } from "./CustomAnalyticsUpdateForm";

const route = ADMIN_ROUTES.CUSTOM_ANALYTICS;

function Main() {
  if (!CUSTOM_ANALYTICS_ENABLED) {
    return (
      <div>
        <div className="mt-4">
          <Callout type="danger" title="Custom Analytics is not enabled.">
            To set up custom analytics scripts, please work with the team who
            setup Onyx in your team to set the{" "}
            <i>CUSTOM_ANALYTICS_SECRET_KEY</i> environment variable.
          </Callout>
        </div>
      </div>
    );
  }

  return (
    <div>
      <Text as="p">
        {
          "This allows you to bring your own analytics tool to Onyx! Copy the Web snippet from your analytics provider into the box below, and we'll start sending usage events."
        }
      </Text>
      <Spacer rem={2} />

      <CustomAnalyticsUpdateForm />
    </div>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
