"use client";

import { Button, Card, Divider, Modal, Text } from "@opal/components";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { SvgPlug, SvgPlus, SvgSettings } from "@opal/icons";
import {
  BuiltInExternalAppDescriptor,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";

interface AddAppCatalogModalProps {
  onClose: () => void;
  /** Built-in providers not yet configured (one instance per provider). */
  descriptors: BuiltInExternalAppDescriptor[];
  onPickProvider: (descriptor: BuiltInExternalAppDescriptor) => void;
  onPickCustom: () => void;
}

/** Catalog of everything an admin can grant to Craft: the remaining built-in
 * providers, a custom app, and a pointer to MCP servers (managed in Actions). */
export default function AddAppCatalogModal({
  onClose,
  descriptors,
  onPickProvider,
  onPickCustom,
}: AddAppCatalogModalProps) {
  return (
    <Modal open onOpenChange={(open) => !open && onClose()}>
      <Modal.Content width="lg" height="fit">
        <Modal.Header
          title="Add an app"
          description="Make an integration available to your whole organization. Built-in providers come with actions that teach the Craft agent how to use them; already-configured providers are not listed."
        />
        <Modal.Body>
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {descriptors.map((descriptor) => (
                <CatalogCard
                  key={descriptor.app_type}
                  icon={getAppTypeLogo(descriptor.app_type)}
                  title={descriptor.name}
                  actionLabel="Add"
                  onClick={() => onPickProvider(descriptor)}
                />
              ))}
              <CatalogCard
                icon={SvgPlug}
                title="Custom app"
                description="Credentials and network access for your own integration."
                actionLabel="Create"
                onClick={onPickCustom}
              />
            </div>
            <Divider />
            <div className="flex items-center justify-between gap-2">
              <Text font="secondary-body" color="text-03">
                Need an MCP server instead? Connect it in Actions, then enable
                it for Craft here.
              </Text>
              <Button
                prominence="tertiary"
                href={ADMIN_ROUTES.MCP_ACTIONS.path}
                icon={SvgSettings}
              >
                Open Actions
              </Button>
            </div>
          </div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

interface CatalogCardProps {
  icon: IconFunctionComponent;
  title: string | RichStr;
  description?: string | RichStr;
  /** Plain string — Button children don't accept RichStr. */
  actionLabel: string;
  onClick: () => void;
}

function CatalogCard({
  icon: Icon,
  title,
  description,
  actionLabel,
  onClick,
}: CatalogCardProps) {
  return (
    <Card background="light" border="solid" rounding="lg">
      {/* h-full centers the row inside grid-stretched cards of uneven height. */}
      <div className="h-full flex items-center gap-3 w-full">
        <Icon className="w-8 h-8 shrink-0" />
        <div className="flex-1 flex flex-col gap-0.5">
          <Text font="main-ui-action">{title}</Text>
          {description && (
            <Text font="secondary-body" color="text-03">
              {description}
            </Text>
          )}
        </div>
        <Button icon={SvgPlus} onClick={onClick}>
          {actionLabel}
        </Button>
      </div>
    </Card>
  );
}
