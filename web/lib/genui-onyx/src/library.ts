import { createLibrary } from "@onyx/genui";
import { onyxPromptAddons } from "./prompt-addons";

// Component definitions (real React bindings)
import { textComponent } from "./components/text";
import { buttonComponent } from "./components/button";
import { cardComponent } from "./components/card";
import { tagComponent } from "./components/tag";
import { tableComponent } from "./components/table";
import { inputComponent } from "./components/input";
import { iconButtonComponent } from "./components/icon-button";
import { codeComponent } from "./components/code";
import { dividerComponent } from "./components/divider";
import {
  stackComponent,
  rowComponent,
  columnComponent,
} from "./components/layout";
import { imageComponent } from "./components/image";
import { linkComponent } from "./components/link";
import { alertComponent } from "./components/alert";
import { listComponent } from "./components/list";

/**
 * The assembled Onyx component library for GenUI.
 *
 * All components are bound to real Opal / refresh-components React components.
 */
export const onyxLibrary = createLibrary(
  [
    // Layout
    stackComponent,
    rowComponent,
    columnComponent,
    cardComponent,
    dividerComponent,

    // Content
    textComponent,
    tagComponent,
    tableComponent,
    codeComponent,
    imageComponent,
    linkComponent,
    listComponent,

    // Interactive
    buttonComponent,
    iconButtonComponent,
    inputComponent,

    // Feedback
    alertComponent,
  ],
  {
    defaultPromptOptions: {
      streaming: true,
      additionalRules: onyxPromptAddons.rules,
      examples: onyxPromptAddons.examples,
    },
  }
);
