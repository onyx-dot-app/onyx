import { AdminPageTitle } from "@/components/admin/Title";
import { Explorer } from "./Explorer";
import { fetchValidFilterInfo } from "@/lib/search/utilsSS";
import SvgZoomIn from "@/icons/zoom-in";

const Page = async (props: {
  searchParams: Promise<{ [key: string]: string }>;
}) => {
  const searchParams = await props.searchParams;
  const { connectors, documentSets } = await fetchValidFilterInfo();

  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={SvgZoomIn} title="Document Explorer" />

      <Explorer
        initialSearchValue={searchParams.query}
        connectors={connectors}
        documentSets={documentSets}
      />
    </div>
  );
};

export default Page;
