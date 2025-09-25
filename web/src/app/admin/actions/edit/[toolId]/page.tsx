"use client";
import React, { useEffect, useState } from "react";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../../i18n/keys";
import { ErrorCallout } from "@/components/ErrorCallout";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import CardSection from "@/components/admin/CardSection";
import { ActionEditor } from "@/app/admin/actions/ActionEditor";
import { fetchToolById } from "@/lib/tools/fetchToolsClient";
import { DeleteToolButton } from "./DeleteToolButton";
import { AdminPageTitle } from "@/components/admin/Title";
import { BackButton } from "@/components/BackButton";
import { ToolIcon } from "@/components/icons/icons";
import { ToolSnapshot } from "@/lib/tools/interfaces";

export default function Page({
  params,
}: {
  params: Promise<{ toolId: string }>;
}) {
  const { t } = useTranslation();
  const [tool, setTool] = useState<ToolSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toolId, setToolId] = useState<string | null>(null);

  useEffect(() => {
    const getParams = async () => {
      const resolvedParams = await params;
      setToolId(resolvedParams.toolId);
    };
    getParams();
  }, [params]);

  useEffect(() => {
    if (!toolId) return;

    const loadTool = async () => {
      try {
        const fetchedTool = await fetchToolById(toolId);
        setTool(fetchedTool);
      } catch (err) {
        setError("Failed to load tool");
      } finally {
        setLoading(false);
      }
    };
    loadTool();
  }, [toolId]);

  if (loading) {
    return <div>Loading...</div>;
  }

  let body;
  if (error || !tool) {
    body = (
      <div>
        <ErrorCallout
          errorTitle={t(k.SOMETHING_WENT_WRONG)}
          errorMsg={error || "Tool not found"}
        />
      </div>
    );
  } else {
    body = (
      <div className="w-full my-8">
        <div>
          <div>
            <CardSection>
              <ActionEditor tool={tool} />
            </CardSection>

            <Title className="mt-12">{t(k.DELETE_TOOL)}</Title>
            <Text>{t(k.CLICK_THE_BUTTON_BELOW_TO_PERM)}</Text>
            <div className="flex mt-6">
              <DeleteToolButton toolId={tool.id} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto container">
      <BackButton />

      <AdminPageTitle
        title={t(k.EDIT_TOOL)}
        icon={<ToolIcon size={32} className="my-auto" />}
      />

      {body}
    </div>
  );
}
