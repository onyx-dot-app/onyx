import type { ASTNode, Statement, ParseError } from "../types";

/**
 * Resolve variable references in the AST.
 *
 * Each statement defines `name = expression`. Later expressions can reference
 * earlier variable names. This pass replaces ReferenceNodes with the actual
 * subtree they point to, detecting cycles.
 */
export function resolveReferences(statements: Statement[]): {
  resolved: Map<string, ASTNode>;
  root: ASTNode | null;
  errors: ParseError[];
} {
  const definitions = new Map<string, ASTNode>();
  const resolved = new Map<string, ASTNode>();
  const errors: ParseError[] = [];

  // Build definition map
  for (const stmt of statements) {
    definitions.set(stmt.name, stmt.value);
  }

  // Resolve each statement
  for (const stmt of statements) {
    const resolving = new Set<string>();
    const result = resolveNode(
      stmt.value,
      definitions,
      resolved,
      resolving,
      errors,
    );
    resolved.set(stmt.name, result);
  }

  // Root is the last statement or the one named "root"
  let root: ASTNode | null = null;
  if (resolved.has("root")) {
    root = resolved.get("root")!;
  } else if (statements.length > 0) {
    const lastStmt = statements[statements.length - 1]!;
    root = resolved.get(lastStmt.name) ?? null;
  }

  return { resolved, root, errors };
}

function resolveNode(
  node: ASTNode,
  definitions: Map<string, ASTNode>,
  resolved: Map<string, ASTNode>,
  resolving: Set<string>,
  errors: ParseError[],
): ASTNode {
  switch (node.kind) {
    case "reference": {
      const { name } = node;

      // Already resolved
      if (resolved.has(name)) {
        return resolved.get(name)!;
      }

      // Cycle detection
      if (resolving.has(name)) {
        errors.push({
          message: `Circular reference detected: "${name}"`,
          line: 0,
          column: 0,
        });
        return { kind: "literal", value: null };
      }

      // Unknown reference — leave as-is (may be defined later in streaming)
      const definition = definitions.get(name);
      if (!definition) {
        return node; // keep as unresolved reference
      }

      resolving.add(name);
      const result = resolveNode(
        definition,
        definitions,
        resolved,
        resolving,
        errors,
      );
      resolving.delete(name);
      resolved.set(name, result);
      return result;
    }

    case "component":
      return {
        ...node,
        args: node.args.map((arg) => ({
          ...arg,
          value: resolveNode(
            arg.value,
            definitions,
            resolved,
            resolving,
            errors,
          ),
        })),
      };

    case "array":
      return {
        ...node,
        elements: node.elements.map((el) =>
          resolveNode(el, definitions, resolved, resolving, errors),
        ),
      };

    case "object":
      return {
        ...node,
        entries: node.entries.map((entry) => ({
          ...entry,
          value: resolveNode(
            entry.value,
            definitions,
            resolved,
            resolving,
            errors,
          ),
        })),
      };

    case "literal":
      return node;
  }
}
