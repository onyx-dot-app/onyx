import { FiAlertCircle } from "react-icons/fi";
import ErrorPageLayout from "./ErrorPageLayout";

export default function Error() {
  return (
    <ErrorPageLayout>
      <h1 className="text-2xl font-semibold flex items-center gap-2 mb-4 text-gray-800 dark:text-gray-200">
        <p className=""> We encountered an issue</p>
        <FiAlertCircle className="text-error inline-block" />
      </h1>
      <div className="space-y-4 text-gray-600 dark:text-gray-300">
        <p>
          It seems there was a problem loading your Onyx settings. This could be
          due to a configuration issue or incomplete setup.
        </p>
        <p>
          If you&apos;re an admin, please review our{" "}
          <a
            className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            href="https://docs.onyx.app/introduction?utm_source=app&utm_medium=error_page&utm_campaign=config_error"
            target="_blank"
            rel="noopener noreferrer"
          >
            documentation
          </a>{" "}
          for proper configuration steps. If you&apos;re a user, please contact
          your admin for assistance.
        </p>
        <p>
          Need help? Join our{" "}
          <a
            className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            href="https://join.slack.com/t/danswer/shared_invite/zt-1w76msxmd-HJHLe3KNFIAIzk_0dSOKaQ"
            target="_blank"
            rel="noopener noreferrer"
          >
            Slack community
          </a>{" "}
          for support.
        </p>
      </div>
    </ErrorPageLayout>
  );
}
