"use client";
import React, { useEffect, useState } from "react";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
import { ActionsTable } from "./ActionTable";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { FiPlusSquare } from "react-icons/fi";
import Link from "next/link";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { ErrorCallout } from "@/components/ErrorCallout";
import { AdminPageTitle } from "@/components/admin/Title";
import { ToolIcon } from "@/components/icons/icons";
import CreateButton from "@/components/ui/createButton";
import { fetchTools } from "@/lib/tools/fetchToolsClient";

export default function Page() {
  const { t } = useTranslation();
  const [tools, setTools] = useState<ToolSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadTools = async () => {
      try {
        const fetchedTools = await fetchTools();
        if (fetchedTools) {
          setTools(fetchedTools);
        } else {
          setError("Failed to load tools");
        }
      } catch (err) {
        setError("Failed to load tools");
      } finally {
        setLoading(false);
      }
    };
    loadTools();
  }, []);

  if (loading) {
    return <div>Loading...</div>;
  }

  if (error) {
    return (
      <ErrorCallout errorTitle={t(k.SOMETHING_WENT_WRONG)} errorMsg={error} />
    );
  }

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<ToolIcon size={32} className="my-auto" />}
        title={t(k.TOOLS)}
      />

      <Text className="mb-2">{t(k.ACTIONS_ALLOW_ASSISTANTS_TO_RE)}</Text>

      <div>
        <Separator />

        <Title>{t(k.CREATE_AN_ACTION)}</Title>
        <CreateButton href="/admin/actions/new" text={t(k.NEW_TOOL)} />

        <Separator />

        <Title>{t(k.EXISTING_ACTIONS)}</Title>
        <ActionsTable tools={tools} />
      </div>
    </div>
  );
}
