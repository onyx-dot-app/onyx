import type { ESTree } from "@oxlint/plugins";

export function staticText(node: ESTree.Node | undefined): string | undefined {
  if (node?.type === "Literal" && typeof node.value === "string") {
    return node.value;
  }
  if (node?.type === "TemplateLiteral" && node.expressions.length === 0) {
    return node.quasis[0]?.value.cooked ?? undefined;
  }
}

export function staticName(
  node: ESTree.Node,
  computed: boolean
): string | undefined {
  return !computed && node.type === "Identifier" ? node.name : staticText(node);
}

export function callPath(node: ESTree.Node | undefined): string[] {
  if (!node) return [];
  switch (node.type) {
    case "Identifier":
      return [node.name];
    case "MemberExpression": {
      const name = staticName(node.property, node.computed);
      return name === undefined ? [] : [...callPath(node.object), name];
    }
    case "CallExpression":
      return callPath(node.callee);
    case "TaggedTemplateExpression":
      return callPath(node.tag);
    case "ChainExpression":
    case "TSAsExpression":
    case "TSNonNullExpression":
    case "TSSatisfiesExpression":
      return callPath(node.expression);
    default:
      return [];
  }
}

export function globalPath(node: ESTree.Node | undefined): string {
  const path = callPath(node);
  if (["global", "globalThis", "self", "window"].includes(path[0] ?? "")) {
    return path.slice(1).join(".");
  }
  return path.join(".");
}

export function option(
  node: ESTree.Node | undefined,
  name: string
): ESTree.Node | undefined {
  if (node?.type !== "ObjectExpression") return undefined;
  for (const property of node.properties) {
    if (
      property.type === "Property" &&
      staticName(property.key, property.computed) === name
    ) {
      return property.value;
    }
  }
  return undefined;
}

export function isFunction(
  node: ESTree.Node | undefined | null
): node is ESTree.ArrowFunctionExpression | ESTree.Function {
  return (
    node?.type === "ArrowFunctionExpression" ||
    node?.type === "FunctionDeclaration" ||
    node?.type === "FunctionExpression"
  );
}

export function isPromise(
  node: ESTree.Node | undefined | null
): node is ESTree.NewExpression {
  return (
    node?.type === "NewExpression" && globalPath(node.callee) === "Promise"
  );
}

export function inPromiseExecutor(node: ESTree.Node): boolean {
  for (let parent = node.parent; parent; parent = parent.parent) {
    if (isFunction(parent) && isPromise(parent.parent)) {
      return parent.parent.arguments[0] === parent;
    }
  }
  return false;
}
