"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/components/user/UserProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { usePopup } from "@/components/admin/connectors/Popup";
import { BackButton } from "@/components/BackButton";
import { LoadingAnimation } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { Modal } from "@/components/Modal";
import { FiTrash2, FiEdit, FiSave, FiX } from "react-icons/fi";

interface FederatedConnectorDetail {
  id: number;
  source: string;
  name: string;
  credentials: {
    client_id?: string;
    client_secret?: string;
    redirect_uri?: string;
    [key: string]: any;
  };
  oauth_token_exists: boolean;
  oauth_token_expires_at?: string;
  document_sets: Array<{
    id: number;
    name: string;
    entities: any;
  }>;
}

export default function FederatedConnectorPage(props: {
  params: Promise<{ id: string }>;
}) {
  const router = useRouter();
  const { user } = useUser();
  const { popup, setPopup } = usePopup();

  const [params, setParams] = useState<{ id: string } | null>(null);
  const [connector, setConnector] = useState<FederatedConnectorDetail | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editedCredentials, setEditedCredentials] = useState<any>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Handle async params
  useEffect(() => {
    props.params.then(setParams);
  }, [props.params]);

  const fetchConnector = async () => {
    if (!params?.id) return;

    try {
      const response = await fetch(`/api/federated/${params.id}`);
      if (!response.ok) {
        throw new Error("Failed to fetch federated connector");
      }
      const data = await response.json();
      setConnector(data);
      setEditedCredentials(data.credentials);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (params?.id) {
      fetchConnector();
    }
  }, [params?.id]);

  const handleSave = async () => {
    if (!connector || !params?.id) return;

    setIsSaving(true);
    try {
      const response = await fetch(`/api/federated/${params.id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          credentials: editedCredentials,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to update federated connector");
      }

      const result = await response.json();
      setConnector(result.data);
      setIsEditing(false);
      setPopup({
        message: "Federated connector updated successfully",
        type: "success",
      });
    } catch (err) {
      setPopup({
        message:
          err instanceof Error ? err.message : "Failed to update connector",
        type: "error",
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!params?.id) return;

    setIsDeleting(true);
    try {
      const response = await fetch(`/api/federated/${params.id}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        throw new Error("Failed to delete federated connector");
      }

      setPopup({
        message: "Federated connector deleted successfully",
        type: "success",
      });
      router.push("/admin/indexing/status");
    } catch (err) {
      setPopup({
        message:
          err instanceof Error ? err.message : "Failed to delete connector",
        type: "error",
      });
      setIsDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center w-full h-full">
        <div className="mt-12 w-full max-w-4xl mx-auto">
          <BackButton />
          <div className="flex justify-center items-center h-64">
            <LoadingAnimation text="Loading federated connector..." />
          </div>
        </div>
      </div>
    );
  }

  if (error || !connector) {
    return (
      <div className="flex justify-center w-full h-full">
        <div className="mt-12 w-full max-w-4xl mx-auto">
          <BackButton />
          <ErrorCallout
            errorTitle="Failed to load federated connector"
            errorMsg={error || "Connector not found"}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-center w-full h-full">
      <div className="mt-12 w-full max-w-4xl mx-auto">
        <BackButton />

        <div className="mb-4 flex justify-between items-center">
          <h1 className="text-3xl font-bold">
            Federated Connector: {connector.name}
          </h1>
          <div className="flex gap-2">
            {!isEditing ? (
              <>
                <Button onClick={() => setIsEditing(true)} variant="outline">
                  <FiEdit className="mr-2" />
                  Edit
                </Button>
                <Button
                  variant="destructive"
                  disabled={isDeleting}
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  <FiTrash2 className="mr-2" />
                  Delete
                </Button>
              </>
            ) : (
              <>
                <Button onClick={handleSave} disabled={isSaving}>
                  <FiSave className="mr-2" />
                  Save
                </Button>
                <Button
                  onClick={() => {
                    setIsEditing(false);
                    setEditedCredentials(connector.credentials);
                  }}
                  variant="outline"
                >
                  <FiX className="mr-2" />
                  Cancel
                </Button>
              </>
            )}
          </div>
        </div>

        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Basic Information</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label>Source</Label>
                <p className="text-sm text-muted-foreground">
                  {connector.source}
                </p>
              </div>
              <div>
                <Label>OAuth Status</Label>
                <div className="flex items-center gap-2 mt-1">
                  <Badge
                    variant={
                      connector.oauth_token_exists ? "success" : "secondary"
                    }
                  >
                    {connector.oauth_token_exists
                      ? "Connected"
                      : "Not Connected"}
                  </Badge>
                  {connector.oauth_token_expires_at && (
                    <span className="text-sm text-muted-foreground">
                      Expires:{" "}
                      {new Date(
                        connector.oauth_token_expires_at
                      ).toLocaleString()}
                    </span>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Credentials</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {Object.entries(editedCredentials).map(([key, value]) => (
                <div key={key}>
                  <Label htmlFor={key}>
                    {key
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (l) => l.toUpperCase())}
                  </Label>
                  <Input
                    id={key}
                    type={key.includes("secret") ? "password" : "text"}
                    value={String(value || "")}
                    onChange={(e) =>
                      setEditedCredentials({
                        ...editedCredentials,
                        [key]: e.target.value,
                      })
                    }
                    disabled={!isEditing}
                    className="mt-1"
                  />
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Delete Confirmation Modal */}
        {showDeleteConfirm && (
          <Modal
            onOutsideClick={() => setShowDeleteConfirm(false)}
            title="Are you sure?"
            width="max-w-md"
          >
            <div className="space-y-4">
              <p>
                This action cannot be undone. This will permanently delete the
                federated connector and remove all associated configurations.
              </p>
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => setShowDeleteConfirm(false)}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => {
                    setShowDeleteConfirm(false);
                    handleDelete();
                  }}
                  disabled={isDeleting}
                >
                  Delete Connector
                </Button>
              </div>
            </div>
          </Modal>
        )}

        {popup}
      </div>
    </div>
  );
}
