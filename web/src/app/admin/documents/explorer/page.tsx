import { AdminPageTitle } from "@/components/admin/Title";
import { Explorer } from "./Explorer";
import { fetchValidFilterInfo } from "@/lib/search/utilsSS";
import { SvgZoomIn } from "@opal/icons";
export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const { connectors, documentSets } = await fetchValidFilterInfo();

  return (
    <>
      <AdminPageTitle
        icon={<SvgZoomIn className="stroke-text-04 h-8 w-8" />}
        title="Document Explorer"
      />

      <Explorer
        initialSearchValue={searchParams.query}
        connectors={connectors}
        documentSets={documentSets}
      />
    </>
  );
}
