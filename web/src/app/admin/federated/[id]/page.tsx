"use client";

import { useState, useEffect } from "react";
import { notFound } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useFederatedConnector } from "./useFederatedConnector";
import { FederatedConnectorForm } from "@/components/admin/federated/FederatedConnectorForm";

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
    return (
      <div className="flex justify-center w-full h-full">
        <div className="mt-12 w-full max-w-4xl mx-auto">
          <div className="flex flex-col items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-blue-500 mb-4" />
            <div className="text-center">
              <p className="text-lg font-medium text-gray-700 mb-2">
                Loading connector configuration...
              </p>
              <p className="text-sm text-gray-500">
                Retrieving connector details and credential schema
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex justify-center w-full h-full">
        <div className="mt-12 w-full max-w-4xl mx-auto">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-red-600 mb-4">Error</h1>
            <p className="text-gray-600">{error}</p>
          </div>
        </div>
      </div>
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
