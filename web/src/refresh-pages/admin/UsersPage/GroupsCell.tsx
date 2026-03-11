"use client";

import { useState, useRef, useLayoutEffect, useCallback } from "react";
import { SvgEdit } from "@opal/icons";
import { Tag } from "@opal/components";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import EditGroupsModal from "./EditGroupsModal";
import type { UserRow, UserGroupInfo } from "./interfaces";

interface GroupsCellProps {
  groups: UserGroupInfo[];
  user: UserRow;
  onMutate: () => void;
}

/**
 * Measures how many Tag pills fit in the container, accounting for a "+N"
 * overflow counter when not all tags are visible. Uses a two-phase render:
 * first renders all tags (clipped by overflow:hidden) for measurement, then
 * re-renders with only the visible subset + "+N".
 *
 * Hovering the cell shows a tooltip with ALL groups. Clicking opens the
 * edit groups modal.
 */
export default function GroupsCell({
  groups,
  user,
  onMutate,
}: GroupsCellProps) {
  const [showModal, setShowModal] = useState(false);
  const [visibleCount, setVisibleCount] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const computeVisibleCount = useCallback(() => {
    const container = containerRef.current;
    if (!container || groups.length <= 1) {
      setVisibleCount(groups.length);
      return;
    }

    const tags = container.querySelectorAll<HTMLElement>("[data-group-tag]");
    if (tags.length === 0) return;

    const containerWidth = container.clientWidth;
    const gap = 4; // gap-1
    const counterWidth = 32; // "+N" Tag approximate width

    let used = 0;
    let count = 0;

    for (let i = 0; i < tags.length; i++) {
      const tagWidth = tags[i]!.offsetWidth;
      const gapBefore = count > 0 ? gap : 0;
      const hasMore = i < tags.length - 1;
      const reserve = hasMore ? gap + counterWidth : 0;

      if (used + gapBefore + tagWidth + reserve <= containerWidth) {
        used += gapBefore + tagWidth;
        count++;
      } else {
        break;
      }
    }

    setVisibleCount(Math.max(1, count));
  }, [groups]);

  // Reset to measurement phase when groups change
  useLayoutEffect(() => {
    setVisibleCount(null);
  }, [groups]);

  // Measure after the "show all" render
  useLayoutEffect(() => {
    if (visibleCount !== null) return;
    computeVisibleCount();
  }, [visibleCount, computeVisibleCount]);

  // Re-measure on container resize
  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      setVisibleCount(null);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const isMeasuring = visibleCount === null;
  const effectiveVisible = visibleCount ?? groups.length;
  const overflowCount = groups.length - effectiveVisible;
  const hasOverflow = !isMeasuring && overflowCount > 0;

  const allGroupsTooltip = (
    <div className="flex flex-wrap gap-1 max-w-[14rem]">
      {groups.map((g) => (
        <div key={g.id} className="max-w-[10rem]">
          <Tag title={g.name} size="md" />
        </div>
      ))}
    </div>
  );

  const tagsContent = (
    <>
      {(isMeasuring ? groups : groups.slice(0, effectiveVisible)).map((g) => (
        <div key={g.id} data-group-tag className="flex-shrink-0">
          <Tag title={g.name} size="md" />
        </div>
      ))}
      {hasOverflow && (
        <div className="flex-shrink-0">
          <Tag title={`+${overflowCount}`} size="md" />
        </div>
      )}
    </>
  );

  return (
    <>
      <div
        className={`group/groups relative flex items-center w-full min-w-0 ${
          user.id ? "cursor-pointer" : ""
        }`}
        onClick={user.id ? () => setShowModal(true) : undefined}
      >
        {groups.length === 0 ? (
          <div
            ref={containerRef}
            className="flex items-center gap-1 overflow-hidden flex-nowrap min-w-0 pr-7"
          >
            <Text as="span" secondaryBody text03>
              —
            </Text>
          </div>
        ) : hasOverflow ? (
          <SimpleTooltip
            side="bottom"
            align="start"
            tooltip={allGroupsTooltip}
            className="bg-background-neutral-01 border border-border-01 shadow-sm"
            delayDuration={200}
          >
            <div
              ref={containerRef}
              className="flex items-center gap-1 overflow-hidden flex-nowrap min-w-0 pr-7"
            >
              {tagsContent}
            </div>
          </SimpleTooltip>
        ) : (
          <div
            ref={containerRef}
            className="flex items-center gap-1 overflow-hidden flex-nowrap min-w-0 pr-7"
          >
            {tagsContent}
          </div>
        )}
        {user.id && (
          <IconButton
            tertiary
            icon={SvgEdit}
            tooltip="Edit"
            toolTipPosition="left"
            tooltipSize="sm"
            className="absolute right-0 opacity-0 group-hover/groups:opacity-100 transition-opacity"
            onClick={(e) => {
              e.stopPropagation();
              setShowModal(true);
            }}
          />
        )}
      </div>
      {showModal && user.id && (
        <EditGroupsModal
          user={user}
          onClose={() => setShowModal(false)}
          onMutate={onMutate}
        />
      )}
    </>
  );
}
