import { useFormatter, useTranslations } from "next-intl";
import { Text } from "@opal/components";

export default function SkillVersionLabel({
  version,
}: {
  version: number | null;
}) {
  const t = useTranslations("skills.versions");
  const format = useFormatter();
  if (version === null) return null;
  return (
    <Text font="secondary-body" color="text-03">
      {t("number", { version: format.number(version) })}
    </Text>
  );
}
