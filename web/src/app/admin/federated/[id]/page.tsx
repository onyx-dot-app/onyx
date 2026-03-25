"use client";

import { useState, useEffect } from "react";
import { notFound } from "next/navigation";
import { useFederatedConnector } from "./useFederatedConnector";
import { FederatedConnectorForm } from "@/components/admin/federated/FederatedConnectorForm";
import ResourceErrorPage from "@/sections/error/ResourceErrorPage";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";

export default function EditFederatedConnectorPage(props: {
  params: Promise<{ id: string }>;
}) {
  const [params, setParams] = useState<{ id: string } | null>(null);

  useEffect(() => {
    props.params.then(setParams);
  }, [props.params]);

  const { sourceType, connectorData, credentialSchema, isLoading, error } =
    useFederatedConnector(params?.id ?? "");

  if (isLoading) {
    return <SimpleLoader />;
  }

  if (error) {
    return (
      <ResourceErrorPage
        errorType="fetch_error"
        description={error}
        backHref="/admin/federated"
        backLabel="Back to federated connectors"
      />
    );
  }

  if (!sourceType || !params) {
    notFound();
  }

  const connectorId = parseInt(params.id);

  return (
    <div className="flex justify-center w-full h-full">
      <div className="mt-12 w-full max-w-4xl mx-auto">
        <FederatedConnectorForm
          connector={sourceType}
          connectorId={connectorId}
          preloadedConnectorData={connectorData ?? undefined}
          preloadedCredentialSchema={credentialSchema ?? undefined}
        />
      </div>
    </div>
  );
}
