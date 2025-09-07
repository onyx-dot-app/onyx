"use client";

import { useEffect, useState } from "react";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";

export default function LinearAppCredential({
  onChange,
}: {
  onChange?: (values: { client_id: string; client_secret: string }) => void;
}) {
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(
          "/api/manage/admin/connector/linear/app-credential"
        );
        if (res.ok) {
          const json = (await res.json()) as { client_id?: string };
          setClientId(json.client_id || "");
          if (onChange) {
            onChange({ client_id: json.client_id || "", client_secret: "" });
          }
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return null;

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="linear_client_id">Linear Client ID</Label>
        <Input
          id="linear_client_id"
          value={clientId}
          onChange={(e) => {
            const v = e.target.value;
            setClientId(v);
            if (onChange)
              onChange({ client_id: v, client_secret: clientSecret });
          }}
        />
      </div>
      <div>
        <Label htmlFor="linear_client_secret">Linear Client Secret</Label>
        <Input
          id="linear_client_secret"
          type="password"
          value={clientSecret}
          onChange={(e) => {
            const v = e.target.value;
            setClientSecret(v);
            if (onChange) onChange({ client_id: clientId, client_secret: v });
          }}
        />
      </div>
    </div>
  );
}
