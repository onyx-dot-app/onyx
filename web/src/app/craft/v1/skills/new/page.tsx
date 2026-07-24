import SkillEditorPage from "@/views/SkillEditorPage";

interface CreateSkillPageProps {
  searchParams: Promise<{
    draft?: string | string[];
    externalAppId?: string | string[];
    externalAppName?: string | string[];
  }>;
}

export default async function CreateSkillPage({
  searchParams,
}: CreateSkillPageProps) {
  const { draft, externalAppId, externalAppName } = await searchParams;
  const parsedExternalAppId =
    typeof externalAppId === "string" ? Number(externalAppId) : undefined;
  return (
    <SkillEditorPage
      draftId={typeof draft === "string" ? draft : undefined}
      externalAppId={
        Number.isInteger(parsedExternalAppId) &&
        parsedExternalAppId !== undefined &&
        parsedExternalAppId > 0
          ? parsedExternalAppId
          : undefined
      }
      externalAppName={
        typeof externalAppName === "string" ? externalAppName : undefined
      }
    />
  );
}
