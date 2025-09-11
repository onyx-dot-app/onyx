import i18n from "@/i18n/init";
import k from "./../../../../../i18n/keys";
import { AdminPageTitle } from "@/components/admin/Title";
import { CUSTOM_ANALYTICS_ENABLED } from "@/lib/constants";
import { Callout } from "@/components/ui/callout";
import { FiBarChart2 } from "react-icons/fi";
import Text from "@/components/ui/text";
import { CustomAnalyticsUpdateForm } from "./CustomAnalyticsUpdateForm";

function Main() {
  if (!CUSTOM_ANALYTICS_ENABLED) {
    return (
      <div>
        <div className="mt-4">
          <Callout type="danger" title={i18n.t(k.CUSTOM_ANALYTICS_NOT_ENABLED)}>
            {i18n.t(k.TO_SET_UP_CUSTOM_ANALYTICS_SCR)}{" "}
            <i>{i18n.t(k.CUSTOM_ANALYTICS_SECRET_KEY)}</i>{" "}
            {i18n.t(k.ENVIRONMENT_VARIABLE)}
          </Callout>
        </div>
      </div>
    );
  }

  return (
    <div>
      <Text className="mb-8">{i18n.t(k.THIS_ALLOWS_YOU_TO_BRING_YOUR)}</Text>

      <CustomAnalyticsUpdateForm />
    </div>
  );
}

export default function Page() {
  return (
    <main className="pt-4 mx-auto container">
      <AdminPageTitle
        title={i18n.t(k.CUSTOM_ANALYTICS_TITLE)}
        icon={<FiBarChart2 size={32} />}
      />

      <Main />
    </main>
  );
}
