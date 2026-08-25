"use client";

import { useMemo, useState } from "react";
import { Button, LineItemButton, Text } from "@opal/components";
import type { RichStr } from "@opal/types";
import {
  SvgChevronRight,
  SvgFileText,
  SvgFolder,
  SvgFolderOpen,
  SvgTrash,
} from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { cn } from "@opal/utils";
import { formatBytes } from "@/lib/utils";
import type { SkillBundleFile } from "@/lib/skills/types";

interface SkillFileTreeNode {
  name: string;
  path: string;
  size: number | null;
  children: SkillFileTreeNode[];
}

interface SkillFileTreeNodesProps {
  nodes: SkillFileTreeNode[];
  depth: number;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  onRemove?: (path: string) => void;
  removingPath?: string | null;
  removeDisabled: boolean;
}

function SkillFileTreeNodes({
  nodes,
  depth,
  expandedPaths,
  onToggle,
  onRemove,
  removingPath,
  removeDisabled,
}: SkillFileTreeNodesProps) {
  return nodes.map((node) => {
    const isDirectory = node.size === null;
    const isExpanded = expandedPaths.has(node.path);
    const FileIcon = isDirectory
      ? isExpanded
        ? SvgFolderOpen
        : SvgFolder
      : SvgFileText;

    const rightChildren = isDirectory ? (
      <SvgChevronRight
        size={14}
        className={cn(
          "stroke-text-03 transition-transform",
          isExpanded && "rotate-90"
        )}
      />
    ) : (
      <div className="flex items-center gap-1">
        <Text font="secondary-body" color="text-02">
          {formatBytes(node.size!, 1)}
        </Text>
        {onRemove && (
          <Button
            type="button"
            icon={SvgTrash}
            size="sm"
            prominence="tertiary"
            aria-label={`Remove ${node.name}`}
            tooltip={`Remove ${node.name}`}
            disabled={removeDisabled || removingPath !== null}
            onClick={() => onRemove(node.path)}
          />
        )}
      </div>
    );

    return (
      <div key={node.path}>
        <div style={{ paddingLeft: `${depth * 20}px` }}>
          {isDirectory ? (
            <LineItemButton
              sizePreset="main-ui"
              rounding="sm"
              icon={FileIcon}
              onClick={() => onToggle(node.path)}
              rightChildren={rightChildren}
              title={node.name}
            />
          ) : (
            // A file row does nothing when pressed. Only the directory rows
            // toggle, so only they are buttons — the file row is a label with
            // its own controls beside it. The padding matches what
            // LineItemButton applies, so the two line up.
            <div className="w-full p-1.5">
              <ContentAction
                sizePreset="main-ui"
                padding={0.5}
                icon={FileIcon}
                rightChildren={rightChildren}
                title={node.name}
              />
            </div>
          )}
        </div>
        {isDirectory && isExpanded && (
          <SkillFileTreeNodes
            nodes={node.children}
            depth={depth + 1}
            expandedPaths={expandedPaths}
            onToggle={onToggle}
            onRemove={onRemove}
            removingPath={removingPath}
            removeDisabled={removeDisabled}
          />
        )}
      </div>
    );
  });
}

interface SkillFileTreeProps {
  files: readonly SkillBundleFile[];
  emptyMessage?: string | RichStr;
  onRemove?: (path: string) => void;
  removingPath?: string | null;
  removeDisabled?: boolean;
}

export default function SkillFileTree({
  files,
  emptyMessage = "No supporting files yet.",
  onRemove,
  removingPath = null,
  removeDisabled = false,
}: SkillFileTreeProps) {
  const nodes = useMemo(() => {
    const root: SkillFileTreeNode = {
      name: "",
      path: "",
      size: null,
      children: [],
    };

    for (const file of files) {
      const parts = file.path.split("/");
      let parent = root;
      for (let index = 0; index < parts.length; index += 1) {
        const part = parts[index];
        if (part === undefined) continue;
        const path = parts.slice(0, index + 1).join("/");
        let node = parent.children.find((child) => child.name === part);
        if (!node) {
          node = {
            name: part,
            path,
            size: index === parts.length - 1 ? file.size : null,
            children: [],
          };
          parent.children.push(node);
        }
        parent = node;
      }
    }

    function sortNodes(treeNodes: SkillFileTreeNode[]): SkillFileTreeNode[] {
      return treeNodes
        .map((node) => ({ ...node, children: sortNodes(node.children) }))
        .sort((left, right) => {
          const leftIsDirectory = left.size === null;
          const rightIsDirectory = right.size === null;
          if (leftIsDirectory !== rightIsDirectory) {
            return leftIsDirectory ? -1 : 1;
          }
          return left.name.localeCompare(right.name);
        });
    }

    return sortNodes(root.children);
  }, [files]);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());

  function toggle(path: string) {
    setExpandedPaths((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  if (files.length === 0) {
    return (
      <div className="flex min-h-24 items-center justify-center p-3">
        <Text font="secondary-body" color="text-03">
          {emptyMessage}
        </Text>
      </div>
    );
  }

  return (
    <div className="max-h-80 overflow-y-auto p-1">
      <SkillFileTreeNodes
        nodes={nodes}
        depth={0}
        expandedPaths={expandedPaths}
        onToggle={toggle}
        onRemove={onRemove}
        removingPath={removingPath}
        removeDisabled={removeDisabled}
      />
    </div>
  );
}
