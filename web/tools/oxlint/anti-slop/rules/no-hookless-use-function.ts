import { defineRule, type ESTree } from "@oxlint/plugins";

const HOOK_NAME = /^use[A-Z]/u;
// Bare `use` is React 19's `use(promise | context)`, which is a hook call too.
const HOOK_CALLEE = /^use(?:[A-Z]|$)/u;

type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;

function isFunctionNode(node: ESTree.Node): node is FunctionNode {
  return (
    node.type === "FunctionDeclaration" ||
    node.type === "FunctionExpression" ||
    node.type === "ArrowFunctionExpression"
  );
}

function isHookCallee(callee: ESTree.Node): boolean {
  if (callee.type === "Identifier") return HOOK_CALLEE.test(callee.name);
  if (callee.type === "MemberExpression" && !callee.computed) {
    return (
      callee.property.type === "Identifier" &&
      HOOK_CALLEE.test(callee.property.name)
    );
  }
  return false;
}

function isAstNode(value: object): value is ESTree.Node {
  return "type" in value && typeof value.type === "string";
}

// A hook call inside a nested callback runs when the callback runs, not during
// render, so it does not make the outer function a hook.
function callsHook(value: unknown, root: FunctionNode): boolean {
  if (typeof value !== "object" || value === null) return false;
  if (Array.isArray(value))
    return value.some((child) => callsHook(child, root));
  if (!isAstNode(value)) return false;
  if (value !== root && isFunctionNode(value)) return false;
  if (value.type === "CallExpression" && isHookCallee(value.callee))
    return true;
  for (const [key, child] of Object.entries(value)) {
    if (key === "parent") continue;
    if (callsHook(child, root)) return true;
  }
  return false;
}

/** Ban use* functions that call no hooks; the React Compiler skips them. */
export const noHooklessUseFunctionRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow use* functions that call no hooks; the React Compiler only compiles functions that do.",
    },
    messages: {
      hookless:
        '"{{name}}" calls no hooks, so the React Compiler skips it and its result is rebuilt on every render. Rename it to a plain function, or read the hook it depends on inside it.',
    },
  },
  createOnce(context) {
    const check = (name: string, fn: FunctionNode, reportNode: ESTree.Node) => {
      if (!HOOK_NAME.test(name) || callsHook(fn.body, fn)) return;
      context.report({
        node: reportNode,
        messageId: "hookless",
        data: { name },
      });
    };
    return {
      FunctionDeclaration(node) {
        if (node.id) check(node.id.name, node, node.id);
      },
      VariableDeclarator(node) {
        if (node.id.type !== "Identifier" || node.init == null) return;
        if (
          node.init.type !== "ArrowFunctionExpression" &&
          node.init.type !== "FunctionExpression"
        )
          return;
        check(node.id.name, node.init, node.id);
      },
    };
  },
});
