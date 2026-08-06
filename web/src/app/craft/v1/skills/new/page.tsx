import SkillEditorPage from "@/views/SkillEditorPage";
import { externalAppContextFromSearchParams } from "@/app/craft/v1/apps/admin/skillAssociationNavigation";

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
  const params = await searchParams;
  return (
    <SkillEditorPage
      draftId={typeof params.draft === "string" ? params.draft : undefined}
      {...externalAppContextFromSearchParams(params)}
    />
  );
}
