"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { mutate } from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { SvgArrowUpCircle, SvgWallet } from "@opal/icons";
import type { IconProps } from "@opal/types";
import {
  useBillingInformation,
  useLicense,
  BillingInformation,
  hasActiveSubscription,
  claimLicense,
  endTrial,
  PaymentMethodRequiredError,
  createCustomerPortalSession,
  StripePortalFlowType,
} from "@/lib/billing";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useUser } from "@/providers/UserProvider";
import { LinkButton, MessageCard } from "@opal/components";

import PlansView from "./PlansView";
import CheckoutView from "./CheckoutView";
import BillingDetailsView from "./BillingDetailsView";
import LicenseActivationCard from "./LicenseActivationCard";
import "./billing.css";

// sessionStorage key: value is a unix-ms expiry timestamp
const BILLING_ACTIVATING_KEY = "billing_license_activating_until";

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
          <LinkButton onClick={onActivateLicense}>{licenseText}</LinkButton>
        </>
      )}
      <LinkButton href={billingHelpHref}>Billing Help</LinkButton>
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
  const [isActivating, setIsActivating] = useState<boolean>(false);

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

  const hasManualLicense = licenseData?.source === "manual_upload";

  // Air-gapped: billing endpoint is unreachable (manual license + connectivity error)
  const isAirGapped = !!(hasManualLicense && billingError);

  // Stripe error: auto-fetched license but billing endpoint is unreachable
  const hasStripeError = !!(
    isSelfHosted &&
    licenseData?.has_license &&
    billingError &&
    !hasManualLicense
  );

  // Manual license without active Stripe subscription
  // Stripe-dependent actions (manage plan, update seats) won't work
  const isManualLicenseOnly = !!(hasManualLicense && !hasSubscription);

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

  // Read activating state from sessionStorage after mount (avoids SSR hydration mismatch)
  useEffect(() => {
    const raw = sessionStorage.getItem(BILLING_ACTIVATING_KEY);
    if (!raw) return;
    if (Number(raw) > Date.now()) {
      setIsActivating(true);
    } else {
      sessionStorage.removeItem(BILLING_ACTIVATING_KEY);
    }
  }, []);

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
    const retryUpgrade = searchParams.get("retry_upgrade") === "1";

    if (!sessionId && !portalReturn) return;

    router.replace("/admin/billing", { scroll: false });

    let cancelled = false;

    const handleBillingReturn = async () => {
      if (!NEXT_PUBLIC_CLOUD_ENABLED) {
        // Retry up to 3 times with 2s backoff. The license may not be available
        // immediately if the Stripe webhook hasn't finished processing yet
        // (redirect and webhook fire nearly simultaneously).
        let lastError: Error | null = null;
        for (let attempt = 0; attempt < 3; attempt++) {
          if (cancelled) return;
          try {
            // After checkout, exchange session_id for license; after portal, re-sync license
            await claimLicense(sessionId ?? undefined);
            if (cancelled) return;
            refreshLicense();
            // Refresh settings so EE-gated UI (e.g. sidebar) updates immediately.
            router.refresh();
            mutate(SWR_KEYS.settings);
            mutate(SWR_KEYS.enterpriseSettings);
            // Navigate to billing details now that the license is active
            changeView("details");
            lastError = null;
            break;
          } catch (err) {
            lastError = err instanceof Error ? err : new Error("Unknown error");
            if (attempt < 2) {
              await new Promise((resolve) => setTimeout(resolve, 2000));
            }
          }
        }
        if (cancelled) return;
        if (lastError) {
          console.error(
            "Failed to sync license after billing return:",
            lastError
          );
          // Show an activating banner on the plans view and keep retrying in the background.
          sessionStorage.setItem(
            BILLING_ACTIVATING_KEY,
            String(Date.now() + 120_000)
          );
          setIsActivating(true);
          changeView("plans");
        }
      }
      if (!cancelled) refreshBilling();

      // Auto-retry the trial upgrade if the user just came back from the
      // add-payment-method portal flow. This avoids making them click
      // "Upgrade now" a second time once their card is on file.
      if (!cancelled && retryUpgrade && NEXT_PUBLIC_CLOUD_ENABLED) {
        try {
          await endTrial();
          if (!cancelled) {
            refreshBilling();
            router.refresh();
            mutate(SWR_KEYS.settings);
            mutate(SWR_KEYS.enterpriseSettings);
          }
        } catch (err) {
          if (err instanceof PaymentMethodRequiredError) {
            // Card add was abandoned or failed verification — bounce them
            // back to the same flow so they can complete it.
            try {
              const response = await createCustomerPortalSession({
                return_url: `${window.location.origin}/admin/billing?portal_return=true&retry_upgrade=1`,
                flow_type: StripePortalFlowType.PAYMENT_METHOD_UPDATE,
              });
              if (response.stripe_customer_portal_url) {
                window.location.href = response.stripe_customer_portal_url;
              }
            } catch (portalErr) {
              console.error("Failed to reopen portal after retry:", portalErr);
            }
          } else {
            console.error("Auto-retry of trial upgrade failed:", err);
          }
        }
      }
    };
    handleBillingReturn();

    return () => {
      cancelled = true;
    };
    // changeView intentionally omitted: it only calls stable state setters and the
    // effect runs at most once (when session_id/portal_return params are present).
  }, [searchParams, router, refreshBilling, refreshLicense]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll every 15s while activating, up to 2 minutes, to detect when the license arrives.
  useEffect(() => {
    if (!isActivating) return;

    let requestInFlight = false;

    const intervalId = setInterval(async () => {
      if (requestInFlight) return;
      const raw = sessionStorage.getItem(BILLING_ACTIVATING_KEY);
      if (!raw || Number(raw) <= Date.now()) {
        // Expired — stop immediately without waiting for React cleanup
        clearInterval(intervalId);
        sessionStorage.removeItem(BILLING_ACTIVATING_KEY);
        setIsActivating(false);
        return;
      }
      requestInFlight = true;
      try {
        await claimLicense(undefined);
        sessionStorage.removeItem(BILLING_ACTIVATING_KEY);
        setIsActivating(false);
        refreshLicense();
        refreshBilling();
        // Refresh settings so EE-gated UI (e.g. sidebar) updates immediately.
        router.refresh();
        mutate(SWR_KEYS.settings);
        mutate(SWR_KEYS.enterpriseSettings);
        changeView("details");
      } catch (err) {
        // License not ready yet — keep polling. Log so unexpected failures
        // (network errors, 500s) are distinguishable from expected 404s.
        console.debug("License activation poll: will retry", err);
      } finally {
        requestInFlight = false;
      }
    }, 15_000);

    return () => clearInterval(intervalId);
  }, [isActivating]); // eslint-disable-line react-hooks/exhaustive-deps

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
    // Refresh settings so EE-gated UI (e.g. sidebar) updates immediately.
    router.refresh();
    mutate(SWR_KEYS.settings);
    mutate(SWR_KEYS.enterpriseSettings);
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
          showBackButton: !!(
            hasSubscription ||
            (isSelfHosted && licenseData?.has_license)
          ),
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
    const hasEntitlement =
      hasSubscription || (isSelfHosted && licenseData?.has_license);
    if (view === "checkout") {
      changeView(hasEntitlement ? "details" : "plans");
    } else if (view === "plans" && hasEntitlement) {
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
          isManualLicenseOnly={isManualLicenseOnly}
          hasStripeError={hasStripeError}
          licenseCard={
            isManualLicenseOnly ? (
              <LicenseActivationCard
                isOpen
                onSuccess={handleLicenseActivated}
                license={licenseData ?? undefined}
                onClose={() => {}}
                hideClose
              />
            ) : undefined
          }
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
        {showLicenseActivationInput && !isManualLicenseOnly && (
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
            isManualLicenseOnly ||
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
        divider
      />
      <SettingsLayouts.Body>
        <div className="flex flex-col items-center gap-6">
          {isActivating && (
            <MessageCard
              variant="warning"
              title="Your license is still activating"
              description="Your license is being processed. You'll be taken to billing details automatically once confirmed."
              onClose={() => {
                sessionStorage.removeItem(BILLING_ACTIVATING_KEY);
                setIsActivating(false);
              }}
            />
          )}
          {renderContent()}
          {renderFooter()}
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
