import { SettingsLayouts } from "@opal/layouts";
import { CUSTOM_ANALYTICS_ENABLED } from "@/lib/constants";
import { Callout } from "@/components/ui/callout";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Text } from "@opal/components";
import { Spacer } from "@opal/components";
import { CustomAnalyticsUpdateForm } from "./CustomAnalyticsUpdateForm";

const route = ADMIN_ROUTES.CUSTOM_ANALYTICS;

function Main() {
  if (!CUSTOM_ANALYTICS_ENABLED) {
    return (
      <div>
        <div className="mt-4">
          <Callout type="danger" title="Custom Analytics is not enabled.">
            To set up custom analytics scripts, please work with the team who
            setup Glomi AI in your team to set the{" "}
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
          "你可以把自己的分析工具接入 Glomi AI。将分析服务商提供的 Web snippet 粘贴到下方输入框后，我们会开始发送使用事件。"
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
      <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
