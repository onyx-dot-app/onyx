import { AdminPageTitle } from "@/components/admin/Title";
import { ZoomInIcon } from "@/components/icons/icons";
import { Explorer } from "./Explorer";
import { fetchValidFilterInfo } from "@/lib/search/utilsSS";

const Page = async (props: {
  searchParams: Promise<{ [key: string]: string }>;
}) => {
  const { connectors, documentSets } = await fetchValidFilterInfo();

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<ZoomInIcon size={32} />}
        title="Document Explorer"
      />

      <Explorer connectors={connectors} documentSets={documentSets} />
    </div>
  );
};

export default Page;
