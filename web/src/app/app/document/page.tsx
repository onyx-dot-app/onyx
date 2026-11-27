import DocumentView from "@/sections/documentView/DocumentView";

export interface DocumentPageProps {
  searchParams: Promise<{ id?: string | string[] }>;
}

export default async function Page({ searchParams }: DocumentPageProps) {
  const { id } = await searchParams;
  return <DocumentView documentId={typeof id === "string" && id ? id : null} />;
}
