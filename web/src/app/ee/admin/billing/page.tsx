import { AdminPageTitle } from "@/components/admin/Title";
import BillingInformationPage from "./BillingInformationPage";
import { MdOutlineCreditCard } from "react-icons/md";

export interface BillingInformation {
  seats: number;
  subscription_status: string;
  billing_start: Date;
  billing_end: Date;
  payment_method_enabled: boolean;
}

export default function page() {
  return (
    <div className="container max-w-4xl">
      <AdminPageTitle
        title="Billing Information"
        icon={<MdOutlineCreditCard size={32} className="my-auto" />}
      />
      <BillingInformationPage />
    </div>
  );
}
