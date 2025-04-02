import React from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { ValidSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import { useOAuthDetails } from "@/lib/connectors/oauth";
import { Spinner } from "@/components/Spinner";
import { CreateStdOAuthCredential } from "@/components/credentials/actions/CreateStdOAuthCredential";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/oauth";
import { Button } from "@/components/ui/button";
import { getSourceDisplayName } from "@/lib/sources";

interface OutlookPageProps {
  setPopup: (popupSpec: any) => void;
  onSwitch?: (credential: Credential<any>) => void;
}

export default function OutlookPage({ setPopup, onSwitch }: OutlookPageProps) {
  const { data: oauthDetails, isLoading: oauthDetailsLoading } = useOAuthDetails(
    ValidSources.Outlook
  );

  const handleAuthorize = async () => {
    try {
      const redirectUrl = await getConnectorOauthRedirectUrl(
        ValidSources.Outlook,
        {}
      );
      if (redirectUrl) {
        window.location.href = redirectUrl;
      } else {
        setPopup({
          message: "Failed to get OAuth URL",
          type: "error",
        });
      }
    } catch (error) {
      setPopup({
        message: "Error initiating OAuth flow",
        type: "error",
      });
    }
  };

  if (oauthDetailsLoading) {
    return <Spinner />;
  }

  if (oauthDetails?.oauth_enabled) {
    if (oauthDetails.additional_kwargs.length > 0) {
      return (
        <CreateStdOAuthCredential
          sourceType={ValidSources.Outlook}
          additionalFields={oauthDetails.additional_kwargs}
        />
      );
    }
  }

  return (
    <div className="flex flex-col gap-y-4">
      <p className="text-sm">
        Connect your Outlook account to access emails and attachments.
      </p>
      <Button
        onClick={handleAuthorize}
        className="bg-blue-500 hover:bg-blue-600 text-white"
      >
        Connect Outlook Account
      </Button>
    </div>
  );
} 