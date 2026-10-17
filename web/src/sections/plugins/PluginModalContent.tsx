import type { ComponentProps } from "react";
import { Modal } from "@opal/components";

type PluginModalContentProps = Omit<
  ComponentProps<typeof Modal.Content>,
  "width" | "height" | "position" | "preventAccidentalClose"
>;

export default function PluginModalContent(props: PluginModalContentProps) {
  return (
    <Modal.Content
      {...props}
      width="md"
      height="fit"
      position="top"
      preventAccidentalClose={false}
    />
  );
}
