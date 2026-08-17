"use client";

import { Fragment, ReactNode } from "react";
import { useFormContext } from "@/components/context/FormContext";
import { credentialTemplates } from "@/lib/connectors/credentials";
import { Content, SidebarLayouts, useSidebarState } from "@opal/layouts";
import { Divider, SidebarTab } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgX } from "@opal/icons";
import { renderSidebarLogo } from "@/lib/sidebar/utils";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";

// Fixed height of each step row (px). A uniform row height lets the connecting
// rail line up deterministically with every dot regardless of step count.
const STEP_ROW_PX = 36;

type SelectionType = "done" | "current" | "future";

interface SelectionIconProps {
  selected: SelectionType;
}

function SelectionIcon({ selected }: SelectionIconProps) {
  return (
    <div
      className={cn(
        "shrink-0 z-10 rounded-full h-3.5 w-3.5 flex items-center justify-center",
        selected === "future"
          ? "bg-background-tint-04"
          : "bg-action-selection-05"
      )}
    >
      {selected === "current" && (
        <div className="h-1.5 w-1.5 rounded-full bg-background-tint-inverted-00" />
      )}
    </div>
  );
}

interface CreateConnectorSidebarShellProps {
  children?: ReactNode;
}

/**
 * Sidebar shared by the create-connector flows. Use it directly for a flow
 * that has no steps to show; otherwise use the default export.
 *
 * It replaces `AdminSidebar`, so it must offer its own way back to the admin
 * panel. Without one the user is stranded.
 */
export function CreateConnectorSidebarShell({
  children,
}: CreateConnectorSidebarShellProps) {
  const showLogoWhenFolded = useShowLogoWhenFolded();
  const { folded } = useSidebarState();

  return (
    <SidebarLayouts.Root>
      <SidebarLayouts.Header
        renderAppLogo={renderSidebarLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      />

      <SidebarLayouts.Body scrollKey="create-connector">
        {children}
      </SidebarLayouts.Body>

      {/* The way out sits at the bottom, like "Exit Admin Panel" in `AdminSidebar`. */}
      <SidebarLayouts.Footer>
        {!folded && <Divider paddingPerpendicular={2} />}
        <SidebarTab
          icon={SvgX}
          href="/admin/add-connector"
          variant="sidebar-light"
          folded={folded}
        >
          Exit Connector Setup
        </SidebarTab>
      </SidebarLayouts.Footer>
    </SidebarLayouts.Root>
  );
}

export default function CreateConnectorSidebar() {
  const { formStep, setFormStep, connector, allowAdvanced, allowCreate } =
    useFormContext();
  const noCredential = credentialTemplates[connector] == null;

  const settingSteps = [
    ...(!noCredential ? ["Credential"] : []),
    "Connector",
    ...(connector == "file" ? [] : ["Advanced (optional)"]),
  ];

  return (
    <CreateConnectorSidebarShell>
      <div className="relative mx-2 flex flex-col">
        {settingSteps.map((step, index) => {
          // The form numbers steps absolutely (0 = Credential, 1 = Connector,
          // 2 = Advanced) and clamps `formStep` to >= 1 when there's no
          // credential step. Since we omit the Credential row in that case,
          // shift the row index up to recover the form's step numbering.
          const stepValue = index + (noCredential ? 1 : 0);

          const allowed =
            (step == "Connector" && allowCreate) ||
            (step == "Advanced (optional)" && allowAdvanced) ||
            stepValue <= formStep;

          const selected: SelectionType =
            formStep === stepValue
              ? "current"
              : formStep < stepValue
                ? "future"
                : "done";

          return (
            <Fragment key={index}>
              {index !== 0 && (
                <div
                  className={cn(
                    "absolute left-2 w-0.5",
                    stepValue <= formStep
                      ? "bg-action-selection-05"
                      : "bg-background-tint-04"
                  )}
                  style={{
                    top: (index - 1) * STEP_ROW_PX + STEP_ROW_PX / 2,
                    height: STEP_ROW_PX,
                  }}
                />
              )}
              <button
                type="button"
                disabled={!allowed}
                className={cn(
                  "flex items-center",
                  allowed ? "cursor-pointer" : "cursor-not-allowed"
                )}
                style={{ height: STEP_ROW_PX }}
                onClick={() => setFormStep(stepValue)}
              >
                <Content
                  sizePreset="main-ui"
                  variant="body"
                  icon={() => <SelectionIcon selected={selected} />}
                  title={step}
                  color={selected === "future" ? "muted" : "default"}
                />
              </button>
            </Fragment>
          );
        })}
      </div>
    </CreateConnectorSidebarShell>
  );
}
