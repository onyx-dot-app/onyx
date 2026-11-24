import { notFound } from "@opal/navigation";
import { parseArtifactLink } from "@/lib/chat/publishedFiles";
import ArtifactLinkPage from "@/sections/chat/ArtifactLinkPage";

interface PageProps {
  params: Promise<{ link: string[] }>;
}

/** An artifact link: `/app/artifacts/<artifact_id>[/v<N>]`. */
export default async function Page({ params }: PageProps) {
  const { link } = await params;
  const artifact = parseArtifactLink(`/app/artifacts/${link.join("/")}`);
  if (!artifact) notFound();
  return (
    <ArtifactLinkPage
      key={link.join("/")}
      artifactId={artifact.artifactId}
      version={artifact.version}
    />
  );
}
