"use client";

import { useState } from "react";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { Content } from "@opal/layouts";
import Separator from "@/refresh-components/Separator";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import RequestConnectorModal from "@/app/craft/v1/configure/components/RequestConnectorModal";
import {
  OutlookIcon,
  OneDriveIcon,
  BoxIcon,
  TrelloIcon,
  ServiceNowIcon,
} from "@/components/icons/icons";

// Coming soon connectors - organized by ecosystem
const COMING_SOON_CONNECTORS: ValidSources[] = [
  // Microsoft
  ValidSources.Sharepoint,
  ValidSources.Teams,
  ValidSources.Imap, // Outlook via IMAP
  // Atlassian
  ValidSources.Confluence,
  ValidSources.Jira,
  ValidSources.Bitbucket,
  // Git/GitLab
  ValidSources.GitLab,
  // Cloud Storage
  ValidSources.Dropbox,
  // Salesforce
  ValidSources.Salesforce,
  ValidSources.Gong,
  // Knowledge Base/Wiki
  ValidSources.Bookstack,
  ValidSources.Discord,
  ValidSources.Zendesk,
  ValidSources.Freshdesk,
  ValidSources.Egnyte,
  // Project Management
  ValidSources.Asana,
  ValidSources.Clickup,
  ValidSources.Productboard,
  // Knowledge Base/Wiki
  ValidSources.Outline,
  ValidSources.Slab,
  ValidSources.Coda,
  ValidSources.Guru,
  ValidSources.Document360,
  ValidSources.Gitbook,
  ValidSources.Highspot,
  ValidSources.DrupalWiki,
  ValidSources.Discourse,
  ValidSources.Axero,
  // Messaging/Collaboration
  ValidSources.Zulip,
  // Other
  ValidSources.Loopio,
  ValidSources.Xenforo,
];

export default function ComingSoonConnectors() {
  const [showRequestModal, setShowRequestModal] = useState(false);

  return (
    <>
      <Separator />
      <div className="w-full flex items-center justify-between pb-2">
        <div className="flex flex-col gap-0.25">
          <Text mainContentEmphasis text04>
            Coming Soon
          </Text>
          <Text secondaryBody text03>
            Don't see what you're looking for? Submit a connector request!
          </Text>
        </div>
        <button
          type="button"
          onClick={() => setShowRequestModal(true)}
          className="px-4 py-2 rounded-12 bg-white dark:bg-black hover:opacity-90 transition-colors whitespace-nowrap"
        >
          <Text
            mainUiAction
            className="text-text-dark-05 dark:text-text-light-05"
          >
            Submit a request
          </Text>
        </button>
      </div>
      <div className="w-full grid grid-cols-1 md:grid-cols-4 gap-2">
        {COMING_SOON_CONNECTORS.flatMap((type) => {
          const sourceMetadata = getSourceMetadata(type);
          // Special case: IMAP should display as "Outlook" with custom icon
          const displayName =
            type === ValidSources.Imap ? "Outlook" : sourceMetadata.displayName;

          const card = (
            <div key={type} className="opacity-60">
              <Card variant="secondary">
                <Content
                  icon={
                    type === ValidSources.Imap
                      ? OutlookIcon
                      : sourceMetadata.icon
                  }
                  title={displayName}
                  sizePreset="main-ui"
                  variant="body"
                />
              </Card>
            </div>
          );

          // Insert OneDrive right after Outlook
          if (type === ValidSources.Imap) {
            return [
              card,
              <div key="onedrive" className="opacity-60">
                <Card variant="secondary">
                  <Content
                    icon={OneDriveIcon}
                    title="OneDrive"
                    sizePreset="main-ui"
                    variant="body"
                  />
                </Card>
              </div>,
            ];
          }

          // Insert Box right after Discord
          if (type === ValidSources.Discord) {
            return [
              card,
              <div key="box" className="opacity-60">
                <Card variant="secondary">
                  <Content
                    icon={BoxIcon}
                    title="Box"
                    sizePreset="main-ui"
                    variant="body"
                  />
                </Card>
              </div>,
            ];
          }

          return [card];
        })}
        {/* Enterprise/ERP */}
        <div className="opacity-60">
          <Card variant="secondary">
            <Content
              icon={ServiceNowIcon}
              title="ServiceNow"
              sizePreset="main-ui"
              variant="body"
            />
          </Card>
        </div>
        {/* Project Management */}
        <div className="opacity-60">
          <Card variant="secondary">
            <Content
              icon={TrelloIcon}
              title="Trello"
              sizePreset="main-ui"
              variant="body"
            />
          </Card>
        </div>
      </div>
      <RequestConnectorModal
        open={showRequestModal}
        onClose={() => setShowRequestModal(false)}
      />
    </>
  );
}
