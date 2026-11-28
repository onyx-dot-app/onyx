import SkillEditorPage from "@/views/SkillEditorPage";

interface CreateSkillPageProps {
  searchParams: Promise<{ draft?: string | string[] }>;
}

export default async function CreateSkillPage({
  searchParams,
}: CreateSkillPageProps) {
  const params = await searchParams;
  return (
    <SkillEditorPage
      draftId={typeof params.draft === "string" ? params.draft : undefined}
    />
  );
}
