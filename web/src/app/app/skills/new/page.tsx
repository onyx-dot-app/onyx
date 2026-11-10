import SkillEditorPage from "@/views/SkillEditorPage";

interface PageProps {
  searchParams: Promise<{ draft?: string | string[] }>;
}

export default async function Page({ searchParams }: PageProps) {
  const { draft } = await searchParams;
  return (
    <SkillEditorPage
      libraryPath="/app/skills"
      draftId={typeof draft === "string" ? draft : undefined}
    />
  );
}
