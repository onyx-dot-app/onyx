"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { REGISTRATION_URL } from "@/lib/constants";
import { Button } from "@opal/components";
import Link from "next/link";
import { SvgImport } from "@opal/icons";
import { useTranslations } from "next-intl";

export default function Page() {
  const t = useTranslations("auth.accountNotFound");

  return (
    <AuthFlowContainer>
      <div className="flex flex-col space-y-6">
        <h2 className="text-2xl font-bold text-text-900 text-center">
          {t("title")}
        </h2>
        <p className="text-text-700 max-w-md text-center">
          {t("description")}
        </p>
        <ul className="list-disc text-left text-text-600 w-full pl-6 mx-auto">
          <li>{t("invite")}</li>
          <li>{t("createTeam")}</li>
        </ul>
        <div className="flex justify-center">
          <Button
            href={`${REGISTRATION_URL}/register`}
            width="full"
            icon={SvgImport}
          >
            {t("createOrganization")}
          </Button>
        </div>
        <p className="text-sm text-text-500 text-center">
          {t("differentEmail")}{" "}
          <Link
            href="/auth/login"
            className="text-action-link-05 hover:underline"
          >
            {t("signIn")}
          </Link>
        </p>
      </div>
    </AuthFlowContainer>
  );
}
