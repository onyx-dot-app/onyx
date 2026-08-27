"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { REGISTRATION_URL } from "@/lib/constants";
import { Button } from "@opal/components";
import Link from "next/link";
import { SvgImport } from "@opal/icons";
import { useTranslations } from "next-intl";

export default function Page() {
  const t = useTranslations("auth");

  return (
    <AuthFlowContainer>
      <div className="flex flex-col space-y-6">
        <h2 className="text-2xl font-bold text-text-900 text-center">
          {t("createAccount.heading.title")}
        </h2>
        <p className="text-text-700 max-w-md text-center">
          {t("createAccount.notFound.description")}
        </p>
        <ul className="list-disc text-left text-text-600 w-full pl-6 mx-auto">
          <li>{t("createAccount.inviteOption.text")}</li>
          <li>{t("createAccount.createTeamOption.text")}</li>
        </ul>
        <div className="flex justify-center">
          <Button
            href={`${REGISTRATION_URL}/register`}
            width="full"
            icon={SvgImport}
          >
            {t("createAccount.createOrgButton.label")}
          </Button>
        </div>
        <p className="text-sm text-text-500 text-center">
          {t("createAccount.differentEmailPrompt.text")}{" "}
          <Link
            href="/auth/login"
            className="text-action-selection-05 hover:underline"
          >
            {t("createAccount.signInLink.label")}
          </Link>
        </p>
      </div>
    </AuthFlowContainer>
  );
}
