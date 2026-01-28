"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgWallet } from "@opal/icons";
import { useBillingInformation } from "@/lib/hooks/useBillingInformation";
import { useLicense } from "@/lib/hooks/useLicense";
import {
  BillingInformation,
  hasActiveSubscription,
} from "@/lib/billing/interfaces";
import { fetchLicense } from "@/lib/billing/actions";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import Plans from "./components/Plans";
import BillingDetails from "./components/BillingDetails";
import "./billing.css";

export default function BillingPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [viewingPlans, setViewingPlans] = useState(false);

  const {
    data: billingData,
    isLoading: billingLoading,
    refresh: refreshBilling,
  } = useBillingInformation();

  const {
    data: licenseData,
    isLoading: licenseLoading,
    refresh: refreshLicense,
  } = useLicense();

  // Handle checkout success
  useEffect(() => {
    const sessionId = searchParams.get("session_id");
    if (sessionId) {
      // Clear the session_id from URL
      router.replace("/admin/billing", { scroll: false });

      // Refresh data after successful checkout
      const handleCheckoutSuccess = async () => {
        // For self-hosted, fetch the new license
        if (!NEXT_PUBLIC_CLOUD_ENABLED) {
          try {
            await fetchLicense();
            refreshLicense();
          } catch (error) {
            console.error("Failed to fetch license after checkout:", error);
          }
        }
        refreshBilling();
      };

      handleCheckoutSuccess();
    }
  }, [searchParams, router, refreshBilling, refreshLicense]);

  const isLoading = billingLoading || licenseLoading;

  if (isLoading) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgWallet}
          title="Plans & Billing"
          description="Loading billing information..."
        />
        <SettingsLayouts.Body>
          <div className="flex items-center justify-center h-32">
            <span className="text-text-03">Loading...</span>
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const hasSubscription = billingData && hasActiveSubscription(billingData);
  const billing = hasSubscription ? (billingData as BillingInformation) : null;

  // Determine current plan name for the Plans component
  const currentPlan = billing?.plan_type ?? licenseData?.plan_type ?? undefined;

  const handleViewPlans = () => {
    setViewingPlans(true);
  };

  const handleBackFromPlans = () => {
    setViewingPlans(false);
  };

  const handleRefresh = () => {
    refreshBilling();
    if (!NEXT_PUBLIC_CLOUD_ENABLED) {
      refreshLicense();
    }
  };

  // Show Plans page (no subscription OR viewing plans from billing details)
  if (!hasSubscription || viewingPlans) {
    const title = hasSubscription ? "View Plans" : "Upgrade Plan";
    const description = hasSubscription
      ? "Compare and manage your subscription plan"
      : "Choose a plan to unlock premium features";

    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgWallet}
          title={title}
          description={description}
          backButton={hasSubscription && viewingPlans}
        />
        <SettingsLayouts.Body>
          <Plans currentPlan={currentPlan} onLicenseActivated={handleRefresh} />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  // Show Billing Details page (has subscription)
  // At this point we know billing is not null because hasSubscription is true
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgWallet}
        title="Plans & Billing"
        description="Manage your subscription and billing settings"
      />
      <SettingsLayouts.Body>
        <BillingDetails
          billing={billing!}
          license={licenseData ?? undefined}
          onViewPlans={handleViewPlans}
          onRefresh={handleRefresh}
        />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
