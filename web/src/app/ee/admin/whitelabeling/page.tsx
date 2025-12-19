import { WhitelabelingForm } from "./WhitelabelingForm";
import { AdminPageTitle } from "@/components/admin/Title";
import { PaintingIcon } from "@/components/icons/icons";

export default async function Whitelabeling() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Whitelabeling"
        icon={<PaintingIcon size={32} className="my-auto" />}
      />

      <WhitelabelingForm />
    </div>
  );
}
