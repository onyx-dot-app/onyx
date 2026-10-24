import type { ESTree } from "@oxlint/plugins";

/**
 * Static class names in a `className` value: string literals, template literal
 * text and the string parts of `cn(...)` / `clsx(...)` calls, conditionals,
 * logical expressions, arrays and object keys. Tokens keep their variant
 * prefixes; use `baseClass` to strip them.
 */
export function staticClassNames(
  value: ESTree.JSXAttribute["value"]
): string[] {
  const strings: string[] = [];
  const visit = (node: ESTree.Node | null | undefined): void => {
    if (!node) return;
    switch (node.type) {
      case "Literal":
        if (typeof node.value === "string") strings.push(node.value);
        return;
      case "TemplateLiteral":
        node.quasis.forEach((quasi) => strings.push(quasi.value.raw));
        node.expressions.forEach(visit);
        return;
      case "JSXExpressionContainer":
        visit(node.expression);
        return;
      case "CallExpression":
        node.arguments.forEach(visit);
        return;
      case "ConditionalExpression":
        visit(node.consequent);
        visit(node.alternate);
        return;
      case "LogicalExpression":
        visit(node.left);
        visit(node.right);
        return;
      case "ArrayExpression":
        node.elements.forEach(visit);
        return;
      case "ObjectExpression":
        node.properties.forEach((property) => {
          if (property.type !== "Property") return;
          if (property.key.type === "Identifier" && !property.computed) {
            strings.push(property.key.name);
          } else {
            visit(property.key);
          }
        });
        return;
      default:
        return;
    }
  };
  visit(value);
  return strings.flatMap((text) => text.split(/\s+/)).filter(Boolean);
}

/** A class name without its variant prefixes (`md:`, `hover:`) and `!` marker. */
export function baseClass(token: string): string {
  return (token.split(":").pop() ?? "").replace(/^!|!$/g, "");
}

/** The `className` attribute of a JSX element, if it has one. */
export function classNameAttribute(
  node: ESTree.JSXOpeningElement
): ESTree.JSXAttribute | null {
  for (const attribute of node.attributes) {
    if (
      attribute.type === "JSXAttribute" &&
      attribute.name.type === "JSXIdentifier" &&
      attribute.name.name === "className"
    ) {
      return attribute;
    }
  }
  return null;
}
