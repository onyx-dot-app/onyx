import { defineRule } from "@oxlint/plugins";

import {
  baseClass,
  classNameAttribute,
  staticClassNames,
} from "../shared/class-names.ts";

const LAYOUT_ELEMENTS = new Set(["div", "span"]);
const LAYOUT_CLASS =
  /^(flex|inline-flex|grid|inline-grid|items-.+|justify-.+|gap-.+|gap-[xy]-.+)$/;

/**
 * Flags a `<div>` or `<span>` that hand-rolls a flex or grid container.
 * `Section` from `@opal/layouts` is the layout container; it takes className, a
 * ref and event handlers, so there is no reason to drop to a raw element.
 */
export const noLayoutDivRule = defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow raw div/span flex and grid containers; use Opal layouts.",
    },
    messages: {
      layoutDiv:
        "`<{{element}}>` with `{{className}}` is a hand-rolled layout container. Use `Section` from `@opal/layouts` (flexDirection, justifyContent, alignItems, gap, padding props), or `Content`, `ContentAction`, `Card`, `InputHorizontal`/`InputVertical` or `Divider`.",
    },
  },
  createOnce(context) {
    return {
      JSXOpeningElement(node) {
        if (
          node.name.type !== "JSXIdentifier" ||
          !LAYOUT_ELEMENTS.has(node.name.name)
        ) {
          return;
        }
        const attribute = classNameAttribute(node);
        if (attribute === null) return;
        const className = staticClassNames(attribute.value).find((name) =>
          LAYOUT_CLASS.test(baseClass(name))
        );
        if (className === undefined) return;
        context.report({
          node: attribute,
          messageId: "layoutDiv",
          data: { element: node.name.name, className },
        });
      },
    };
  },
});
