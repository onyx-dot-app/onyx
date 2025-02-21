import { AdminPageTitle } from "@/components/admin/Title";
import BillingInformationPage from "./BillingInformationPage";
import { MdOutlineCreditCard } from "react-icons/md";

export interface BillingInformation {
  stripe_subscription_id: string;
  status: string;
  current_period_start: Date;
  current_period_end: Date;
  number_of_seats: number;
  cancel_at_period_end: boolean;
  canceled_at: Date | null;
  trial_start: Date | null;
  trial_end: Date | null;
  seats: number;
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
