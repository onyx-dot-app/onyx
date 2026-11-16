import { defineRule } from "@oxlint/plugins";

const ROUTER_METHODS = new Set(["push", "replace", "back"]);

const HISTORY_METHODS = new Set(["pushState", "replaceState", "back"]);

// `NavLink` goes through @opal/navigation; the SVG elements reference a
// resource or a fragment of the document, not a page.
const NOT_NAVIGATING_ELEMENTS = new Set([
  "NavLink",
  "use",
  "image",
  "feImage",
  "linearGradient",
  "radialGradient",
  "pattern",
  "filter",
  "textPath",
  "mpath",
  "tref",
]);

const LOCATION_METHODS = new Set(["assign", "replace", "reload"]);

interface StringLike {
  type: string;
  value?: unknown;
  quasis?: { value: { cooked: string | null } }[];
}

/** The static start of a string literal or template literal, else null. */
function staticPrefix(node: StringLike | null | undefined): string | null {
  if (!node) return null;
  if (
    (node.type === "Literal" || node.type === "StringLiteral") &&
    typeof node.value === "string"
  ) {
    return node.value;
  }
  if (node.type === "TemplateLiteral" && node.quasis && node.quasis[0]) {
    return node.quasis[0].value.cooked;
  }
  return null;
}

/**
 * A link to a page of this app: a path (`/admin/users`), a query (`?a=1`), a
 * hash (`#top`) or a relative path. Not another site (`//host`, `https:`),
 * a backend route (`/api/…`, which a link downloads or loads in full), or
 * another scheme (`mailto:`, `tel:`).
 */
function isAppPagePath(path: string): boolean {
  if (path === "" || path.startsWith("//")) return false;
  if (/^[a-z][a-z0-9+.-]*:/i.test(path)) return false;
  return !path.startsWith("/api/");
}

interface NodeLike {
  type: string;
  name?: string;
  computed?: boolean;
  object?: NodeLike;
  property?: NodeLike;
}

/**
 * `window.location` or `globalThis.location`. A bare `location` may be a local
 * (a test's stub), so it is not matched.
 */
function isLocation(node: NodeLike | undefined): boolean {
  if (!node) return false;
  return (
    node.type === "MemberExpression" &&
    !node.computed &&
    node.property?.type === "Identifier" &&
    node.property.name === "location" &&
    node.object?.type === "Identifier" &&
    (node.object.name === "window" || node.object.name === "globalThis")
  );
}

/** The last name in `router` or `this.router`, else null. */
function memberName(node: NodeLike | undefined): string | null {
  if (!node) return null;
  if (node.type === "Identifier") return node.name ?? null;
  if (
    node.type === "MemberExpression" &&
    !node.computed &&
    node.property?.type === "Identifier"
  ) {
    return node.property.name ?? null;
  }
  return null;
}

/**
 * Keeps all navigation in `@opal/navigation`: it flags any import of
 * `next/navigation` or `next/link`, a router's `push`, `replace` or `back`, a
 * `history.pushState`, `replaceState` or `back`, a write to `window.location`,
 * and a static internal `href`. `go`, `linkTo` and `clampedBack` write the URL
 * at once, so the tabs and the page's loader follow the click; the rest wait
 * for Next to render the page, and a bare back can leave the app.
 */
export const noNakedNavigationRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Navigate only through @opal/navigation (go, linkTo, clampedBack, NavLink, and its re-exports of Next's helpers).",
    },
    messages: {
      import:
        "Import from `@opal/navigation`, not `{{source}}`: it re-exports `usePathname`, `useSearchParams`, `useParams`, `redirect` and `notFound`, and `useNavigation()` covers the router (`go`, `refresh`, `prefetch`, `clampedBack`). `NavLink` replaces `next/link`.",
      router:
        "`{{call}}` skips @opal/navigation, so the URL and the tabs wait for the page to render. Use `useNavigation().go(…)` (with `{ replace: true }` for a replace), `clampedBack(fallback)` for back, or a `useAppPosition()` method.",
      history:
        "`{{call}}` skips @opal/navigation. Use `useNavigation().go(…)`, or `clampedBack(fallback)` for back.",
      location:
        "Writing `window.location` skips @opal/navigation. Use `useNavigation().load()` or `reload()` (or `loadPage()` outside a component) for a full page load, or `go()` for a page of the app.",
      href: "`href` to `{{path}}` skips the URL-first switch of @opal/navigation, so the URL, the tabs and the loader do not move with the click. Spread `useNavigation().linkTo(…)` (or a `useAppPosition().linkTo…()`), or use `NavLink`.",
    },
  },
  createOnce(context) {
    return {
      ImportDeclaration(node) {
        const source = node.source.value;
        if (source === "next/navigation" || source === "next/link") {
          context.report({ node, messageId: "import", data: { source } });
        }
      },
      AssignmentExpression(node) {
        const left = node.left as NodeLike;
        // `window.location = …`, or a write to any of its parts (`href`,
        // `pathname`, `search`, `hash`).
        const writesLocation =
          isLocation(left) ||
          (left.type === "MemberExpression" && isLocation(left.object));
        if (writesLocation) context.report({ node, messageId: "location" });
      },
      CallExpression(node) {
        const callee = node.callee as NodeLike;
        if (
          callee.type !== "MemberExpression" ||
          callee.computed ||
          callee.property?.type !== "Identifier"
        ) {
          return;
        }
        const method = callee.property.name ?? "";
        if (LOCATION_METHODS.has(method) && isLocation(callee.object)) {
          context.report({ node, messageId: "location" });
          return;
        }
        const objectName = memberName(callee.object);
        if (objectName === null) return;
        // `router.push`, `this.router.replace`; not an array's push.
        if (ROUTER_METHODS.has(method) && /router$/i.test(objectName)) {
          context.report({
            node,
            messageId: "router",
            data: { call: `${objectName}.${method}` },
          });
          return;
        }
        // `history.pushState`, `window.history.back`.
        if (HISTORY_METHODS.has(method) && objectName === "history") {
          context.report({
            node,
            messageId: "history",
            data: { call: `history.${method}` },
          });
        }
      },
      JSXAttribute(node) {
        if (node.name.type !== "JSXIdentifier" || node.name.name !== "href") {
          return;
        }
        const element = node.parent;
        if (
          element.type === "JSXOpeningElement" &&
          element.name.type === "JSXIdentifier" &&
          NOT_NAVIGATING_ELEMENTS.has(element.name.name)
        ) {
          return;
        }
        const value = node.value;
        const expression =
          value?.type === "JSXExpressionContainer" ? value.expression : value;
        const path = staticPrefix(expression as StringLike | null | undefined);
        if (path === null || !isAppPagePath(path)) return;
        context.report({ node, messageId: "href", data: { path } });
      },
    };
  },
});
