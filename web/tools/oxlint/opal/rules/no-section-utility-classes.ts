import { defineRule } from "@oxlint/plugins";

import {
  baseClass,
  classNameAttribute,
  staticClassNames,
} from "../shared/class-names.ts";

const SECTION_SOURCES = new Set([
  "@opal/layouts",
  "@opal/layouts/general/components",
  "@/layouts/general-layouts",
]);
// Section sets `gap` and `padding` as inline styles, so these classes never apply.
const DEAD_CLASS = /^(p[xytrblse]?-.+|gap(-[xy])?-.+)$/;
// These apply (cn uses tailwind-merge), but they bypass the width/height props.
// min-*/max-* and responsive variants stay allowed: Section has no props for them.
const SIZE_CLASS = /^(w|h|size)-.+$/;

/**
 * Flags utility classes on an Opal `Section` that its props own. Padding and gap
 * classes are dead: Section always sets both as inline styles. Size classes
 * override the `width`/`height` defaults; use the props instead. Margin classes
 * stay allowed for asymmetric spacing.
 */
export const noSectionUtilityClassesRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow padding, gap and size classes on Section; use its props.",
    },
    messages: {
      deadClass:
        "`{{className}}` on `Section` is ignored: Section sets gap and padding as inline styles. Use `gap={n}` or `padding={n}` (N / 4 rem), or a margin class for asymmetric spacing.",
      sizeClass:
        '`{{className}}` on `Section` overrides its width/height defaults. Use `width`/`height` (`"auto" | "fit" | "full"` or a number in rem).',
    },
  },
  createOnce(context) {
    let sectionNames = new Set<string>();
    let namespaces = new Set<string>();
    return {
      Program() {
        sectionNames = new Set<string>();
        namespaces = new Set<string>();
      },
      ImportDeclaration(node) {
        if (!SECTION_SOURCES.has(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportNamespaceSpecifier") {
            namespaces.add(specifier.local.name);
            continue;
          }
          if (
            specifier.type === "ImportSpecifier" &&
            specifier.imported.type === "Identifier" &&
            specifier.imported.name === "Section"
          ) {
            sectionNames.add(specifier.local.name);
          }
        }
      },
      JSXOpeningElement(node) {
        const name = node.name;
        const isSection =
          (name.type === "JSXIdentifier" && sectionNames.has(name.name)) ||
          (name.type === "JSXMemberExpression" &&
            name.object.type === "JSXIdentifier" &&
            namespaces.has(name.object.name) &&
            name.property.name === "Section");
        if (!isSection) return;
        const attribute = classNameAttribute(node);
        if (attribute === null) return;
        for (const className of staticClassNames(attribute.value)) {
          const messageId = DEAD_CLASS.test(baseClass(className))
            ? "deadClass"
            : !className.includes(":") && SIZE_CLASS.test(className)
              ? "sizeClass"
              : null;
          if (messageId === null) continue;
          context.report({ node: attribute, messageId, data: { className } });
        }
      },
    };
  },
});
