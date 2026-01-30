/**
 * Billing Page - Main orchestrator for the /admin/billing route.
 *
 * Manages three views: Plans (selection), Checkout (purchase), and Details (management).
 * Handles Stripe redirects, license claiming, and air-gapped deployment modes.
 * Works for both cloud (Stripe-managed) and self-hosted (license-based) deployments.
 */
"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgWallet } from "@opal/icons";
import {
  useBillingInformation,
  useLicense,
  BillingInformation,
  hasActiveSubscription,
  claimLicense,
} from "@/lib/billing";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useUser } from "@/components/user/UserProvider";

import PlansView from "./PlansView";
import CheckoutView from "./CheckoutView";
import BillingDetailsView from "./BillingDetailsView";
import LicenseActivationCard from "./LicenseActivationCard";
import "./billing.css";

// ----------------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------------

type BillingView = "plans" | "details" | "checkout";

interface ViewConfig {
  title: string;
  description: string;
  showBackButton: boolean;
}

import { SUPPORT_EMAIL } from "./constants";

// ----------------------------------------------------------------------------
// FooterLinks - Help links and license activation trigger
// ----------------------------------------------------------------------------

/** Footer with billing help email and license key activation link (self-hosted only). */
function FooterLinks({
  hasSubscription,
  onActivateLicense,
  hideLicenseLink,
}: {
  hasSubscription?: boolean;
  onActivateLicense?: () => void;
  hideLicenseLink?: boolean;
}) {
  const { user } = useUser();
  const licenseText = hasSubscription
    ? "Update License Key"
    : "Activate License Key";
  const billingHelpHref = `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(
    `[Billing] support for ${user?.email ?? "unknown"}`
  )}`;

  return (
    <Section flexDirection="row" justifyContent="center" gap={1} height="auto">
      {onActivateLicense && !hideLicenseLink && (
        <>
          <Text secondaryBody text03>
            Have a license key?
          </Text>
          <Button action tertiary onClick={onActivateLicense}>
            <Text secondaryBody text03 className="underline">
              {licenseText}
            </Text>
          </Button>
        </>
      )}
      <Button
        action
        tertiary
        href={billingHelpHref}
        className="billing-text-link"
      >
        <Text secondaryBody text03 className="underline">
          Billing Help
        </Text>
      </Button>
    </Section>
  );
}

// ----------------------------------------------------------------------------
// BillingPage - View controller and data orchestration
// ----------------------------------------------------------------------------

/**
 * Main billing page component. Fetches billing/license data and routes between views.
 * Handles post-checkout and post-portal redirects to sync license state.
 */
export default function BillingPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [view, setView] = useState<BillingView>("plans");
  const [showLicenseActivationInput, setShowLicenseActivationInput] =
    useState(false);
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

  const isAirGapped = licenseData?.source === "manual_upload";
  const hasStripeError = !!(
    isSelfHosted &&
    licenseData?.has_license &&
    billingError &&
    !isAirGapped
  );

  // Set initial view based on subscription status
  useEffect(() => {
    if (!isLoading) {
      const shouldShowDetails =
        hasSubscription || (isSelfHosted && licenseData?.has_license);
      setView(shouldShowDetails ? "details" : "plans");
    }
  }, [isLoading, hasSubscription, isSelfHosted, licenseData?.has_license]);

  // Show license activation card when there's a Stripe error
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

  // Handle return from customer portal
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
  };

  // Hide license activation card when Stripe connection is restored
  useEffect(() => {
    if (
      !hasStripeError &&
      !isAirGapped &&
      showLicenseActivationInput &&
      !isLoading
    ) {
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

  // Handle view changes with transition
  const changeView = (newView: BillingView) => {
    if (newView === view) return;
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

  const handleBack = () => {
    if (view === "checkout") {
      changeView(hasSubscription ? "details" : "plans");
    } else if (view === "plans" && hasSubscription) {
      changeView("details");
    }
  };

  // Render content
  const renderContent = () => {
    if (isLoading) return null;

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
            <PlansView
              currentPlan={currentPlan}
              hasSubscription={!!hasSubscription}
              onCheckout={() => changeView("checkout")}
              hideFeatures={showLicenseActivationInput}
            />
          );
        case "details":
          return (
            <BillingDetailsView
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

  // Render footer
  const renderFooter = () => {
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
          {renderFooter()}
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
