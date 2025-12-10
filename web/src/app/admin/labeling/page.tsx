import { AdminPageLayout } from "@/refresh-components/layouts/AdminPageLayout";
import SvgPaintBrush from "@/icons/paint-brush";
import Button from "@/refresh-components/buttons/Button";
import { AppearanceThemeSettings } from "./AppearanceThemeSettings";

export default function LabelingPage() {
  return (
    <AdminPageLayout
      title="Appearance & Theming"
      description="Customize how the application appears to users across your organization."
      icon={SvgPaintBrush}
      rightChildren={<Button>Apply Changes</Button>}
    >
      <AppearanceThemeSettings />
    </AdminPageLayout>
  );
}
