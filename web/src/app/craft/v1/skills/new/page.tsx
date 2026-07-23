import SkillEditorPage from "@/views/SkillEditorPage";

interface CreateSkillPageProps {
  searchParams: Promise<{ draft?: string | string[] }>;
}

export default async function CreateSkillPage({
  searchParams,
}: CreateSkillPageProps) {
  const { draft } = await searchParams;
  return (
    <SkillEditorPage draftId={typeof draft === "string" ? draft : undefined} />
  );
}
