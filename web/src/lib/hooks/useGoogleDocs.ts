"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

export interface Section {
  link?: string | null;
  text?: string | null;
  image_file_name?: string | null;
}

export interface DocumentBase {
  id: string;
  sections: Section[];
  source: string;
  semantic_identifier: string;
  metadata: Record<string, string | string[]>;
  doc_updated_at: string | null;
  chunk_count: number | null;
  primary_owners: any | null;
  secondary_owners: any | null;
  title: string | null;
  from_ingestion_api: boolean;
  additional_info: any | null;
}

export interface GoogleSheetResponse {
  [sheetName: string]: string[][];
}

/**
 * Hook to fetch Google Doc content by document ID
 */
export function useGoogleDoc(docId: string | null) {
  const { data, error, isLoading } = useSWR<DocumentBase>(
    docId ? `/api/google/docs/${docId}` : null,
    errorHandlingFetcher
  );

  return {
    doc: data,
    isLoading,
    error,
  };
}

/**
 * Hook to fetch Google Sheet content by sheet ID
 */
export function useGoogleSheet(sheetId: string | null) {
  const { data, error, isLoading } = useSWR<GoogleSheetResponse>(
    sheetId ? `/api/google/sheets/${sheetId}` : null,
    errorHandlingFetcher
  );

  return {
    sheet: data,
    isLoading,
    error,
  };
}

/**
 * Convert document sections to HTML content
 */
export function convertSectionsToHtml(sections: Section[] | undefined): string {
  if (!sections) return '';

  return sections
    .map(section => {
      if (section.text) {
        return `<p>${section.text}</p>`;
      } else if (section.link) {
        return `<p><a href="${section.link}" target="_blank" rel="noopener noreferrer">${section.link}</a></p>`;
      } else if (section.image_file_name) {
        return `<img src="${section.image_file_name}" alt="Document image" />`;
      }
      return '';
    })
    .filter(content => content.length > 0)
    .join('');
}

/**
 * Convert sheet sections to table HTML content
 */
export function convertSectionsToTableHtml(sections: Section[] | undefined): string {
  if (!sections) return '';

  return sections
    .map(section => section.text || '')
    .join('\n');
}
