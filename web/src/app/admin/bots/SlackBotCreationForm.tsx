"use client";

import CardSection from "@/components/admin/CardSection";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { SlackTokensForm } from "./SlackTokensForm";
import { SourceIcon } from "@/components/SourceIcon";
import { AdminPageTitle } from "@/components/admin/Title";
import { ValidSources } from "@/lib/types";

export const NewSlackBotForm = () => {
  const [formValues] = useState({
    name: "",
    enabled: true,
    bot_token: "",
    app_token: "",
    user_token: "",
  });
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  return (
    <div>
      <AdminPageTitle
        icon={<SourceIcon iconSize={36} sourceType={ValidSources.Slack} />}
        title="New Slack Bot"
      />
      <CardSection>
        {popup}
        <div className="p-4">
          <SlackTokensForm
            isUpdate={false}
            initialValues={formValues}
            setPopup={setPopup}
            router={router}
          />
        </div>
      </CardSection>
    </div>
  );
};
