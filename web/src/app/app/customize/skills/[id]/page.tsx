import SkillEditorPage from "@/views/SkillEditorPage";

export interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function Page({ params }: PageProps) {
  const { id } = await params;
  return <SkillEditorPage skillId={id} />;
}
