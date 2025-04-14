import i18n from "i18next";
import k from "./../../i18n/keys";
import { FiAlertCircle } from "react-icons/fi";
import ErrorPageLayout from "./ErrorPageLayout";

export default function Error() {
  return (
    <ErrorPageLayout>
      <h1 className="text-2xl font-semibold flex items-center gap-2 mb-4 text-gray-800 dark:text-gray-200">
        <p className=""> {i18n.t(k.WE_ENCOUNTERED_AN_ISSUE)}</p>
        <FiAlertCircle className="text-error inline-block" />
      </h1>
      <div className="space-y-4 text-gray-600 dark:text-gray-300">
        <p>{i18n.t(k.IT_SEEMS_THERE_WAS_A_PROBLEM_L)}</p>
        <p>
          {i18n.t(k.IF_YOU_RE_AN_ADMIN_PLEASE_REV)}{" "}
          <a
            className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            href="https://docs.onyx.app/introduction?utm_source=app&utm_medium=error_page&utm_campaign=config_error"
            target="_blank"
            rel="noopener noreferrer"
          >
            {i18n.t(k.DOCUMENTATION)}
          </a>{" "}
          {i18n.t(k.FOR_PROPER_CONFIGURATION_STEPS)}
        </p>
        <p>
          {i18n.t(k.NEED_HELP_JOIN_OUR)}{" "}
          <a
            className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            href="https://join.slack.com/t/danswer/shared_invite/zt-1w76msxmd-HJHLe3KNFIAIzk_0dSOKaQ"
            target="_blank"
            rel="noopener noreferrer"
          >
            {i18n.t(k.SLACK_COMMUNITY)}
          </a>{" "}
          {i18n.t(k.FOR_SUPPORT1)}
        </p>
      </div>
    </ErrorPageLayout>
  );
}
