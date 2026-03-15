import type {
  ASTNode,
  ComponentNode,
  ElementNode,
  ParseError,
  ParamDef,
} from "../types";
import type { Library } from "../types";

/**
 * Convert a resolved AST into an ElementNode tree.
 *
 * - Maps positional arguments to named props using ParamDef ordering
 * - Validates prop values against Zod schemas
 * - Unknown components produce errors but still render (as generic elements)
 */
export function validateAndTransform(
  node: ASTNode,
  library: Library,
): { element: ElementNode | null; errors: ParseError[] } {
  const errors: ParseError[] = [];
  const element = transformNode(node, library, errors);
  return { element, errors };
}

function transformNode(
  node: ASTNode,
  library: Library,
  errors: ParseError[],
): ElementNode | null {
  switch (node.kind) {
    case "component":
      return transformComponent(node, library, errors);

    case "literal":
      // Wrap literal strings in a Text element
      if (typeof node.value === "string") {
        return {
          kind: "element",
          component: "Text",
          props: { children: node.value },
          children: [],
        };
      }
      return null;

    case "array":
      // Array at root level → Stack wrapper
      return {
        kind: "element",
        component: "Stack",
        props: {},
        children: node.elements
          .map((el) => transformNode(el, library, errors))
          .filter((el): el is ElementNode => el !== null),
      };

    case "object":
      // Objects can't directly render — treat as props error
      errors.push({
        message: "Object literal cannot be rendered as a component",
        line: 0,
        column: 0,
      });
      return null;

    case "reference":
      // Unresolved reference — placeholder
      return {
        kind: "element",
        component: "__Unresolved",
        props: { name: node.name },
        children: [],
      };
  }
}

function transformComponent(
  node: ComponentNode,
  library: Library,
  errors: ParseError[],
): ElementNode {
  const def = library.resolve(node.name);
  const paramDefs = def ? library.paramMap().get(node.name) ?? [] : [];

  // Map positional args to named props
  const props: Record<string, unknown> = {};
  const children: ElementNode[] = [];

  let positionalIndex = 0;

  for (const arg of node.args) {
    if (arg.key !== null) {
      // Named argument
      props[arg.key] = astToValue(arg.value, library, errors, children);
    } else {
      // Positional argument — map to param def by index
      const paramDef = paramDefs[positionalIndex] as ParamDef | undefined;

      if (paramDef) {
        props[paramDef.name] = astToValue(arg.value, library, errors, children);
      } else {
        // Extra positional arg with no param def — treat as child
        const childElement = transformNode(arg.value, library, errors);
        if (childElement) {
          children.push(childElement);
        }
      }

      positionalIndex++;
    }
  }

  // Validate props against Zod schema if component is known
  if (def) {
    const result = def.props.safeParse(props);
    if (!result.success) {
      for (const issue of result.error.issues) {
        errors.push({
          message: `${node.name}: ${issue.path.join(".")}: ${issue.message}`,
          line: 0,
          column: 0,
        });
      }
    }
  } else {
    errors.push({
      message: `Unknown component: "${node.name}"`,
      line: 0,
      column: 0,
    });
  }

  return {
    kind: "element",
    component: node.name,
    props,
    children,
  };
}

/**
 * Convert an AST node to a plain JS value for use as a prop.
 */
function astToValue(
  node: ASTNode,
  library: Library,
  errors: ParseError[],
  children: ElementNode[],
): unknown {
  switch (node.kind) {
    case "literal":
      return node.value;

    case "array":
      return node.elements.map((el) => {
        // Nested components become ElementNodes
        if (el.kind === "component") {
          return transformComponent(el, library, errors);
        }
        return astToValue(el, library, errors, children);
      });

    case "object": {
      const obj: Record<string, unknown> = {};
      for (const entry of node.entries) {
        obj[entry.key] = astToValue(entry.value, library, errors, children);
      }
      return obj;
    }

    case "component":
      return transformComponent(node, library, errors);

    case "reference":
      // Unresolved reference — return placeholder
      return { __ref: node.name };
  }
}
