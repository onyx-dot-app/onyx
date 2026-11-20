"use client";

import { useEffect } from "react";
import { useLocale, useTranslations } from "next-intl";
import { SvgBlocks } from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import { memberPluginEntries } from "@/lib/plugins/directory";
import { customizeTabHref, skillHref } from "@/lib/customize/paths";
import { useUser } from "@/providers/UserProvider";
import CustomizeDetailLayout, {
  BackLink,
} from "@/sections/customize/CustomizeDetailLayout";

interface MemberPluginDetailPageProps {
  pluginId: string;
}

/** An old plugin link. A plugin holds one skill, so the page opens the skill
 * page, or shows that the plugin is not found. */
export default function MemberPluginDetailPage({
  pluginId,
}: MemberPluginDetailPageProps) {
  const t = useTranslations("plugins.member.detail");
  const tabCopy = useTranslations("customize.tabs");
  const locale = useLocale();
  const navigation = useNavigation();
  const { user } = useUser();
  const skills = useUserSkills();
  const entry = memberPluginEntries(
    skills.data?.customs ?? [],
    user?.email ?? null,
    locale
  ).find((candidate) => candidate.id === pluginId);
  const skillId = entry?.skills[0]?.id;
  useEffect(() => {
    if (skillId) navigation.go(skillHref(skillId), { replace: true });
  }, [navigation, skillId]);

  return (
    <CustomizeDetailLayout
      back={
        <BackLink to={customizeTabHref("plugins")} label={tabCopy("plugins")} />
      }
      icon={SvgBlocks}
      title={t("title")}
      loading={skills.isLoading || skillId !== undefined}
      error={
        skills.isLoading
          ? false
          : skills.error
            ? t("loadFailed")
            : t("notFound")
      }
      tabs={null}
      tab="overview"
      onTabChange={() => undefined}
    />
  );
}
