import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Explorer } from "./Explorer";
import { fetchValidFilterInfo } from "@/lib/search/utilsSS";
import { SvgZoomIn } from "@opal/icons";
export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const { connectors, documentSets } = await fetchValidFilterInfo();

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgZoomIn}
        title="Document Explorer"
        separator
      />

      <SettingsLayouts.Body>
        <Explorer
          initialSearchValue={searchParams.query}
          connectors={connectors}
          documentSets={documentSets}
        />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
