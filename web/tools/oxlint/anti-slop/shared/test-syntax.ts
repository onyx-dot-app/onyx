import type { ESTree } from "@oxlint/plugins";

export function staticText(
  node: ESTree.Node | null | undefined
): string | undefined {
  if (node?.type === "Literal" && typeof node.value === "string") {
    return node.value;
  }
  if (node?.type === "TemplateLiteral" && node.expressions.length === 0) {
    return node.quasis[0]?.value.cooked ?? undefined;
  }
  return undefined;
}

/** Names along a call target, so `test.describe.configure(...)` gives `["test", "describe", "configure"]`. */
export function callPath(node: ESTree.Node | null | undefined): string[] {
  switch (node?.type) {
    case "Identifier":
      return [node.name];
    case "Literal": {
      const text = staticText(node);
      return text === undefined ? [] : [text];
    }
    case "MemberExpression": {
      const name =
        !node.computed && node.property.type === "Identifier"
          ? node.property.name
          : staticText(node.property);
      return name === undefined ? [] : [...callPath(node.object), name];
    }
    case "CallExpression":
      return callPath(node.callee);
    case "TaggedTemplateExpression":
      return callPath(node.tag);
    case "ChainExpression":
      return callPath(node.expression);
    default:
      return [];
  }
}

export function isFunction(
  node: ESTree.Node | null | undefined
): node is ESTree.ArrowFunctionExpression | ESTree.Function {
  return (
    node?.type === "ArrowFunctionExpression" ||
    node?.type === "FunctionExpression"
  );
}
