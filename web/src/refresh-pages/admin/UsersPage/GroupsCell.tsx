"use client";

import {
  useState,
  useRef,
  useLayoutEffect,
  useCallback,
  useEffect,
} from "react";
import { Hoverable } from "@opal/core";
import { SvgEdit } from "@opal/icons";
import { Button, Tag } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import EditUserModal from "./EditUserModal";
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

  // Re-measure when the container width changes (e.g. window resize).
  // Track width so height-only changes (from the measurement cycle toggling
  // visible tags) don't cause an infinite render loop.
  const lastWidthRef = useRef(0);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;

    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      if (Math.abs(width - lastWidthRef.current) < 1) return;
      lastWidthRef.current = width;
      setVisibleCount(null);
    });
    observer.observe(node);

    return () => observer.disconnect();
  }, [groups]);

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
      <Hoverable.Root group="tags">
        <div
          className={`relative flex justify-between items-center w-full min-w-0 ${
            user.id ? "cursor-pointer" : ""
          }`}
          onClick={user.id ? () => setShowModal(true) : undefined}
        >
          {groups.length === 0 ? (
            <div
              ref={containerRef}
              className="flex items-center gap-1 overflow-hidden flex-nowrap min-w-0 -mr-7"
            >
              <Text as="span" secondaryBody text03>
                —
              </Text>
            </div>
          ) : (
            <SimpleTooltip
              side="bottom"
              align="start"
              tooltip={allGroupsTooltip}
              disabled={!hasOverflow}
              className="bg-background-neutral-01 shadow-sm"
              delayDuration={200}
            >
              <div
                ref={containerRef}
                className="flex items-center gap-1 overflow-hidden flex-nowrap min-w-0 -mr-7"
              >
                {tagsContent}
              </div>
            </SimpleTooltip>
          )}
          {user.id && (
            <Hoverable.Item group="tags" variant="opacity-on-hover">
              <Button
                icon={SvgEdit}
                prominence="tertiary"
                tooltip="Edit"
                tooltipSide="left"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowModal(true);
                }}
              />
            </Hoverable.Item>
          )}
        </div>
      </Hoverable.Root>
      {showModal && user.id != null && (
        <EditUserModal
          user={{ ...user, id: user.id }}
          onClose={() => setShowModal(false)}
          onMutate={onMutate}
        />
      )}
    </>
  );
}
