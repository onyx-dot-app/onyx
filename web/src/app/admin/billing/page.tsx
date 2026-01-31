"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgWallet } from "@opal/icons";
import {
  useBillingInformation,
  useLicense,
  BillingInformation,
  hasActiveSubscription,
  claimLicense,
} from "@/lib/billing";
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
    error: billingError,
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

  // Detect air-gapped mode (license was manually uploaded)
  const isAirGapped = licenseData?.source === "manual_upload";

  // Detect Stripe connection error (has license but can't reach Stripe)
  const hasStripeError = !!(
    isSelfHosted &&
    licenseData?.has_license &&
    billingError &&
    !isAirGapped
  );

  // Set initial view based on subscription status
  // For air-gapped or users with license but no billing, show details view
  useEffect(() => {
    if (!isLoading) {
      const shouldShowDetails =
        hasSubscription || (isSelfHosted && licenseData?.has_license);
      setView(shouldShowDetails ? "details" : "plans");
    }
  }, [isLoading, hasSubscription, isSelfHosted, licenseData?.has_license]);

  // Show license activation card when there's a Stripe error (like air-gapped mode)
  useEffect(() => {
    if (hasStripeError && !showLicenseActivationInput) {
      setShowLicenseActivationInput(true);
    }
  }, [hasStripeError, showLicenseActivationInput]);

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

  // Handle return from customer portal (may have updated subscription/seats)
  useEffect(() => {
    const portalReturn = searchParams.get("portal_return");
    if (portalReturn) {
      router.replace("/admin/billing", { scroll: false });

      const handlePortalReturn = async () => {
        if (!NEXT_PUBLIC_CLOUD_ENABLED) {
          try {
            await claimLicense();
            refreshLicense();
          } catch (error) {
            console.error(
              "Failed to claim license after portal return:",
              error
            );
          }
        }
        refreshBilling();
      };

      handlePortalReturn();
    }
  }, [searchParams, router, refreshBilling, refreshLicense]);

  const handleRefresh = async () => {
    await Promise.all([
      refreshBilling(),
      isSelfHosted ? refreshLicense() : Promise.resolve(),
    ]);
    // After successful refresh, hide license card if Stripe is now connected
    // (billingError will be cleared by the refresh if successful)
  };

  // Hide license activation card when Stripe connection is restored
  useEffect(() => {
    if (
      !hasStripeError &&
      !isAirGapped &&
      showLicenseActivationInput &&
      !isLoading
    ) {
      // Only auto-hide if we had a Stripe error before and it's now resolved
      // Keep it open if user manually opened it or if air-gapped
      if (billingData && hasActiveSubscription(billingData)) {
        setShowLicenseActivationInput(false);
      }
    }
  }, [
    hasStripeError,
    isAirGapped,
    showLicenseActivationInput,
    isLoading,
    billingData,
  ]);

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

  // Footer links - shown on all views (plans, checkout, details)
  const renderFooterLinks = () => {
    if (isLoading) return null;

    return (
      <>
        {showLicenseActivationInput && (
          <div className="w-full billing-card-enter">
            <LicenseActivationCard
              isOpen={showLicenseActivationInput}
              onSuccess={handleLicenseActivated}
              license={licenseData ?? undefined}
              onClose={() => setShowLicenseActivationInput(false)}
            />
          </div>
        )}
        <FooterLinks
          hasSubscription={!!hasSubscription || !!licenseData?.has_license}
          onActivateLicense={
            isSelfHosted ? () => setShowLicenseActivationInput(true) : undefined
          }
          hideLicenseLink={showLicenseActivationInput}
        />
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
              hasSubscription={!!hasSubscription}
              onCheckout={() => changeView("checkout")}
              hideFeatures={showLicenseActivationInput}
            />
          );
        case "details":
          return (
            <BillingDetails
              billing={billing ?? undefined}
              license={licenseData ?? undefined}
              onViewPlans={() => changeView("plans")}
              onRefresh={handleRefresh}
              isAirGapped={isAirGapped}
              hasStripeError={hasStripeError}
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
