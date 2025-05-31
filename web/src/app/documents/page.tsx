'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { TiptapEditor } from '../../components/editors/TiptapEditor';
import { TiptapTableEditor } from '../../components/editors/TiptapTableEditor';
import { DocumentLayout } from '@/components/layout/DocumentLayout';
import { useGoogleDoc, useGoogleSheet, convertSectionsToHtml, DocumentBase } from '@/lib/hooks/useGoogleDocs';
import { defaultSidebarFiles } from '@/lib/documents/types';
import { FiExternalLink } from 'react-icons/fi';
import { ThreeDotsLoader } from '@/components/Loading';

export default function DocumentsPage() {
  const searchParams = useSearchParams();
  const docId = searchParams?.get('docId');
  const [content, setContent] = useState('');
  const [documentData, setDocumentData] = useState<DocumentBase | null>(null);
  const [selectedSheet, setSelectedSheet] = useState<string>('');
  
  const fileInfo = defaultSidebarFiles.find(file => file.docId === docId);
  const isSpreadsheet = fileInfo?.fileType === 'spreadsheet';
  
  const { doc, isLoading: docLoading, error: docError } = useGoogleDoc(isSpreadsheet ? null : docId);
  const { sheet, isLoading: sheetLoading, error: sheetError } = useGoogleSheet(isSpreadsheet ? docId : null);
  
  const isLoading = docLoading || sheetLoading;
  const error = docError || sheetError;
  
  // Always set the first sheet as the default when sheet data is loaded
  useEffect(() => {
    if (sheet && Object.keys(sheet).length > 0) {
      const sheetNames = Object.keys(sheet);
      // Always select the first sheet as default when sheet data changes
      // This ensures the first sheet is always the default
      setSelectedSheet(sheetNames[0]);
    }
  }, [sheet]);
  
  // Track previous docId to handle transitions
  const prevDocIdRef = useRef<string | null>(null);
  
  // Reset state when document ID changes
  useEffect(() => {
    if (docId !== prevDocIdRef.current) {
      // Only reset content when docId actually changes, not on first render
      if (prevDocIdRef.current !== null) {
        setContent('');
        setDocumentData(null);
        
        // Only reset selected sheet for non-spreadsheets
        // For spreadsheets, we'll let the sheet data effect handle setting the first sheet
        if (!isSpreadsheet) {
          setSelectedSheet('');
        }
      }
      
      // Update the ref with current docId
      prevDocIdRef.current = docId;
    }
  }, [docId, isSpreadsheet]);

  // Update content whenever doc, sheet, or selectedSheet changes
  useEffect(() => {
    if (doc) {
      // Store the complete document data
      setDocumentData(doc);
      // Convert sections to HTML for display
      const htmlContent = convertSectionsToHtml(doc.sections);
      setContent(htmlContent);
    } else if (sheet && selectedSheet && sheet[selectedSheet]) {
      // Get the data for the selected sheet
      const sheetData = sheet[selectedSheet];
      // Convert the sheet data to HTML table
      const tableHtml = convertSheetDataToTableHtml(sheetData);
      // Update the content state
      setContent(tableHtml);
      // Reset document data since we're viewing a sheet
      setDocumentData(null);
    }
  }, [doc, sheet, selectedSheet]);

  const convertSheetDataToTableHtml = (data: any[][]) => {
    if (!data || data.length === 0) return '';
    
    const tableRows = data.map((row, index) => {
      const cells = row.map(cell => {
        // Check if cell is an object with hyperlink
        if (cell && typeof cell === 'object' && 'hyperlink' in cell) {
          const cellValue = cell.value || '';
          const hyperlink = cell.hyperlink;
          // Use data-href attribute to preserve the link for Tiptap to process
          const cellContent = `<a href="${hyperlink}">${cellValue}</a>`;
          return index === 0 ? `<th>${cellContent}</th>` : `<td>${cellContent}</td>`;
        } else {
          // Regular cell without hyperlink
          return index === 0 ? `<th>${cell || ''}</th>` : `<td>${cell || ''}</td>`;
        }
      }).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
    
    return `<table><tbody>${tableRows}</tbody></table>`;
  };

  return (
    <DocumentLayout
      documentContent={content}
      documentType={isSpreadsheet ? 'spreadsheet' : 'document'}
      documentTitle={fileInfo?.name || (docId ? 'Document' : 'Documents')}
      setContent={setContent}
    >
      <div className="container mx-auto p-6 max-w-6xl">
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <h1 className="text-3xl font-bold text-foreground">
              {fileInfo?.name || (docId ? 'Document' : 'Documents')}
            </h1>
            {fileInfo?.url && (
              <a 
                href={fileInfo.url} 
                target="_blank" 
                rel="noopener noreferrer"
                className="flex items-center gap-2 text-blue-500 hover:text-blue-700 transition-colors"
              >
                <FiExternalLink size={16} />
              </a>
            )}
          </div>
          {isLoading && <div className="my-2"><ThreeDotsLoader /></div>}
          {error && <p className="text-red-600">{error.message || 'Failed to load document'}</p>}
        </div>
        
        {/* Sheet selection tabs for spreadsheets */}
        {sheet && Object.keys(sheet).length > 1 && (
          <div className="mb-6">
            <div className="border-b border-border">
              <nav className="flex space-x-8">
                {Object.keys(sheet).map((sheetName) => (
                  <button
                    key={sheetName}
                    onClick={() => setSelectedSheet(sheetName)}
                    className={`py-2 px-1 border-b-2 font-medium text-sm ${
                      selectedSheet === sheetName
                        ? 'border-primary text-primary'
                        : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
                    }`}
                  >
                    {sheetName}
                  </button>
                ))}
              </nav>
            </div>
          </div>
        )}
        
        {/* Document editor */}
        {docId && !isLoading && (
          <>
            {isSpreadsheet ? (
              <TiptapTableEditor 
                key={`sheet-${docId}-${selectedSheet}`}
                content={content}
                onChange={setContent}
                editable={true}
              />
            ) : (
              <TiptapEditor 
                key={`doc-${docId}`}
                content={content}
                documentData={documentData}
                onChange={setContent}
                editable={true}
              />
            )}
          </>
        )}
        
        {/* Default state when no document selected */}
        {!docId && (
          <div className="text-center py-12">
            <p className="text-muted-foreground">Select a document from the sidebar to start editing</p>
          </div>
        )}
      </div>
    </DocumentLayout>
  );
}
