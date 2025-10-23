import { OAuthConfig } from "@/lib/tools/interfaces";
import { SelectorFormField } from "@/components/Field";
import Button from "@/refresh-components/buttons/Button";
import SvgPlusCircle from "@/icons/plus-circle";
import { useState } from "react";
import { OAuthConfigForm } from "@/app/admin/oauth-configs/OAuthConfigForm";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { useFormikContext } from "formik";
import CreateButton from "@/refresh-components/buttons/CreateButton";

interface OAuthConfigSelectorProps {
  name: string;
  label?: string;
  oauthConfigs: OAuthConfig[];
  onSelect?: (configId: number | null) => void;
  onConfigCreated?: (config: OAuthConfig) => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
}

export const OAuthConfigSelector = ({
  name,
  label = "OAuth Configuration:",
  oauthConfigs,
  onSelect,
  onConfigCreated,
  setPopup,
}: OAuthConfigSelectorProps) => {
  const [showModal, setShowModal] = useState(false);
  const { setFieldValue } = useFormikContext();

  const options = [
    { name: "None", value: -1 },
    ...oauthConfigs.map((config) => ({
      name: config.name,
      value: config.id,
    })),
  ];

  const handleConfigCreated = (createdConfig: OAuthConfig) => {
    // First, update the parent with the new config so it's added to the list
    if (onConfigCreated) {
      onConfigCreated(createdConfig);
    }

    // Wait a moment for the options list to update before setting the field value
    // This ensures the new config is in the options when the selector tries to find it
    setTimeout(() => {
      // Now set the newly created config as selected
      setFieldValue(name, createdConfig.id.toString(), true);

      // Call the onSelect callback if provided
      if (onSelect) {
        onSelect(createdConfig.id);
      }
    }, 100);
  };

  const handleModalClose = () => {
    setShowModal(false);
  };

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
      <CreateButton onClick={() => setShowModal(true)}>
        New OAuth Configuration
      </CreateButton>

      {showModal && (
        <OAuthConfigForm
          onClose={handleModalClose}
          setPopup={setPopup}
          onConfigCreated={handleConfigCreated}
        />
      )}
    </div>
  );
};
