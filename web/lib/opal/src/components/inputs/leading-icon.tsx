import "@opal/components/inputs/shared.css";
import { IconContainer } from "@opal/components/icon-container/components";
import type { IconFunctionComponent } from "@opal/types";

interface InputLeadingIconProps {
  icon: IconFunctionComponent;
  /** `text-02` instead of the icon container's `text-03` (the search icon). */
  muted?: boolean;
}

/**
 * The icon at the start of an input row (InputTypeIn, the upload inputs,
 * TagField): a 20px main-ui icon container in 2px of padding, one 24px row
 * tall. The field's own 2px start padding completes the 4px gap to the text.
 */
function InputLeadingIcon({ icon, muted = false }: InputLeadingIconProps) {
  return (
    <div className="opal-input-leading-icon" data-muted={muted || undefined}>
      <IconContainer size="main-ui" icon={icon} />
    </div>
  );
}

export { InputLeadingIcon, type InputLeadingIconProps };
