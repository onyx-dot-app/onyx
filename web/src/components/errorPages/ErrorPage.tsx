import ErrorPageLayout from "./ErrorPageLayout";
import Text from "@/refresh-components/texts/Text";
import SvgAlertCircle from "@/icons/alert-circle";

export default function Error() {
  return (
    <ErrorPageLayout>
      <div className="flex items-center gap-2 mb-4 ">
        <Text headingH2 inverted>
          We encountered an issue
        </Text>
        <SvgAlertCircle className="w-[1.5rem] h-[1.5rem] stroke-text-inverted-04" />
      </div>
      <div className="space-y-4 text-gray-600 dark:text-gray-300">
        <Text inverted>
          It seems there was a problem loading your Onyx settings. This could be
          due to a configuration issue or incomplete setup.
        </Text>
        <Text inverted>
          If you&apos;re an admin, please review our{" "}
          <a
            className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            href="https://docs.onyx.app/?utm_source=app&utm_medium=error_page&utm_campaign=config_error"
            target="_blank"
            rel="noopener noreferrer"
          >
            documentation
          </a>{" "}
          for proper configuration steps. If you&apos;re a user, please contact
          your admin for assistance.
        </Text>
        <Text inverted>
          Need help? Join our{" "}
          <a
            className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            href="https://discord.gg/4NA5SbzrWb"
            target="_blank"
            rel="noopener noreferrer"
          >
            Discord community
          </a>{" "}
          for support.
        </Text>
      </div>
    </ErrorPageLayout>
  );
}
