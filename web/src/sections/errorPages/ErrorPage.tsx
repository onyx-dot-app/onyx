import { AuthLayouts } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { DOCS_BASE_URL } from "@/lib/constants";
import { useSettings } from "@/lib/settings/hooks";

export default function ErrorPage() {
  const { logoUrl } = useSettings();

  return (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        title="We encountered an issue"
        description="There was a problem loading your Onyx settings. This could be due to a configuration issue or incomplete setup."
        logoSrc={logoUrl}
      >
        <AuthLayouts.Message
          messageType="warning"
          title="Unable to load settings"
          description={markdown(
            `If you're an admin, please review our [documentation](${DOCS_BASE_URL}?utm_source=app&utm_medium=error_page&utm_campaign=config_error) for proper configuration steps. If you're a user, please contact your admin for assistance.`,
            "Need help? Join our [Discord community](https://discord.gg/4NA5SbzrWb) for support."
          )}
        />
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  );
}
