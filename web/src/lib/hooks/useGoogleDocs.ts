"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

export interface Section {
  link?: string | null;
  text?: string | null;
  image_file_name?: string | null;
}

export interface FormattedSection {
  text: string;
  element_type: string;
  link?: string | null;
  formatting_metadata?: Record<string, any> | null;
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

export interface FormattedDocumentBase {
  id: string;
  sections: FormattedSection[];
  source: string;
  semantic_identifier: string;
  metadata: Record<string, string | string[]>;
  doc_updated_at: string | null;
  title: string | null;
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
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 5000, // Dedupe requests within 5 seconds
    }
  );

  return {
    doc: data,
    isLoading,
    error,
  };
}

/**
 * Hook to fetch Google Doc content with formatting preserved
 */
export function useGoogleDocFormatted(docId: string | null) {
  const { data, error, isLoading } = useSWR<FormattedDocumentBase>(
    docId ? `/api/google/docs/${docId}/formatted` : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 5000, // Dedupe requests within 5 seconds
    }
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
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 5000, // Dedupe requests within 5 seconds
    }
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
 * Convert formatted document sections to HTML content for TipTap editor
 */
export function convertFormattedSectionsToHtml(sections: FormattedSection[] | undefined): string {
  if (!sections) return '';

  return sections
    .map(section => {
      const { text, element_type, formatting_metadata } = section;
      
      switch (element_type) {
        case 'heading1':
          return `<h1>${text}</h1>`;
        case 'heading2':
          return `<h2>${text}</h2>`;
        case 'heading3':
          return `<h3>${text}</h3>`;
        case 'heading4':
          return `<h4>${text}</h4>`;
        case 'heading5':
          return `<h5>${text}</h5>`;
        case 'heading6':
          return `<h6>${text}</h6>`;
        case 'list_item':
          const listType = formatting_metadata?.list_type || 'unordered';
          if (listType === 'ordered') {
            return `<li>${text}</li>`;
          } else {
            return `<li>${text}</li>`;
          }
        case 'table':
          return text;
        case 'paragraph':
        default:
          let formattedText = text;
          if (formatting_metadata?.has_bold) {
            formattedText = `<strong>${formattedText}</strong>`;
          }
          if (formatting_metadata?.has_italic) {
            formattedText = `<em>${formattedText}</em>`;
          }
          if (formatting_metadata?.has_underline) {
            formattedText = `<u>${formattedText}</u>`;
          }
          return `<p>${formattedText}</p>`;
      }
    })
    .filter(content => content.length > 0)
    .join('');
}

/**
 * Convert formatted sections to properly structured HTML with grouped lists
 */
export function convertFormattedSectionsToStructuredHtml(sections: FormattedSection[] | undefined): string {
  if (!sections) return '';

  const htmlParts: string[] = [];
  let currentList: { type: string; items: string[] } | null = null;

  for (const section of sections) {
    const { text, element_type, formatting_metadata } = section;

    if (element_type === 'list_item') {
      const listType = formatting_metadata?.list_type || 'unordered';
      
      if (!currentList || currentList.type !== listType) {
        if (currentList) {
          const listTag = currentList.type === 'ordered' ? 'ol' : 'ul';
          htmlParts.push(`<${listTag}>${currentList.items.join('')}</${listTag}>`);
        }
        currentList = { type: listType, items: [] };
      }
      
      currentList.items.push(`<li>${text}</li>`);
    } else {
      if (currentList) {
        const listTag = currentList.type === 'ordered' ? 'ol' : 'ul';
        htmlParts.push(`<${listTag}>${currentList.items.join('')}</${listTag}>`);
        currentList = null;
      }

      switch (element_type) {
        case 'heading1':
          htmlParts.push(`<h1>${text}</h1>`);
          break;
        case 'heading2':
          htmlParts.push(`<h2>${text}</h2>`);
          break;
        case 'heading3':
          htmlParts.push(`<h3>${text}</h3>`);
          break;
        case 'heading4':
          htmlParts.push(`<h4>${text}</h4>`);
          break;
        case 'heading5':
          htmlParts.push(`<h5>${text}</h5>`);
          break;
        case 'heading6':
          htmlParts.push(`<h6>${text}</h6>`);
          break;
        case 'table':
          htmlParts.push(text);
          break;
        case 'paragraph':
        default:
          let formattedText = text;
          if (formatting_metadata?.has_bold) {
            formattedText = `<strong>${formattedText}</strong>`;
          }
          if (formatting_metadata?.has_italic) {
            formattedText = `<em>${formattedText}</em>`;
          }
          if (formatting_metadata?.has_underline) {
            formattedText = `<u>${formattedText}</u>`;
          }
          htmlParts.push(`<p>${formattedText}</p>`);
          break;
      }
    }
  }

  if (currentList) {
    const listTag = currentList.type === 'ordered' ? 'ol' : 'ul';
    htmlParts.push(`<${listTag}>${currentList.items.join('')}</${listTag}>`);
  }

  return htmlParts.join('');
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
