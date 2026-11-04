import "@opal/components/inputs/shared.css";
import { IconContainer } from "@opal/components/icon-container/components";
import type { IconFunctionComponent } from "@opal/types";

interface InputLeadingIconProps {
  icon: IconFunctionComponent;
  /** `text-02` instead of the icon container's `text-03` (the search icon). */
  muted?: boolean;
}

/**
 * The icon at the start of an input's content row (InputTypeIn, the upload
 * inputs, TagField): a bare 20px main-ui icon container.
 */
function InputLeadingIcon({ icon, muted = false }: InputLeadingIconProps) {
  return (
    <div className="opal-input-leading-icon" data-muted={muted || undefined}>
      <IconContainer size="main-ui" icon={icon} />
    </div>
  );
}

export { InputLeadingIcon, type InputLeadingIconProps };
