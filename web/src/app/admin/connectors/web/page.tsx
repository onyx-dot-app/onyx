"use client";

import useSWR, { useSWRConfig } from "swr";
import * as Yup from "yup";

import { LoadingAnimation } from "@/components/Loading";
import {
  GlobeIcon,
  GearIcon,
  ArrowSquareOutIcon,
} from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import {
  SelectorFormField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { ConnectorIndexingStatus, WebConfig } from "@/lib/types";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { AdminPageTitle } from "@/components/admin/Title";
import { Card, Title } from "@tremor/react";

const SCRAPE_TYPE_TO_PRETTY_NAME = {
  recursive: "Recursive",
  single: "Single Page",
  sitemap: "Sitemap",
};

export default function Web() {
  const { mutate } = useSWRConfig();

  const {
    data: connectorIndexingStatuses,
    isLoading: isConnectorIndexingStatusesLoading,
    error: connectorIndexingStatusesError,
  } = useSWR<ConnectorIndexingStatus<any, any>[]>(
    "/api/manage/admin/connector/indexing-status",
    errorHandlingFetcher
  );

  const webIndexingStatuses: ConnectorIndexingStatus<WebConfig, {}>[] =
    connectorIndexingStatuses?.filter(
      (connectorIndexingStatus) =>
        connectorIndexingStatus.connector.source === "web"
    ) ?? [];

  return (
    <div className="mx-auto container">
      <div className="mb-4">
        <HealthCheckBanner />
      </div>

      <AdminPageTitle icon={<GlobeIcon size={32} />} title="Web" />

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Specify which websites to index
      </Title>
      <p className="text-sm mb-2">
        We re-fetch the latest state of the website once a day.
      </p>
      <Card>
        <ConnectorForm<WebConfig>
          nameBuilder={(values) => `WebConnector-${values.base_url}`}
          ccPairNameBuilder={(values) => values.base_url}
          // Since there is no "real" credential associated with a web connector
          // we create a dummy one here so that we can associate the CC Pair with a
          // user. This is needed since the user for a CC Pair is found via the credential
          // associated with it.
          shouldCreateEmptyCredentialForConnector={true}
          source="web"
          inputType="load_state"
          formBody={
            <>
              <TextFormField
                name="base_url"
                label="URL to Index:"
                autoCompleteDisabled={false}
              />
              <div className="w-full">
                <SelectorFormField
                  name="web_connector_type"
                  label="Scrape Method:"
                  options={[
                    {
                      name: "Recursive",
                      value: "recursive",
                      description:
                        "Recursively index all pages that share the same base URL.",
                    },
                    {
                      name: "Single Page",
                      value: "single",
                      description: "Index only the specified page.",
                    },
                    {
                      name: "Sitemap",
                      value: "sitemap",
                      description:
                        "Enter the sitemap url or the root of the site which we can scan for a sitemap",
                    },
                  ]}
                />
              </div>
            </>
          }
          validationSchema={Yup.object().shape({
            base_url: Yup.string().required(
              "Please enter the website URL to scrape e.g. https://docs.danswer.dev/"
            ),
            web_connector_type: Yup.string()
              .oneOf(["recursive", "single", "sitemap"])
              .optional(),
          })}
          initialValues={{
            base_url: "",
            web_connector_type: undefined,
          }}
          refreshFreq={60 * 60 * 24} // 1 day
          pruneFreq={0} // Don't prune
        />
      </Card>

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Already Indexed Websites
      </Title>
      {isConnectorIndexingStatusesLoading ? (
        <LoadingAnimation text="Loading" />
      ) : connectorIndexingStatusesError || !connectorIndexingStatuses ? (
        <div>Error loading indexing history</div>
      ) : webIndexingStatuses.length > 0 ? (
        <ConnectorsTable<WebConfig, {}>
          connectorIndexingStatuses={webIndexingStatuses}
          specialColumns={[
            {
              header: "Base URL",
              key: "base_url",
              getValue: (
                ccPairStatus: ConnectorIndexingStatus<WebConfig, any>
              ) => {
                const connectorConfig =
                  ccPairStatus.connector.connector_specific_config;
                return (
                  <div className="flex w-fit">
                    <a
                      className="text-blue-500 ml-1 my-auto flex"
                      href={connectorConfig.base_url}
                    >
                      {connectorConfig.base_url}
                      <ArrowSquareOutIcon className="my-auto flex flex-shrink-0 text-blue-500" />
                    </a>
                    <a
                      className="my-auto"
                      href={`/admin/connector/${ccPairStatus.cc_pair_id}`}
                    >
                      <GearIcon className="ml-2 my-auto flex flex-shrink-0 text-gray-400" />
                    </a>
                  </div>
                );
              },
            },
            {
              header: "Scrape Method",
              key: "web_connector_type",
              getValue: (ccPairStatus) => {
                const connectorConfig =
                  ccPairStatus.connector.connector_specific_config;
                return connectorConfig.web_connector_type
                  ? SCRAPE_TYPE_TO_PRETTY_NAME[
                      connectorConfig.web_connector_type
                    ]
                  : "Recursive";
              },
            },
          ]}
          onUpdate={() => mutate("/api/manage/admin/connector/indexing-status")}
        />
      ) : (
        <p className="text-sm">No indexed websites found</p>
      )}
    </div>
  );
}
