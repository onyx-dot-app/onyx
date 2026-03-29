"use client";

import React from "react";
import Link from "next/link";
import type { Route } from "next";
import { Button } from "@opal/components";
import { SvgExternalLink, SvgGlobe, SvgUploadCloud } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Card } from "@/refresh-components/cards";
import { Section } from "@/layouts/general-layouts";
import { Disabled } from "@opal/core";
import {
  OnboardingState,
  OnboardingStep,
} from "@/interfaces/onboarding";

interface DataSourceStepProps {
  state: OnboardingState;
  disabled?: boolean;
}

const DATA_SOURCES = [
  {
    title: "Connect SharePoint",
    description:
      "Sync documents, pages, and permissions from your SharePoint sites.",
    icon: SvgGlobe,
    buttonText: "SharePoint",
    buttonHref: "/admin/connectors/sharepoint",
  },
  {
    title: "Upload Files",
    description: "Upload PDF, Word, Excel, and other files directly.",
    icon: SvgUploadCloud,
    buttonText: "Upload",
    buttonHref: "/admin/connectors/file",
  },
];

const DataSourceStepInner = ({ state, disabled }: DataSourceStepProps) => {
  const isActive =
    state.currentStep === OnboardingStep.DataSource ||
    state.currentStep === OnboardingStep.Name;

  if (!isActive) {
    return null;
  }

  return (
    <Disabled disabled={disabled} allowClick>
      <Section gap={0.5}>
        {DATA_SOURCES.map((source) => (
          <Card key={source.title} padding={0.25} variant="secondary">
            <ContentAction
              icon={source.icon}
              title={source.title}
              description={source.description}
              sizePreset="main-ui"
              variant="section"
              paddingVariant="sm"
              rightChildren={
                <Link href={source.buttonHref as Route}>
                  <Button prominence="tertiary" rightIcon={SvgExternalLink}>
                    {source.buttonText}
                  </Button>
                </Link>
              }
            />
          </Card>
        ))}
      </Section>
    </Disabled>
  );
};

const DataSourceStep = React.memo(DataSourceStepInner);
DataSourceStep.displayName = "DataSourceStep";
export default DataSourceStep;
