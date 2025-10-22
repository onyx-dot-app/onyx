import { OAuthConfig } from "@/lib/tools/interfaces";
import { SelectorFormField } from "@/components/Field";
import Button from "@/refresh-components/buttons/Button";
import { FiPlus } from "react-icons/fi";
import { useState } from "react";
import { OAuthConfigForm } from "@/app/admin/oauth-configs/OAuthConfigForm";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { useFormikContext } from "formik";

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

    // Now set the newly created config as selected
    setFieldValue(name, createdConfig.id.toString(), true);

    // Call the onSelect callback if provided
    if (onSelect) {
      onSelect(createdConfig.id);
    }
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
          let configId: number;
          if (selected === null || selected === "null") {
            configId = -1;
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
      <Button onClick={() => setShowModal(true)} type="button" secondary>
        <FiPlus className="mr-1" />
        Create New OAuth Config
      </Button>

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
