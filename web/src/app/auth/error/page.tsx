"use client";
import i18n from "@/i18n/init";
import k from "@/i18n/keys";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { FiLogIn } from "react-icons/fi";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useTranslation } from "@/hooks/useTranslation";

const Page = () => {
  const { t } = useTranslation();
  return (
    <AuthFlowContainer>
      <div className="flex flex-col space-y-6 max-w-md mx-auto">
        <h2 className="text-2xl font-bold text-text-900 text-center">
          {t(k.AUTHENTICATION_ERROR)}
        </h2>
        <p className="text-text-700 text-center">
          {t(k.WE_ENCOUNTERED_AN_ISSUE_WHILE)}
        </p>
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg p-4 shadow-sm">
          <h3 className="text-red-800 dark:text-red-400 font-semibold mb-2">
            {t(k.POSSIBLE_ISSUES)}
          </h3>
          <ul className="space-y-2">
            <li className="flex items-center text-red-700 dark:text-red-400">
              <div className="w-2 h-2 bg-red-500 dark:bg-red-400 rounded-full mr-2"></div>
              {t(k.INCORRECT_OR_EXPIRED_LOGIN_CRE)}
            </li>
            <li className="flex items-center text-red-700 dark:text-red-400">
              <div className="w-2 h-2 bg-red-500 dark:bg-red-400 rounded-full mr-2"></div>
              {t(k.TEMPORARY_AUTHENTICATION_SYSTE)}
            </li>
            <li className="flex items-center text-red-700 dark:text-red-400">
              <div className="w-2 h-2 bg-red-500 dark:bg-red-400 rounded-full mr-2"></div>
              {t(k.ACCOUNT_ACCESS_RESTRICTIONS_OR)}
            </li>
          </ul>
        </div>

        <Link href="/auth/login" className="w-full">
          <Button size="lg" icon={FiLogIn} className="w-full">
            {t(k.RETURN_TO_LOGIN_PAGE)}
          </Button>
        </Link>
        <p className="text-sm text-text-500 text-center">
          {t(k.WE_RECOMMEND_TRYING_AGAIN_IF)}

          {NEXT_PUBLIC_CLOUD_ENABLED && (
            <span className="block mt-1 text-blue-600">
              {t(k.A_MEMBER_OF_OUR_TEAM_HAS_BEEN)}
            </span>
          )}
        </p>
      </div>
    </AuthFlowContainer>
  );
};

export default Page;
