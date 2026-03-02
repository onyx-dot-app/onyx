import { fetchValidFilterInfo } from "@/lib/search/utilsSS";
import DocumentExplorerPage from "./DocumentExplorerPage";

export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const { connectors, documentSets } = await fetchValidFilterInfo();

  return (
    <DocumentExplorerPage
      initialSearchValue={searchParams.query}
      connectors={connectors}
      documentSets={documentSets}
    />
  );
}
