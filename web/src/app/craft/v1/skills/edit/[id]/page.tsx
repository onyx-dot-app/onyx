import SkillEditorPage from "@/views/SkillEditorPage";
import { externalAppContextFromSearchParams } from "@/app/craft/v1/apps/admin/skillAssociationNavigation";

export interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    externalAppId?: string | string[];
    externalAppName?: string | string[];
  }>;
}

export default async function Page({ params, searchParams }: PageProps) {
  const { id } = await params;
  const appContext = externalAppContextFromSearchParams(await searchParams);
  return <SkillEditorPage skillId={id} {...appContext} />;
}
