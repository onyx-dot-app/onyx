import { defineRule, type ESTree } from "@oxlint/plugins";

import {
  callPath,
  globalPath,
  isFunction,
  isPromise,
} from "../shared/test-syntax.ts";
import { callbackTimer, timerPromises } from "../shared/test-timers.ts";

function isSyntaxNode(value: unknown): value is ESTree.Node {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    typeof value.type === "string" &&
    "parent" in value
  );
}

function someSyntax(
  node: unknown,
  matches: (node: ESTree.Node) => boolean
): boolean {
  if (Array.isArray(node))
    return node.some((child) => someSyntax(child, matches));
  if (!isSyntaxNode(node)) return false;
  const syntax = node;
  if (matches(syntax)) return true;
  if (isFunction(syntax)) return false;
  return Object.entries(syntax).some(
    ([key, child]) => key !== "parent" && someSyntax(child, matches)
  );
}

type Loop =
  | ESTree.DoWhileStatement
  | ESTree.ForStatement
  | ESTree.WhileStatement;

function counterBound(loop: Loop): boolean {
  const test = loop.test;
  if (
    test?.type !== "BinaryExpression" ||
    !["<", "<=", ">", ">="].includes(test.operator)
  ) {
    return false;
  }
  const update = loop.type === "ForStatement" ? loop.update : undefined;
  return [
    [test.left, test.right],
    [test.right, test.left],
  ].some(([counter, bound]) => {
    if (
      counter?.type !== "Identifier" ||
      (bound?.type !== "Identifier" &&
        !(bound?.type === "Literal" && typeof bound.value === "number"))
    ) {
      return false;
    }
    return someSyntax([loop.body, update], (node) => {
      if (node.type === "UpdateExpression") {
        return (
          node.argument.type === "Identifier" &&
          node.argument.name === counter.name
        );
      }
      return (
        node.type === "AssignmentExpression" &&
        (node.operator === "+=" || node.operator === "-=") &&
        node.left.type === "Identifier" &&
        node.left.name === counter.name
      );
    });
  });
}

export const noPollingLoopInTestsRule = defineRule({
  meta: {
    type: "problem",
    docs: { description: "Disallow polling on timer or microtask ticks." },
    messages: {
      poll: "Await the event that signals completion, or use a retrying assertion for observable state.",
    },
  },
  create(context) {
    const timers = timerPromises();
    const check = (loop: Loop) => {
      const predicate =
        (loop.test &&
          !(loop.test.type === "Literal" && loop.test.value === true) &&
          !counterBound(loop)) ||
        someSyntax(
          loop.body,
          (node) =>
            node.type === "IfStatement" &&
            someSyntax(
              [node.consequent, node.alternate],
              (branch) =>
                branch.type === "BreakStatement" ||
                branch.type === "ReturnStatement" ||
                branch.type === "ThrowStatement"
            )
        );
      if (!predicate) return;

      const ticks = someSyntax(loop.body, (node) => {
        if (
          node.type === "AwaitExpression" &&
          node.argument.type === "CallExpression"
        ) {
          const { callee } = node.argument;
          return (
            globalPath(callee) === "Promise.resolve" ||
            callPath(callee).at(-1) === "waitForTimeout" ||
            timers.isTimer(callee)
          );
        }
        if (!isPromise(node)) return false;
        const executor = node.arguments[0];
        return Boolean(
          callbackTimer(executor) ||
          (isFunction(executor) &&
            someSyntax(
              executor.body,
              (child) =>
                child.type === "CallExpression" &&
                Boolean(callbackTimer(child.callee))
            ))
        );
      });
      if (ticks) context.report({ node: loop, messageId: "poll" });
    };

    return {
      ImportDeclaration: timers.ImportDeclaration,
      ForStatement: check,
      WhileStatement: check,
      DoWhileStatement: check,
    };
  },
});
