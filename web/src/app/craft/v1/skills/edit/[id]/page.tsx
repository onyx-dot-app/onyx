import SkillEditorPage from "@/views/SkillEditorPage";

export interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    externalAppId?: string | string[];
    externalAppName?: string | string[];
  }>;
}

export default async function Page({ params, searchParams }: PageProps) {
  const { id } = await params;
  const { externalAppId, externalAppName } = await searchParams;
  const parsedExternalAppId =
    typeof externalAppId === "string" ? Number(externalAppId) : undefined;
  return (
    <SkillEditorPage
      skillId={id}
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
