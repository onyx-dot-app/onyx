"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../i18n/keys";
import { FiAlertCircle } from "react-icons/fi";
import ErrorPageLayout from "./ErrorPageLayout";

export default function Error() {
  const { t } = useTranslation();
  return (
    <ErrorPageLayout>
      <h1 className="text-2xl font-semibold flex items-center gap-2 mb-4 text-gray-800 dark:text-gray-200">
        <p className=""> {t(k.WE_ENCOUNTERED_AN_ISSUE)}</p>
        <FiAlertCircle className="text-error inline-block" />
      </h1>
      <div className="space-y-4 text-gray-600 dark:text-gray-300">
        <p>{t(k.IT_SEEMS_THERE_WAS_A_PROBLEM_L)}</p>
        <p>
          {t(k.IF_YOU_RE_AN_ADMIN_PLEASE_REV)}{" "}
          <a
            className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            href="https://docs.onyx.app/introduction?utm_source=app&utm_medium=error_page&utm_campaign=config_error"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t(k.DOCUMENTATION)}
          </a>{" "}
          {t(k.FOR_PROPER_CONFIGURATION_STEPS)}
        </p>
        <p>
          {t(k.NEED_HELP_JOIN_OUR)}{" "}
          <a
            className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            href="https://join.slack.com/t/danswer/shared_invite/zt-1w76msxmd-HJHLe3KNFIAIzk_0dSOKaQ"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t(k.SLACK_COMMUNITY)}
          </a>{" "}
          {t(k.FOR_SUPPORT1)}
        </p>
      </div>
    </ErrorPageLayout>
  );
}
