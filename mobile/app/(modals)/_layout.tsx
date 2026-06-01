// Modals group. The root Stack already presents the whole (modals) group with
// presentation: "modal" (native sheet); this inner Stack just groups the modal
// routes. Native confirm dialogs use a bottom-sheet primitive, not this group.
import { HiddenHeaderStack } from "@/components/HiddenHeaderStack";

export default HiddenHeaderStack;
