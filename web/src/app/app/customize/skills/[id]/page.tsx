import CustomizeSkillPage from "@/sections/customize/CustomizeSkillPage";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function Page({ params }: PageProps) {
  const { id } = await params;
  return <CustomizeSkillPage key={id} skillId={id} />;
}
