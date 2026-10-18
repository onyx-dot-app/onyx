import type { ComponentProps } from "react";
import { Modal } from "@opal/components";

type PluginModalContentProps = Omit<
  ComponentProps<typeof Modal.Content>,
  "width" | "height" | "maxHeight" | "position" | "preventAccidentalClose"
>;

export default function PluginModalContent(props: PluginModalContentProps) {
  return (
    <Modal.Content
      {...props}
      width="lg"
      height="fit"
      maxHeight="80dvh"
      position="top"
      preventAccidentalClose={false}
    />
  );
}
