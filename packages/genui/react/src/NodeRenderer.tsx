import React from "react";
import type { ElementNode } from "@onyx/genui";
import { useLibrary } from "./context";
import { ErrorBoundary } from "./ErrorBoundary";

interface NodeRendererProps {
  node: ElementNode;
}

/**
 * Check if a value is an ElementNode (has kind: "element" and component string).
 */
function isElementNode(value: unknown): value is ElementNode {
  return (
    typeof value === "object" &&
    value !== null &&
    "kind" in value &&
    (value as Record<string, unknown>)["kind"] === "element" &&
    "component" in value
  );
}

/**
 * Recursively resolve prop values — any ElementNode found in props
 * (or nested in arrays) gets rendered to a React element.
 */
function resolvePropsForRender(
  props: Record<string, unknown>,
  library: ReturnType<typeof useLibrary>,
): Record<string, unknown> {
  const resolved: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(props)) {
    resolved[key] = resolveValue(value, library);
  }

  return resolved;
}

function resolveValue(
  value: unknown,
  library: ReturnType<typeof useLibrary>,
): unknown {
  if (isElementNode(value)) {
    return <NodeRenderer node={value} />;
  }

  if (Array.isArray(value)) {
    return value.map((item, i) => {
      if (isElementNode(item)) {
        return <NodeRenderer key={i} node={item} />;
      }
      // Recurse into nested arrays
      if (Array.isArray(item)) {
        return resolveValue(item, library);
      }
      return item;
    });
  }

  return value;
}

/**
 * Recursively renders an ElementNode by looking up the component
 * in the library and passing validated props.
 */
export function NodeRenderer({ node }: NodeRendererProps) {
  const library = useLibrary();

  // Handle unresolved references
  if (node.component === "__Unresolved") {
    return (
      <span style={{ opacity: 0.5, fontStyle: "italic" }}>
        {String(node.props["name"] ?? "...")}
      </span>
    );
  }

  const def = library.resolve(node.component);

  if (!def) {
    // Unknown component — render children or show placeholder
    if (node.children.length > 0) {
      return (
        <>
          {node.children.map((child, i) => (
            <NodeRenderer key={i} node={child} />
          ))}
        </>
      );
    }
    return (
      <span style={{ color: "#9ca3af", fontStyle: "italic" }}>
        [{node.component}]
      </span>
    );
  }

  // Resolve ElementNodes within props into rendered React elements
  const resolvedProps = resolvePropsForRender(node.props, library);

  // Render explicit children from node.children
  const renderedChildren =
    node.children.length > 0
      ? node.children.map((child, i) => <NodeRenderer key={i} node={child} />)
      : undefined;

  const Component = def.component as React.FC<{
    props: Record<string, unknown>;
    children?: React.ReactNode;
  }>;

  return (
    <ErrorBoundary componentName={node.component}>
      <Component props={resolvedProps}>{renderedChildren}</Component>
    </ErrorBoundary>
  );
}
