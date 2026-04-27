"use client";

import { Content } from "@opal/layouts";
import { SvgSearchMenu } from "@opal/icons";

export default function DbgPage() {
  return (
    <div className="grid gap-12 p-8">
      <h1 className="font-heading-h1 text-text-05">Content Debug</h1>

      {/* ContentXl — heading variant */}
      <table className="border-collapse table-fixed w-full">
        <thead>
          <tr className="border-b border-border-02">
            <th
              className="text-left font-heading-h3 text-text-05 pb-2"
              colSpan={2}
            >
              ContentXl (variant: heading)
            </th>
          </tr>
          <tr className="border-b border-border-01">
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3 border-r border-border-01">
              headline
            </th>
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3">
              section
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="py-3 px-3 align-top border-r border-border-01">
              <Content
                sizePreset="headline"
                variant="heading"
                icon={SvgSearchMenu}
                title="Headline Heading"
                description="Description text for headline heading."
              />
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="section"
                variant="heading"
                icon={SvgSearchMenu}
                title="Section Heading"
                description="Description text for section heading."
              />
            </td>
          </tr>
        </tbody>
      </table>

      {/* ContentLg — section variant */}
      <table className="border-collapse table-fixed w-full">
        <thead>
          <tr className="border-b border-border-02">
            <th
              className="text-left font-heading-h3 text-text-05 pb-2"
              colSpan={2}
            >
              ContentLg (variant: section)
            </th>
          </tr>
          <tr className="border-b border-border-01">
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3 border-r border-border-01">
              headline
            </th>
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3">
              section
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="py-3 px-3 align-top border-r border-border-01">
              <Content
                sizePreset="headline"
                variant="section"
                icon={SvgSearchMenu}
                title="Headline Section"
                description="Description text for headline section."
              />
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="section"
                variant="section"
                icon={SvgSearchMenu}
                title="Section Section"
                description="Description text for section section."
              />
            </td>
          </tr>
        </tbody>
      </table>

      {/* ContentMd — section variant */}
      <table className="border-collapse table-fixed w-full">
        <thead>
          <tr className="border-b border-border-02">
            <th
              className="text-left font-heading-h3 text-text-05 pb-2"
              colSpan={3}
            >
              ContentMd (variant: section)
            </th>
          </tr>
          <tr className="border-b border-border-01">
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3 border-r border-border-01">
              main-content
            </th>
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3 border-r border-border-01">
              main-ui
            </th>
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3">
              secondary
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="py-3 px-3 align-top border-r border-border-01">
              <Content
                sizePreset="main-content"
                variant="section"
                icon={SvgSearchMenu}
                title="Main Content"
                description="Description text for main-content."
              />
            </td>
            <td className="py-3 px-3 align-top border-r border-border-01">
              <Content
                sizePreset="main-ui"
                variant="section"
                icon={SvgSearchMenu}
                title="Main UI"
                description="Description text for main-ui."
              />
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="secondary"
                variant="section"
                icon={SvgSearchMenu}
                title="Secondary"
                description="Description text for secondary."
              />
            </td>
          </tr>
        </tbody>
      </table>

      {/* ContentSm — body variant */}
      <table className="border-collapse table-fixed w-full">
        <thead>
          <tr className="border-b border-border-02">
            <th
              className="text-left font-heading-h3 text-text-05 pb-2"
              colSpan={4}
            >
              ContentSm (variant: body)
            </th>
          </tr>
          <tr className="border-b border-border-01">
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3 w-1/4 border-r border-border-01" />
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3 w-1/4 border-r border-border-01">
              main-content
            </th>
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3 w-1/4 border-r border-border-01">
              main-ui
            </th>
            <th className="text-left font-secondary-mono-label text-text-02 py-2 px-3 w-1/4 ">
              secondary
            </th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-border-01">
            <td className="py-3 px-3 align-top font-secondary-mono-label text-text-02 border-r border-border-01">
              inline
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="main-content"
                variant="body"
                icon={SvgSearchMenu}
                title="Main Content"
              />
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="main-ui"
                variant="body"
                icon={SvgSearchMenu}
                title="Main UI"
              />
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="secondary"
                variant="body"
                icon={SvgSearchMenu}
                title="Secondary"
              />
            </td>
          </tr>
          <tr className="border-b border-border-01">
            <td className="py-3 px-3 align-top font-secondary-mono-label text-text-02 border-r border-border-01">
              vertical
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="main-content"
                variant="body"
                icon={SvgSearchMenu}
                title="Main Content"
                orientation="vertical"
              />
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="main-ui"
                variant="body"
                icon={SvgSearchMenu}
                title="Main UI"
                orientation="vertical"
              />
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="secondary"
                variant="body"
                icon={SvgSearchMenu}
                title="Secondary"
                orientation="vertical"
              />
            </td>
          </tr>
          <tr>
            <td className="py-3 px-3 align-top font-secondary-mono-label text-text-02 border-r border-border-01">
              reverse
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="main-content"
                variant="body"
                icon={SvgSearchMenu}
                title="Main Content"
                orientation="reverse"
              />
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="main-ui"
                variant="body"
                icon={SvgSearchMenu}
                title="Main UI"
                orientation="reverse"
              />
            </td>
            <td className="py-3 px-3 align-top">
              <Content
                sizePreset="secondary"
                variant="body"
                icon={SvgSearchMenu}
                title="Secondary"
                orientation="reverse"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
