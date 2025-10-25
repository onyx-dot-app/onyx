import { OAuthConfig } from "@/lib/tools/interfaces";
import { SelectorFormField } from "@/components/Field";
import Button from "@/refresh-components/buttons/Button";
import SvgPlusCircle from "@/icons/plus-circle";
import { useState } from "react";
import { OAuthConfigForm } from "@/app/admin/oauth-configs/OAuthConfigForm";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { useFormikContext } from "formik";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { KeyedMutator } from "swr";
import SvgEdit from "@/icons/edit";

interface OAuthConfigSelectorProps {
  name: string;
  label?: string;
  oauthConfigs: OAuthConfig[];
  onSelect?: (configId: number | null) => void;
  onConfigCreated?: (config: OAuthConfig) => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  mutateOAuthConfigs?: KeyedMutator<OAuthConfig[]>;
}

export const OAuthConfigSelector = ({
  name,
  label = "OAuth Configuration:",
  oauthConfigs,
  onSelect,
  onConfigCreated,
  setPopup,
  mutateOAuthConfigs,
}: OAuthConfigSelectorProps) => {
  const [showModal, setShowModal] = useState(false);
  const [editingConfig, setEditingConfig] = useState<OAuthConfig | null>(null);
  const { setFieldValue, values } = useFormikContext<any>();

  // Get the currently selected config ID
  const selectedConfigId = values[name];

  const options = [
    { name: "None", value: -1 },
    ...oauthConfigs.map((config) => ({
      name: config.name,
      value: config.id,
    })),
  ];

  const handleConfigSaved = (savedConfig: OAuthConfig) => {
    const isCreating = !editingConfig;

    // Refresh the OAuth configs list
    if (mutateOAuthConfigs) {
      mutateOAuthConfigs();
    }

    // If creating a new config, also call the onConfigCreated callback
    // and select the new config
    if (isCreating && onConfigCreated) {
      onConfigCreated(savedConfig);

      // Wait a moment for the options list to update before setting the field value
      // This ensures the new config is in the options when the selector tries to find it
      setTimeout(() => {
        // Now set the newly created config as selected
        setFieldValue(name, savedConfig.id.toString(), true);

        // Call the onSelect callback if provided
        if (onSelect) {
          onSelect(savedConfig.id);
        }
      }, 100);
    }
  };

  const handleModalClose = () => {
    setShowModal(false);
    setEditingConfig(null);
  };

  const handleEditClick = () => {
    // Find the selected config
    const configId =
      typeof selectedConfigId === "string"
        ? parseInt(selectedConfigId)
        : selectedConfigId;
    const config = oauthConfigs.find((c) => c.id === configId);
    if (config) {
      setEditingConfig(config);
      setShowModal(true);
    }
  };

  // Check if a valid config is selected (not null and not "None")
  const hasValidSelection =
    selectedConfigId &&
    selectedConfigId !== -1 &&
    selectedConfigId !== "-1" &&
    selectedConfigId !== "null";

  return (
    <div className="space-y-2">
      <SelectorFormField
        name={name}
        label={label}
        options={options}
        subtext="Select an OAuth configuration for this tool. Users will be prompted to authenticate when using this tool."
        onSelect={(selected) => {
          // SelectorFormField passes the value string directly, not an object
          let configId: number | null;
          if (
            !selected ||
            selected === "null" ||
            selected === -1 ||
            selected === "-1"
          ) {
            configId = null;
          } else if (typeof selected === "number") {
            configId = selected;
          } else {
            configId = parseInt(selected);
          }
          if (onSelect) {
            onSelect(configId);
          }
        }}
      />
      <div className="flex gap-2">
        <CreateButton onClick={() => setShowModal(true)}>
          New OAuth Configuration
        </CreateButton>
        {hasValidSelection && (
          <Button
            onClick={handleEditClick}
            secondary
            leftIcon={SvgEdit}
            type="button"
          >
            Edit Configuration
          </Button>
        )}
      </div>

      {showModal && (
        <OAuthConfigForm
          onClose={handleModalClose}
          setPopup={setPopup}
          config={editingConfig || undefined}
          onConfigSubmitted={handleConfigSaved}
        />
      )}
    </div>
  );
};
