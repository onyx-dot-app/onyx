"use client";

import React, { useState, useEffect } from "react";
import { AvatarQueryMode, AvatarUpdateRequest } from "@/lib/types";
import { useMyAvatar } from "@/lib/avatar";
import {
  Settings,
  Save,
  Loader2,
  Eye,
  EyeOff,
  Shield,
  Clock,
} from "lucide-react";

export function AvatarSettings() {
  const { avatar, loading, error, updateAvatar } = useMyAvatar();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [defaultQueryMode, setDefaultQueryMode] = useState<AvatarQueryMode>(
    AvatarQueryMode.OWNED_DOCUMENTS
  );
  const [allowAccessibleMode, setAllowAccessibleMode] = useState(true);
  const [showQueryInRequest, setShowQueryInRequest] = useState(true);
  const [maxRequestsPerDay, setMaxRequestsPerDay] = useState<number | null>(
    100
  );

  // Sync form state with loaded avatar
  useEffect(() => {
    if (avatar) {
      setName(avatar.name || "");
      setDescription(avatar.description || "");
      setIsEnabled(avatar.is_enabled);
      setDefaultQueryMode(avatar.default_query_mode);
      setAllowAccessibleMode(avatar.allow_accessible_mode);
      setShowQueryInRequest(avatar.show_query_in_request);
      setMaxRequestsPerDay(avatar.max_requests_per_day);
    }
  }, [avatar]);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    const updates: AvatarUpdateRequest = {
      name: name || null,
      description: description || null,
      is_enabled: isEnabled,
      default_query_mode: defaultQueryMode,
      allow_accessible_mode: allowAccessibleMode,
      show_query_in_request: showQueryInRequest,
      max_requests_per_day: maxRequestsPerDay,
    };

    try {
      await updateAvatar(updates);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Failed to save settings"
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-error/10 border border-error text-error rounded-lg">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Settings className="h-6 w-6 text-accent" />
        <h2 className="text-xl font-semibold">Avatar Settings</h2>
      </div>

      <div className="bg-background-subtle p-6 rounded-lg space-y-6">
        {/* Basic Info */}
        <div className="space-y-4">
          <h3 className="font-medium text-lg border-b border-border pb-2">
            Basic Information
          </h3>

          <div>
            <label className="block text-sm font-medium mb-1">
              Display Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Optional display name"
              className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-accent"
            />
            <p className="text-xs text-text-subtle mt-1">
              Leave empty to use your email address
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe your expertise or what others might find in your knowledge base"
              className="w-full px-3 py-2 border border-border rounded-lg bg-background min-h-[80px] resize-y focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </div>
        </div>

        {/* Availability */}
        <div className="space-y-4">
          <h3 className="font-medium text-lg border-b border-border pb-2 flex items-center gap-2">
            <Eye className="h-5 w-5" />
            Availability
          </h3>

          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={isEnabled}
              onChange={(e) => setIsEnabled(e.target.checked)}
              className="w-4 h-4 text-accent rounded"
            />
            <div>
              <span className="font-medium">Enable Avatar</span>
              <p className="text-xs text-text-subtle">
                When disabled, others cannot query your avatar
              </p>
            </div>
          </label>
        </div>

        {/* Query Settings */}
        <div className="space-y-4">
          <h3 className="font-medium text-lg border-b border-border pb-2 flex items-center gap-2">
            <Shield className="h-5 w-5" />
            Query Permissions
          </h3>

          <div>
            <label className="block text-sm font-medium mb-2">
              Default Query Mode
            </label>
            <select
              value={defaultQueryMode}
              onChange={(e) =>
                setDefaultQueryMode(e.target.value as AvatarQueryMode)
              }
              className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <option value={AvatarQueryMode.OWNED_DOCUMENTS}>
                Owned Documents Only
              </option>
              <option value={AvatarQueryMode.ACCESSIBLE_DOCUMENTS}>
                All Accessible Documents
              </option>
            </select>
          </div>

          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={allowAccessibleMode}
              onChange={(e) => setAllowAccessibleMode(e.target.checked)}
              className="w-4 h-4 text-accent rounded"
            />
            <div>
              <span className="font-medium">Allow "All Accessible" Mode</span>
              <p className="text-xs text-text-subtle">
                Let others request to query all documents you can access (with
                your approval)
              </p>
            </div>
          </label>

          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={showQueryInRequest}
              onChange={(e) => setShowQueryInRequest(e.target.checked)}
              className="w-4 h-4 text-accent rounded"
            />
            <div>
              <span className="font-medium">Show Query in Requests</span>
              <p className="text-xs text-text-subtle">
                See what others are asking when they request permission
              </p>
            </div>
          </label>
        </div>

        {/* Rate Limiting */}
        <div className="space-y-4">
          <h3 className="font-medium text-lg border-b border-border pb-2 flex items-center gap-2">
            <Clock className="h-5 w-5" />
            Rate Limiting
          </h3>

          <div>
            <label className="block text-sm font-medium mb-1">
              Max Requests Per Day (per user)
            </label>
            <input
              type="number"
              value={maxRequestsPerDay ?? ""}
              onChange={(e) =>
                setMaxRequestsPerDay(
                  e.target.value ? parseInt(e.target.value) : null
                )
              }
              placeholder="Unlimited"
              min={0}
              className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-accent"
            />
            <p className="text-xs text-text-subtle mt-1">
              Leave empty for unlimited requests
            </p>
          </div>
        </div>

        {/* Save Button */}
        <div className="flex items-center gap-4 pt-4 border-t border-border">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent-hover disabled:opacity-50 transition-colors"
          >
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Save className="h-4 w-4" />
                Save Settings
              </>
            )}
          </button>

          {saveSuccess && (
            <span className="text-success text-sm">Settings saved!</span>
          )}

          {saveError && <span className="text-error text-sm">{saveError}</span>}
        </div>
      </div>
    </div>
  );
}

export default AvatarSettings;
