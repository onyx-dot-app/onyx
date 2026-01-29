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
import { claimLicense } from "@/lib/billing/actions";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import Plans from "./components/Plans";
import BillingDetails from "./components/BillingDetails";
import CheckoutView from "./components/CheckoutView";
import FooterLinks from "./components/FooterLinks";
import LicenseActivationCard from "./components/LicenseActivationCard";
import "./billing.css";

type BillingView = "plans" | "details" | "checkout";

interface ViewConfig {
  title: string;
  description: string;
  showBackButton: boolean;
}

export default function BillingPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [view, setView] = useState<BillingView>("plans");
  const [showLicenseActivationInput, setShowLicenseActivationInput] =
    useState<boolean>(false);
  const [viewChangeId, setViewChangeId] = useState(0);
  const [transitionType, setTransitionType] = useState<
    "expand" | "collapse" | "fade"
  >("fade");

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

  const isLoading = billingLoading || licenseLoading;
  const hasSubscription = billingData && hasActiveSubscription(billingData);
  const billing = hasSubscription ? (billingData as BillingInformation) : null;
  const currentPlan = billing?.plan_type ?? licenseData?.plan_type ?? undefined;
  const isSelfHosted = !NEXT_PUBLIC_CLOUD_ENABLED;

  // Set initial view based on subscription status
  useEffect(() => {
    if (!isLoading) {
      setView(hasSubscription ? "details" : "plans");
    }
  }, [isLoading, hasSubscription]);

  // Handle checkout success
  useEffect(() => {
    const sessionId = searchParams.get("session_id");
    if (sessionId) {
      router.replace("/admin/billing", { scroll: false });

      const handleCheckoutSuccess = async () => {
        if (!NEXT_PUBLIC_CLOUD_ENABLED) {
          try {
            await claimLicense(sessionId);
            refreshLicense();
          } catch (error) {
            console.error("Failed to claim license after checkout:", error);
          }
        }
        refreshBilling();
      };

      handleCheckoutSuccess();
    }
  }, [searchParams, router, refreshBilling, refreshLicense]);

  const handleRefresh = () => {
    refreshBilling();
    if (isSelfHosted) {
      refreshLicense();
    }
  };

  const handleLicenseActivated = () => {
    refreshLicense();
    refreshBilling();
  };

  // View configuration
  const getViewConfig = (): ViewConfig => {
    if (isLoading) {
      return {
        title: "Plans & Billing",
        description: "Loading billing information...",
        showBackButton: false,
      };
    }

    switch (view) {
      case "checkout":
        return {
          title: "Upgrade Plan",
          description: "Configure your Business Plan subscription",
          showBackButton: false,
        };
      case "plans":
        return {
          title: hasSubscription ? "View Plans" : "Upgrade Plan",
          description: hasSubscription
            ? "Compare and manage your subscription plan"
            : "Choose a plan to unlock premium features",
          showBackButton: !!hasSubscription,
        };
      case "details":
      default:
        return {
          title: "Plans & Billing",
          description: "Manage your subscription and billing settings",
          showBackButton: false,
        };
    }
  };

  const viewConfig = getViewConfig();

  // Footer links - shown on plans and checkout views
  const renderFooterLinks = () => {
    if (isLoading || view === "details") return null;

    return (
      <>
        <FooterLinks
          hasSubscription={!!hasSubscription}
          onActivateLicense={
            isSelfHosted ? () => setShowLicenseActivationInput(true) : undefined
          }
        />
        {showLicenseActivationInput && (
          <div className="w-full billing-card-enter">
            <LicenseActivationCard
              isOpen={showLicenseActivationInput}
              onSuccess={handleLicenseActivated}
              isUpdate={!!hasSubscription}
              onClose={() => setShowLicenseActivationInput(false)}
            />
          </div>
        )}
      </>
    );
  };

  // Handle view changes with transition tracking
  const changeView = (newView: BillingView, from?: BillingView) => {
    if (newView === view) return;

    // Determine transition type
    if (newView === "checkout" && view === "plans") {
      setTransitionType("expand");
    } else if (newView === "plans" && view === "checkout") {
      setTransitionType("collapse");
    } else {
      setTransitionType("fade");
    }

    setViewChangeId((id) => id + 1);
    setView(newView);
  };

  // Render content based on view
  const renderContent = () => {
    if (isLoading) {
      return null;
    }
    const animationClass =
      transitionType === "expand"
        ? "billing-view-expand"
        : transitionType === "collapse"
          ? "billing-view-collapse"
          : "billing-view-enter";

    const content = (() => {
      switch (view) {
        case "checkout":
          return <CheckoutView onAdjustPlan={() => changeView("plans")} />;
        case "plans":
          return (
            <Plans
              currentPlan={currentPlan}
              onCheckout={() => changeView("checkout")}
              hideFeatures={showLicenseActivationInput}
            />
          );
        case "details":
          return (
            <BillingDetails
              billing={billing!}
              license={licenseData ?? undefined}
              onViewPlans={() => changeView("plans")}
              onRefresh={handleRefresh}
            />
          );
      }
    })();

    return (
      <div key={viewChangeId} className={`w-full ${animationClass}`}>
        {content}
      </div>
    );
  };

  const handleBack = () => {
    if (view === "checkout") {
      changeView(hasSubscription ? "details" : "plans");
    } else if (view === "plans" && hasSubscription) {
      changeView("details");
    }
  };

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgWallet}
        title={viewConfig.title}
        description={viewConfig.description}
        backButton={viewConfig.showBackButton}
        onBack={handleBack}
        separator
      />
      <SettingsLayouts.Body>
        <div className="flex flex-col items-center gap-6">
          {renderContent()}
          {renderFooterLinks()}
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
