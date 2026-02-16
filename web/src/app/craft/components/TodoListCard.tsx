"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import { SvgChevronDown, SvgCheckCircle } from "@opal/icons";
import {
  TodoListState,
  TodoItem,
  TodoStatus,
} from "@/app/craft/types/displayTypes";

interface TodoListCardProps {
  todoList: TodoListState;
  /** Whether this card should be open by default */
  defaultOpen?: boolean;
}

/**
 * Get status icon for a todo item
 */
function getStatusIcon(status: TodoStatus) {
  switch (status) {
    case "completed":
      return (
        <SvgCheckCircle className="size-4 stroke-status-success-05 mt-0.5 shrink-0" />
      );
    case "in_progress":
      // Gray circle with inset filled circle to indicate work in progress
      return (
        <div className="size-4 rounded-full border-2 border-text-03 mt-0.5 shrink-0 flex items-center justify-center">
          <div className="size-2 bg-text-03 rounded-full" />
        </div>
      );
    case "pending":
    default:
      return (
        <div className="size-4 rounded-full border-2 border-text-03 mt-0.5 shrink-0" />
      );
  }
}

/**
 * Single todo item row
 */
function TodoItemRow({ todo }: { todo: TodoItem }) {
  return (
    <div className="flex items-start gap-2 py-1">
      {/* Status indicator */}
      {getStatusIcon(todo.status)}

      {/* Task text - show activeForm when in_progress, otherwise content */}
      <span
        className={cn(
          "text-sm",
          todo.status === "completed"
            ? "text-text-03 line-through"
            : "text-text-04"
        )}
      >
        {todo.status === "in_progress" ? todo.activeForm : todo.content}
      </span>
    </div>
  );
}

/**
 * TodoListCard - Collapsible card showing a list of todo items
 *
 * Features:
 * - Shows progress count (e.g., "3/5 completed")
 * - Spinner in header when any item is in_progress
 * - Auto-collapses when new todo list appears (controlled by parent)
 * - Items show different states: pending (empty circle), in_progress (spinner), completed (checkmark)
 */
export default function TodoListCard({
  todoList,
  defaultOpen = true,
}: TodoListCardProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  // Update isOpen when defaultOpen changes (for auto-collapse behavior)
  useEffect(() => {
    setIsOpen(defaultOpen);
  }, [defaultOpen]);

  // Calculate progress stats
  const total = todoList.todos.length;
  const completed = todoList.todos.filter(
    (t) => t.status === "completed"
  ).length;

  // Determine background color based on state
  // Only two states: gray (default) and green (completed)
  const allCompleted = completed === total && total > 0;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div
        className={cn(
          "w-full border-[0.5px] rounded-lg overflow-hidden",
          allCompleted
            ? "bg-status-success-01 border-status-success-01"
            : "bg-background-neutral-01 border-border-01"
        )}
      >
        <CollapsibleTrigger asChild>
          <button
            className={cn(
              "w-full flex items-center justify-between px-3 py-2",
              "hover:bg-background-tint-02 transition-colors text-left"
            )}
          >
            <div className="flex items-center gap-2 min-w-0 flex-1">
              {/* Status indicator in header - no spinner, only static icons */}
              {allCompleted ? (
                <SvgCheckCircle className="size-4 stroke-status-success-05 shrink-0" />
              ) : (
                <div className="size-4 rounded border-2 border-text-03 shrink-0 flex items-center justify-center">
                  <div className="size-2 bg-text-03 rounded-sm" />
                </div>
              )}

              {/* Title */}
              <span className="text-sm font-medium text-text-04">Tasks</span>

              {/* Progress count */}
              <span className="text-xs text-text-03">
                {completed}/{total} completed
              </span>
            </div>

            {/* Expand arrow */}
            <SvgChevronDown
              className={cn(
                "size-4 stroke-text-03 transition-transform duration-150 shrink-0",
                !isOpen && "rotate-[-90deg]"
              )}
            />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="px-3 pb-3 pt-0 space-y-0.5">
            {todoList.todos.map((todo, index) => (
              <TodoItemRow key={`${todoList.id}-${index}`} todo={todo} />
            ))}
            {todoList.todos.length === 0 && (
              <span className="text-sm text-text-03 italic">No tasks</span>
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
