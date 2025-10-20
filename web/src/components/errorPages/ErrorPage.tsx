import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import Text from "@/refresh-components/texts/Text";
import SvgAlertCircle from "@/icons/alert-circle";

export default function Error() {
  return (
    <ErrorPageLayout>
      <div className="flex flex-row items-center gap-spacing-interline">
        <Text headingH2>We encountered an issue</Text>
        <SvgAlertCircle className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
      </div>

      <Text text03>
        It seems there was a problem loading your Onyx settings. This could be
        due to a configuration issue or incomplete setup.
      </Text>

      <Text text03>
        If you&apos;re an admin, please review our{" "}
        <a
          className="text-action-link-05"
          href="https://docs.onyx.app/?utm_source=app&utm_medium=error_page&utm_campaign=config_error"
          target="_blank"
          rel="noopener noreferrer"
        >
          documentation
        </a>{" "}
        for proper configuration steps. If you&apos;re a user, please contact
        your admin for assistance.
      </Text>

      <Text text03>
        Need help? Join our{" "}
        <a
          className="text-action-link-05"
          href="https://discord.gg/4NA5SbzrWb"
          target="_blank"
          rel="noopener noreferrer"
        >
          Discord community
        </a>{" "}
        for support.
      </Text>
    </ErrorPageLayout>
  );
}
