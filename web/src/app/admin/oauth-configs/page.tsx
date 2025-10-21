"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { KeyIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { mutate } from "swr";
import { Separator } from "@/components/ui/separator";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Table,
} from "@/components/ui/table";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useState } from "react";
import { DeleteButton } from "@/components/DeleteButton";
import { FiEdit2 } from "react-icons/fi";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { OAuthConfig } from "@/lib/tools/interfaces";
import { deleteOAuthConfig } from "@/lib/oauth/api";
import { OAuthConfigForm } from "./OAuthConfigForm";

function Main() {
  const { popup, setPopup } = usePopup();

  const {
    data: oauthConfigs,
    isLoading,
    error,
  } = useSWR<OAuthConfig[]>("/api/admin/oauth-config", errorHandlingFetcher);

  const [showCreateUpdateForm, setShowCreateUpdateForm] = useState(false);
  const [selectedConfig, setSelectedConfig] = useState<
    OAuthConfig | undefined
  >();

  const handleEdit = (config: OAuthConfig) => {
    setSelectedConfig(config);
    setShowCreateUpdateForm(true);
  };

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (!oauthConfigs || error) {
    return (
      <ErrorCallout
        errorTitle="Failed to fetch OAuth configurations"
        errorMsg={error?.info?.detail || error?.toString()}
      />
    );
  }

  const newConfigButton = (
    <CreateButton onClick={() => setShowCreateUpdateForm(true)}>
      Create OAuth Configuration
    </CreateButton>
  );

  if (oauthConfigs.length === 0) {
    return (
      <div>
        {popup}
        <Text>
          OAuth configurations allow your custom tools to authenticate with
          external services. Create a configuration below to get started.
        </Text>
        <div className="mt-4">{newConfigButton}</div>

        {showCreateUpdateForm && (
          <OAuthConfigForm
            onClose={() => {
              setShowCreateUpdateForm(false);
              setSelectedConfig(undefined);
              mutate("/api/admin/oauth-config");
            }}
            setPopup={setPopup}
            config={selectedConfig}
          />
        )}
      </div>
    );
  }

  return (
    <div>
      {popup}

      <Text>
        OAuth configurations allow your custom tools to authenticate with
        external services. Each configuration can be shared across multiple
        tools.
      </Text>
      <div className="mt-4">{newConfigButton}</div>

      <Separator />

      <Title className="mt-6">Existing OAuth Configurations</Title>
      <Table className="overflow-visible">
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Provider</TableHead>
            <TableHead>Authorization URL</TableHead>
            <TableHead>Token URL</TableHead>
            <TableHead>Scopes</TableHead>
            <TableHead>Tools Using</TableHead>
            <TableHead>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {oauthConfigs.map((config) => (
            <TableRow key={config.id}>
              <TableCell>
                <div
                  className="my-auto flex mb-1 w-fit hover:bg-accent-background-hovered cursor-pointer p-2 rounded-lg border-border text-sm"
                  onClick={() => handleEdit(config)}
                >
                  <FiEdit2 className="my-auto mr-2" />
                  {config.name}
                </div>
              </TableCell>
              <TableCell>{config.provider}</TableCell>
              <TableCell className="max-w-64 truncate">
                {config.authorization_url}
              </TableCell>
              <TableCell className="max-w-64 truncate">
                {config.token_url}
              </TableCell>
              <TableCell>
                {config.scopes ? config.scopes.join(", ") : "None"}
              </TableCell>
              <TableCell>{config.tool_count}</TableCell>
              <TableCell>
                <DeleteButton
                  onClick={async () => {
                    try {
                      await deleteOAuthConfig(config.id);
                      setPopup({
                        type: "success",
                        message: "Successfully deleted OAuth configuration!",
                      });
                      mutate("/api/admin/oauth-config");
                    } catch (error: any) {
                      setPopup({
                        type: "error",
                        message: `Failed to delete OAuth configuration: ${error.message}`,
                      });
                    }
                  }}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {showCreateUpdateForm && (
        <OAuthConfigForm
          onClose={() => {
            setShowCreateUpdateForm(false);
            setSelectedConfig(undefined);
            mutate("/api/admin/oauth-config");
          }}
          setPopup={setPopup}
          config={selectedConfig}
        />
      )}
    </div>
  );
}

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="OAuth Configurations"
        icon={<KeyIcon size={32} />}
      />

      <Main />
    </div>
  );
}
