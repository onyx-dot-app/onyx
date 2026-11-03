import { defineRule } from "@oxlint/plugins";

/** A path into the main app: `/app`, `/app/…` or `/app?…`. */
function isAppPath(path: string): boolean {
  return (
    path === "/app" || path.startsWith("/app/") || path.startsWith("/app?")
  );
}

interface StringLike {
  type: string;
  value?: unknown;
  quasis?: { value: { cooked: string | null } }[];
}

/** The static start of a string literal or template literal, else null. */
function staticPrefix(node: StringLike | null | undefined): string | null {
  if (!node) return null;
  if (node.type === "Literal" && typeof node.value === "string") {
    return node.value;
  }
  if (node.type === "TemplateLiteral" && node.quasis && node.quasis[0]) {
    return node.quasis[0].value.cooked;
  }
  return null;
}

/**
 * Flags navigation into the main app that bypasses `AppPosition`: a
 * `router.push` / `router.replace` call or an `href` whose path starts with
 * `/app`. `AppPosition`'s `open*` and `linkTo*` write the URL at once, so the
 * tab, the chrome and the page's loader follow the click; a direct navigation
 * waits for Next to render the page first.
 */
export const noDirectAppNavigationRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Navigate within the app through AppPosition (open* / linkTo*), not router.push or a bare href.",
    },
    messages: {
      routerCall:
        "`{{method}}` to `{{path}}` bypasses AppPosition, so the URL and the tab wait for the page to render. Use `useAppPosition().open…()` (add a position to `lib/position/hooks.ts` if none fits).",
      href: "`href` to `{{path}}` bypasses AppPosition, so the URL and the tab wait for the page to render. Spread `useAppPosition().linkTo…()` (add a position to `lib/position/hooks.ts` if none fits).",
    },
  },
  createOnce(context) {
    return {
      CallExpression(node) {
        const callee = node.callee;
        if (callee.type !== "MemberExpression" || callee.computed) return;
        if (callee.property.type !== "Identifier") return;
        const method = callee.property.name;
        if (method !== "push" && method !== "replace") return;
        // A router call, not an array's push: `router.push`, `this.router.push`.
        const object = callee.object;
        const objectName =
          object.type === "Identifier"
            ? object.name
            : object.type === "MemberExpression" &&
                object.property.type === "Identifier"
              ? object.property.name
              : null;
        if (objectName === null || !/router$/i.test(objectName)) return;
        const path = staticPrefix(node.arguments[0] as StringLike | undefined);
        if (path === null || !isAppPath(path)) return;
        context.report({
          node,
          messageId: "routerCall",
          data: { method: `${objectName}.${method}`, path },
        });
      },
      JSXAttribute(node) {
        if (node.name.type !== "JSXIdentifier" || node.name.name !== "href") {
          return;
        }
        const value = node.value;
        const expression =
          value?.type === "JSXExpressionContainer" ? value.expression : value;
        const path = staticPrefix(expression as StringLike | null | undefined);
        if (path === null || !isAppPath(path)) return;
        context.report({ node, messageId: "href", data: { path } });
      },
    };
  },
});
