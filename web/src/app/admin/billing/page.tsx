"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgArrowUpCircle, SvgWallet } from "@opal/icons";
import type { IconProps } from "@opal/types";
import {
  useBillingInformation,
  useLicense,
  BillingInformation,
  hasActiveSubscription,
  claimLicense,
} from "@/lib/billing";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useUser } from "@/providers/UserProvider";

import PlansView from "./PlansView";
import CheckoutView from "./CheckoutView";
import BillingDetailsView from "./BillingDetailsView";
import LicenseActivationCard from "./LicenseActivationCard";
import "./billing.css";

// ----------------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------------

type BillingView = "plans" | "details" | "checkout" | null;

interface ViewConfig {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  showBackButton: boolean;
}

// ----------------------------------------------------------------------------
// FooterLinks (inlined)
// ----------------------------------------------------------------------------

const SUPPORT_EMAIL = "support@onyx.app";

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
            <Text secondaryBody text05 className="underline">
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
// BillingPage
// ----------------------------------------------------------------------------

export default function BillingPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Start with null view to prevent flash - will be set once data loads
  const [view, setView] = useState<BillingView | null>(null);
  const [showLicenseActivationInput, setShowLicenseActivationInput] =
    useState(false);
  const [licenseCardAutoOpened, setLicenseCardAutoOpened] = useState(false);
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
  const isSelfHosted = !NEXT_PUBLIC_CLOUD_ENABLED;

  // User is only air-gapped if they have a manual license AND Stripe is not connected
  // Once Stripe connects successfully, they're no longer air-gapped
  const hasManualLicense = licenseData?.source === "manual_upload";
  const stripeConnected = billingData && !billingError;
  const isAirGapped = hasManualLicense && !stripeConnected;
  const hasStripeError = !!(
    isSelfHosted &&
    licenseData?.has_license &&
    billingError &&
    !hasManualLicense
  );

  // Set initial view based on subscription status (only once when data first loads)
  useEffect(() => {
    if (!isLoading && view === null) {
      const shouldShowDetails =
        hasSubscription || (isSelfHosted && licenseData?.has_license);
      setView(shouldShowDetails ? "details" : "plans");
    }
  }, [
    isLoading,
    hasSubscription,
    isSelfHosted,
    licenseData?.has_license,
    view,
  ]);

  // Show license activation card when there's a Stripe error
  useEffect(() => {
    if (hasStripeError && !showLicenseActivationInput) {
      setLicenseCardAutoOpened(true);
      setShowLicenseActivationInput(true);
    }
  }, [hasStripeError, showLicenseActivationInput]);

  // Handle return from checkout or customer portal
  useEffect(() => {
    const sessionId = searchParams.get("session_id");
    const portalReturn = searchParams.get("portal_return");

    if (!sessionId && !portalReturn) return;

    router.replace("/admin/billing", { scroll: false });

    const handleBillingReturn = async () => {
      if (!NEXT_PUBLIC_CLOUD_ENABLED) {
        try {
          // After checkout, exchange session_id for license; after portal, re-sync license
          await claimLicense(sessionId ?? undefined);
          refreshLicense();
          // Refresh the page to update settings (including ee_features_enabled)
          router.refresh();
          // Navigate to billing details now that the license is active
          changeView("details");
        } catch (error) {
          console.error("Failed to sync license after billing return:", error);
        }
      }
      refreshBilling();
    };
    handleBillingReturn();
  }, [searchParams, router, refreshBilling, refreshLicense]);

  const handleRefresh = async () => {
    await Promise.all([
      refreshBilling(),
      isSelfHosted ? refreshLicense() : Promise.resolve(),
    ]);
  };

  // Hide license activation card when Stripe connection is restored (only if auto-opened)
  useEffect(() => {
    if (
      !hasStripeError &&
      !isAirGapped &&
      showLicenseActivationInput &&
      licenseCardAutoOpened &&
      !isLoading
    ) {
      if (billingData && hasActiveSubscription(billingData)) {
        setLicenseCardAutoOpened(false);
        setShowLicenseActivationInput(false);
      }
    }
  }, [
    hasStripeError,
    isAirGapped,
    showLicenseActivationInput,
    licenseCardAutoOpened,
    isLoading,
    billingData,
  ]);

  const handleLicenseActivated = () => {
    refreshLicense();
    refreshBilling();
    // Refresh the page to update settings (including ee_features_enabled)
    router.refresh();
    // Navigate to billing details now that the license is active
    changeView("details");
  };

  // View configuration
  const getViewConfig = (): ViewConfig => {
    if (isLoading || view === null) {
      return {
        icon: SvgWallet,
        title: "Plans & Billing",
        showBackButton: false,
      };
    }
    switch (view) {
      case "checkout":
        return {
          icon: SvgArrowUpCircle,
          title: "Upgrade Plan",
          showBackButton: false,
        };
      case "plans":
        return {
          icon: hasSubscription ? SvgWallet : SvgArrowUpCircle,
          title: hasSubscription ? "View Plans" : "Upgrade Plan",
          showBackButton: !!hasSubscription,
        };
      case "details":
        return {
          icon: SvgWallet,
          title: "Plans & Billing",
          showBackButton: false,
        };
    }
  };

  const viewConfig = getViewConfig();

  // Handle view changes with transition
  const changeView = (newView: "plans" | "details" | "checkout") => {
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

  const renderContent = () => {
    if (isLoading || view === null) return null;

    const animationClass =
      transitionType === "expand"
        ? "billing-view-expand"
        : transitionType === "collapse"
          ? "billing-view-collapse"
          : "billing-view-enter";

    const views: Record<typeof view, React.ReactNode> = {
      checkout: <CheckoutView onAdjustPlan={() => changeView("plans")} />,
      plans: (
        <PlansView
          hasSubscription={!!hasSubscription}
          hasLicense={!!licenseData?.has_license}
          onCheckout={() => changeView("checkout")}
          hideFeatures={showLicenseActivationInput}
        />
      ),
      details: (
        <BillingDetailsView
          billing={billing ?? undefined}
          license={licenseData ?? undefined}
          onViewPlans={() => changeView("plans")}
          onRefresh={handleRefresh}
          isAirGapped={isAirGapped}
          hasStripeError={hasStripeError}
        />
      ),
    };

    return (
      <div key={viewChangeId} className={`w-full ${animationClass}`}>
        {views[view]}
      </div>
    );
  };

  // Render footer
  const renderFooter = () => {
    if (isLoading || view === null) return null;
    return (
      <>
        {showLicenseActivationInput && (
          <div className="w-full billing-card-enter">
            <LicenseActivationCard
              isOpen={showLicenseActivationInput}
              onSuccess={handleLicenseActivated}
              license={licenseData ?? undefined}
              onClose={() => {
                setLicenseCardAutoOpened(false);
                setShowLicenseActivationInput(false);
              }}
            />
          </div>
        )}
        <FooterLinks
          hasSubscription={!!hasSubscription || !!licenseData?.has_license}
          onActivateLicense={
            isSelfHosted ? () => setShowLicenseActivationInput(true) : undefined
          }
          hideLicenseLink={
            showLicenseActivationInput ||
            (view === "plans" &&
              (!!hasSubscription || !!licenseData?.has_license))
          }
        />
      </>
    );
  };

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={viewConfig.icon}
        title={viewConfig.title}
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
