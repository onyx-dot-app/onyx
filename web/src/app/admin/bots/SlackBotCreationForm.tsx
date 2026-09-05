"use client";

import CardSection from "@/components/admin/CardSection";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { SlackTokensForm } from "./SlackTokensForm";
import { SettingsLayouts } from "@opal/layouts";
import { SvgSlack } from "@opal/logos";

export function NewSlackBotForm() {
  const t = useTranslations("admin.slackBots");
  const [formValues] = useState({
    name: "",
    enabled: true,
    bot_token: "",
    app_token: "",
    user_token: "",
  });
  const router = useRouter();

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSlack}
        title={t("newBot.header.title")}
        divider
        backButton
      />
      <SettingsLayouts.Body>
        <CardSection>
          <div className="p-4">
            <SlackTokensForm
              isUpdate={false}
              initialValues={formValues}
              router={router}
            />
          </div>
        </CardSection>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
