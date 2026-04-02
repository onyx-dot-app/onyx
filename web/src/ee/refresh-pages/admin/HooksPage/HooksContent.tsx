"use client";

import { useState } from "react";
import { useHookSpecs } from "@/ee/hooks/useHookSpecs";
import { useHooks } from "@/ee/hooks/useHooks";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Button } from "@opal/components";
import { Content } from "@opal/layouts";
import InputSearch from "@/refresh-components/inputs/InputSearch";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { SvgArrowExchange, SvgExternalLink } from "@opal/icons";
import HookFormModal from "@/ee/refresh-pages/admin/HooksPage/HookFormModal";
import ConnectedHookCard from "@/ee/refresh-pages/admin/HooksPage/ConnectedHookCard";
import { getHookPointIcon } from "@/ee/refresh-pages/admin/HooksPage/hookPointIcons";
import type {
  HookPointMeta,
  HookResponse,
} from "@/ee/refresh-pages/admin/HooksPage/interfaces";
import { markdown } from "@opal/utils";

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function HooksContent() {
  const [search, setSearch] = useState("");
  const [connectSpec, setConnectSpec] = useState<HookPointMeta | null>(null);
  const [editHook, setEditHook] = useState<HookResponse | null>(null);

  const { specs, isLoading: specsLoading, error: specsError } = useHookSpecs();
  const {
    hooks,
    isLoading: hooksLoading,
    error: hooksError,
    mutate,
  } = useHooks();

  if (specsLoading || hooksLoading) {
    return <SimpleLoader />;
  }

  if (specsError || hooksError) {
    return (
      <Text text03 secondaryBody>
        Failed to load{specsError ? " hook specifications" : " hooks"}. Please
        refresh the page.
      </Text>
    );
  }

  const hooksByPoint: Record<string, HookResponse[]> = {};
  for (const hook of hooks ?? []) {
    (hooksByPoint[hook.hook_point] ??= []).push(hook);
  }

  const searchLower = search.toLowerCase();

  // Connected hooks sorted alphabetically by hook name
  const connectedHooks = (hooks ?? [])
    .filter(
      (hook) =>
        !searchLower ||
        hook.name.toLowerCase().includes(searchLower) ||
        specs
          ?.find((s) => s.hook_point === hook.hook_point)
          ?.display_name.toLowerCase()
          .includes(searchLower)
    )
    .sort((a, b) => a.name.localeCompare(b.name));

  // Unconnected hook point specs sorted alphabetically
  const unconnectedSpecs = (specs ?? [])
    .filter(
      (spec) =>
        (hooksByPoint[spec.hook_point]?.length ?? 0) === 0 &&
        (!searchLower ||
          spec.display_name.toLowerCase().includes(searchLower) ||
          spec.description.toLowerCase().includes(searchLower))
    )
    .sort((a, b) => a.display_name.localeCompare(b.display_name));

  function handleHookSuccess(updated: HookResponse) {
    mutate((prev) => {
      if (!prev) return [updated];
      const idx = prev.findIndex((h) => h.id === updated.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = updated;
        return next;
      }
      return [...prev, updated];
    });
  }

  function handleHookDeleted(id: number) {
    mutate((prev) => prev?.filter((h) => h.id !== id));
  }

  const connectSpec_ =
    connectSpec ??
    (editHook
      ? specs?.find((s) => s.hook_point === editHook.hook_point)
      : undefined);

  return (
    <>
      <div className="flex flex-col gap-6">
        <InputSearch
          placeholder="Search hooks..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <div className="flex flex-col gap-2">
          {connectedHooks.length === 0 && unconnectedSpecs.length === 0 ? (
            <Text text03 secondaryBody>
              {search
                ? "No hooks match your search."
                : "No hook points are available."}
            </Text>
          ) : (
            <>
              {connectedHooks.map((hook) => {
                const spec = specs?.find(
                  (s) => s.hook_point === hook.hook_point
                );
                return (
                  <ConnectedHookCard
                    key={hook.id}
                    hook={hook}
                    spec={spec}
                    onEdit={() => setEditHook(hook)}
                    onDeleted={() => handleHookDeleted(hook.id)}
                    onToggled={handleHookSuccess}
                  />
                );
              })}
              {unconnectedSpecs.map((spec) => {
                const UnconnectedIcon = getHookPointIcon(spec.hook_point);
                return (
                  <Card
                    key={spec.hook_point}
                    variant="secondary"
                    padding={0.5}
                    gap={0}
                    className="hover:border-border-02"
                  >
                    <div className="w-full flex flex-row">
                      <div className="flex-1 p-2">
                        <Content
                          sizePreset="main-ui"
                          variant="section"
                          icon={UnconnectedIcon}
                          title={spec.display_name}
                          description={spec.description}
                        />

                        {spec.docs_url && (
                          <a
                            href={spec.docs_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="pl-6 flex items-center gap-1"
                          >
                            <span className="underline font-secondary-body text-text-03">
                              Documentation
                            </span>
                            <SvgExternalLink size={12} className="shrink-0" />
                          </a>
                        )}
                      </div>

                      <Button
                        prominence="tertiary"
                        rightIcon={SvgArrowExchange}
                        onClick={() => setConnectSpec(spec)}
                      >
                        Connect
                      </Button>
                    </div>
                  </Card>
                );
              })}
            </>
          )}
        </div>
      </div>

      {/* Create modal */}
      <HookFormModal
        key={connectSpec?.hook_point ?? "create"}
        open={!!connectSpec}
        onOpenChange={(open) => {
          if (!open) setConnectSpec(null);
        }}
        spec={connectSpec ?? undefined}
        onSuccess={handleHookSuccess}
      />

      {/* Edit modal */}
      <HookFormModal
        key={editHook?.id ?? "edit"}
        open={!!editHook}
        onOpenChange={(open) => {
          if (!open) setEditHook(null);
        }}
        hook={editHook ?? undefined}
        spec={connectSpec_ ?? undefined}
        onSuccess={handleHookSuccess}
      />
    </>
  );
}
