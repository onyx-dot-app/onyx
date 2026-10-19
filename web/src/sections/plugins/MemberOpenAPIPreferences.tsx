"use client";

import { useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { useTranslations } from "next-intl";
import { InputSwitch, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { saveMemberOpenAPIPreferences } from "@/lib/plugins/member";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ToolSnapshot } from "@/lib/tools/types";

interface MemberOpenAPIPreferencesProps {
  tool: ToolSnapshot;
}

export default function MemberOpenAPIPreferences({
  tool,
}: MemberOpenAPIPreferencesProps) {
  const t = useTranslations("actions.memberPlugins.defaults");
  const availabilityCopy = useTranslations("actions.plugins.availability");
  const { mutate } = useSWRConfig();
  const { data, mutate: mutateTools } = useSWR<ToolSnapshot[]>(
    SWR_KEYS.tools,
    null,
    { revalidateOnMount: false }
  );
  const current = data?.find((item) => item.id === tool.id) ?? tool;
  const available = current.default_chat_enabled === true;
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const saving = useRef(false);

  async function save(enabled: boolean) {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setFailed(false);
    try {
      if (!data) await mutateTools((loaded) => loaded ?? [tool], false);
      await saveMemberOpenAPIPreferences(
        current.id,
        { enabled_in_chat: enabled },
        mutate
      );
    } catch {
      setFailed(true);
    } finally {
      saving.current = false;
      setPending(false);
    }
  }

  return (
    <Section padding={0} gap={4} alignItems="stretch" height="auto">
      <div className="flex items-start justify-between gap-4">
        <Content
          title={t("chat")}
          description={
            available
              ? t("chatDescription")
              : t("unavailable", { surface: availabilityCopy("mainChat") })
          }
          sizePreset="main-ui"
          variant="section"
        />
        <InputSwitch
          aria-label={t("chat")}
          checked={available && (current.user_enabled_in_chat ?? true)}
          disabled={pending || !available}
          onCheckedChange={(enabled) => void save(enabled)}
        />
      </div>
      {failed && (
        <div role="alert">
          <Text font="secondary-body" color="status-error-05">
            {t("saveFailed")}
          </Text>
        </div>
      )}
    </Section>
  );
}
