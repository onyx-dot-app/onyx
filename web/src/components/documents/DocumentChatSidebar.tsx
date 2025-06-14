'use client';

import { PacketType } from '@/app/chat/lib';
import { CodeBlock } from '@/app/chat/message/CodeBlock';
import { MemoizedAnchor, MemoizedParagraph } from '@/app/chat/message/MemoizedTextComponents';
import { extractCodeText, preprocessLaTeX } from '@/app/chat/message/codeUtils';
import { useAssistants } from '@/components/context/AssistantsContext';
import { SendIcon } from '@/components/icons/icons';
import { Button } from '@/components/ui/button';
import { AgentAnswerPiece, DocumentEditorResponse, DocumentInfoPacket, OnyxDocument, ThinkingPiece } from '@/lib/search/interfaces';
import { handleSSEStream } from '@/lib/search/streamingUtils';
import { transformLinkUri } from '@/lib/utils';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FiChevronDown, FiChevronRight, FiMessageSquare, FiPlus } from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import rehypePrism from 'rehype-prism-plus';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import { v4 as uuidv4 } from 'uuid';
import { DocumentSelector, DocumentContent } from './DocumentSelector';
import { FileEntry } from '@/lib/documents/types';

interface CitationInfo {
  citation_num: number;
  document_id: string;
  level?: number | null;
  level_question_num?: number | null;
}

interface DocumentChatSidebarProps {
  initialWidth: number;
  documentIds?: string[]; // Accept document IDs from parent component
  documentContent?: string; // The actual text content of the document
  documentType?: 'document' | 'spreadsheet'; // Type of document being viewed
  documentTitle?: string; // Title of the document
  setContent?: (content: string) => void; // Function to update the document content
  availableFiles?: FileEntry[]; // Available files from the left sidebar
}

export function DocumentChatSidebar({ 
  initialWidth, 
  documentIds = [], 
  documentContent = '',
  documentType = 'document',
  documentTitle = '',
  setContent,
  availableFiles = []
}: DocumentChatSidebarProps) {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState<Array<{id: number, text: string, isUser: boolean, isIntermediateOutput?: boolean, isThinking?: boolean, debugLog?: Array<any>}>>([]);
  const [sessionId, setSessionId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [presentingDocument, setPresentingDocument] = useState<any>(null);
  const [documents, setDocuments] = useState<OnyxDocument[]>([]);
  const [citationMap, setCitationMap] = useState<Map<number, string>>(new Map());
  const citationMapRef = useRef<Map<number, string>>(new Map());
  const [expandedThinkingMessages, setExpandedThinkingMessages] = useState<Set<number>>(new Set());
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  
  // Multi-document state
  const [documentsInContext, setDocumentsInContext] = useState<DocumentContent[]>([]);
  
  // Check if document has pending changes
  const hasPendingChanges = useMemo(() => {
    return /<(addition|deletion)-mark>/.test(documentContent);
  }, [documentContent]);
  
  // Get access to assistants to determine current persona ID
  const { pinnedAssistants, finalAssistants } = useAssistants();
  
  // Use the same logic as ChatPage to determine the live assistant
  const liveAssistant = pinnedAssistants[0] || finalAssistants[0];
  const personaId = liveAssistant?.id || 0;
  
  // Helper function to reset state
  const resetState = useCallback(async () => {
    setMessages([]);
    setDocuments([]);
    setCitationMap(new Map());
    setDocumentsInContext([]);
    
    // Create a new chat session when resetting
    try {
      const response = await fetch('/api/chat/create-chat-session', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          persona_id: personaId, // Use the current persona ID
          description: 'Document Chat Session',
          document_chat: true // Mark as document chat session
        }),
      });
      
      if (response.ok) {
        const data = await response.json();
        setSessionId(data.chat_session_id);
      } else {
        console.error('Failed to create chat session');
        // Fallback to UUID if session creation fails
        setSessionId(uuidv4());
      }
    } catch (error) {
      console.error('Error creating chat session:', error);
      // Fallback to UUID if session creation fails
      setSessionId(uuidv4());
    }
  }, [personaId]);
  
  // Auto-add current document to context when component mounts or document changes
  useEffect(() => {
    if (documentContent && documentTitle) {
      // Use the actual document ID if available, otherwise fall back to 'current-document'
      const docId = documentIds.length > 0 ? documentIds[0] : 'current-document';
      
      const currentDoc: DocumentContent = {
        id: docId,
        title: documentTitle,
        content: documentContent,
        type: documentType
      };
      
      // Check if current document is already in context
      const isAlreadyInContext = documentsInContext.some(doc => doc.id === currentDoc.id);
      if (!isAlreadyInContext) {
        setDocumentsInContext([currentDoc]);
      }
    }
  }, [documentContent, documentTitle, documentType, documentIds]);
  
  // Handle adding documents to context
  const handleAddDocument = useCallback((document: DocumentContent) => {
    setDocumentsInContext(prev => {
      const isAlreadyAdded = prev.some(doc => doc.id === document.id);
      if (!isAlreadyAdded) {
        return [...prev, document];
      }
      return prev;
    });
  }, []);
  
  // Handle removing documents from context
  const handleRemoveDocument = useCallback((documentId: string) => {
    setDocumentsInContext(prev => prev.filter(doc => doc.id !== documentId));
  }, []);

  // Keep the ref in sync with the state
  useEffect(() => {
    citationMapRef.current = citationMap;
  }, [citationMap]);

  // Effect to handle textarea auto-resize when it mounts or message changes
  useEffect(() => {
    if (textAreaRef.current) {
      textAreaRef.current.style.height = 'auto';
      textAreaRef.current.style.height = `${textAreaRef.current.scrollHeight}px`;
    }
  }, [message]);

  const orderedDocuments = useMemo(() => {
    if (citationMap.size === 0 || documents.length === 0) {
      return documents;
    }
    
    const docMap = new Map(documents.map(doc => [doc.document_id, doc]));
    
    const maxCitationNum = Math.max(...Array.from(citationMap.keys()));
    const orderedDocs: OnyxDocument[] = new Array(maxCitationNum);
    
    Array.from(citationMap.entries()).forEach(([citationNum, documentId]) => {
      const doc = docMap.get(documentId);
      if (doc) {
        orderedDocs[citationNum - 1] = doc;
      }
    });
    
    let fillIndex = 0;
    for (let i = 0; i < orderedDocs.length; i++) {
      if (!orderedDocs[i]) {
        while (fillIndex < documents.length && orderedDocs.includes(documents[fillIndex])) {
          fillIndex++;
        }
        if (fillIndex < documents.length) {
          orderedDocs[i] = documents[fillIndex++];
        }
      }
    }
    
    return orderedDocs.filter(Boolean);
  }, [citationMap, documents]);

  const anchorCallback = useCallback(
    (props: any) => (
      <MemoizedAnchor
        updatePresentingDocument={setPresentingDocument}
        docs={orderedDocuments}
        userFiles={[]}
        href={props.href}
      >
        {props.children}
      </MemoizedAnchor>
    ),
    [orderedDocuments]
  );

  const paragraphCallback = useCallback(
    (props: any) => (
      <MemoizedParagraph fontSize="sm">
        {props.children}
      </MemoizedParagraph>
    ),
    []
  );

  const markdownComponents = useMemo(
    () => ({
      a: anchorCallback,
      p: paragraphCallback,
      b: ({ node, className, children }: any) => {
        return <span className={className}>{children}</span>;
      },
      code: ({ node, className, children }: any) => {
        const codeText = extractCodeText(
          node,
          children?.toString() || '',
          children
        );

        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    }),
    [anchorCallback, paragraphCallback]
  );

  // Create a proper chat session when the component mounts
  useEffect(() => {
    const createChatSession = async () => {
      try {
        const response = await fetch('/api/chat/create-chat-session', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
                  body: JSON.stringify({
          persona_id: personaId, // Use the current persona ID
          description: 'Document Chat Session',
          document_chat: true // Mark as document chat session
        }),
        });
        
        if (response.ok) {
          const data = await response.json();
          setSessionId(data.chat_session_id);
        } else {
          console.error('Failed to create chat session');
          // Fallback to UUID if session creation fails
          setSessionId(uuidv4());
        }
      } catch (error) {
        console.error('Error creating chat session:', error);
        // Fallback to UUID if session creation fails
        setSessionId(uuidv4());
      }
    };
    
    createChatSession();
  }, [personaId]);

  // Function to preprocess message text and convert single bracket citations to double bracket format
  const preprocessCitations = (text: string): string => {
    if (!text || citationMapRef.current.size === 0) return text;
    
    // Match single bracket citations like [1], [2], etc. but NOT [[1]] (double brackets)
    // Negative lookbehind (?<!\[) ensures there's no [ before, negative lookahead (?!\]) ensures no ] after
    const singleBracketPattern = /(?<!\[)\[(\d+)\](?!\])/g;
    
    return text.replace(singleBracketPattern, (match, citationNum) => {
      const num = parseInt(citationNum, 10);
      const actualUrl = citationMapRef.current.get(num);
      
      if (actualUrl) {
        console.log('Converting single bracket citation:', {
          original: match,
          citationNum: num,
          actualUrl,
          converted: `[[${citationNum}]](${actualUrl})`
        });
        
        // Convert to double bracket format with actual URL
        return `[[${citationNum}]](${actualUrl})`;
      } else {
        console.log('No citation mapping found for:', match, 'Available mappings:', Array.from(citationMapRef.current.entries()));
      }
      
      // If no citation mapping found, leave as is
      return match;
    });
  };

  // Helper function to wrap entire text with all available citations  
  const wrapEntireTextWithCitations = (
    text: string,
    citeMap: Map<number, string>
  ): string => {
    // If text has addition-mark tags, always wrap them with citations
    if (/<addition-mark>/.test(text)) {
      // Use citation from map if available, otherwise default to citation 1
      const citationNum = citeMap.size > 0 ? Array.from(citeMap.entries())[0][0] : 1;
      const actualUrl = citeMap.get(citationNum);

      console.log('Document editor wrapEntireTextWithCitations:', {
        citationNum,
        actualUrl,
        hasAdditionMarks: true,
        citationMapSize: citeMap.size
      });

      // Replace addition-mark content with citation-mark wrapped content using span instead of anchor
      const result = text.replace(
        /<addition-mark>(.*?)<\/addition-mark>/g,
        `<addition-mark><span class="citation-mark" data-url="${actualUrl || `#citation-${citationNum}`}" data-document-id="doc-${citationNum}">$1</span></addition-mark>`
      );
      
      console.log('Citation wrapping result:', {
        originalHasAdditionMarks: /<addition-mark>/.test(text),
        resultHasAdditionMarks: /<addition-mark>/.test(result),
        resultHasCitationMarks: /citation-mark/.test(result),
        citationNum,
        actualUrl
      });
      
      return result;
    }

    console.log('No addition-mark tags found, returning plain text');
    return text;
  };

  const handleSendMessage = async () => {
    // Reset textarea height after sending message
    if (textAreaRef.current) {
      textAreaRef.current.style.height = 'auto';
    }
    if (!message.trim()) return;
    setIsLoading(true);
    
    const newMessage = {
      id: Date.now(),
      text: message,
      isUser: true
    };
    
    // Add the user message to existing messages
    setMessages(prev => [...prev, newMessage]);
    setMessage('');
    
    try {
      const response = await fetch('/api/chat/document-chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: message,
          document_ids: documentIds, // Use passed document IDs
          session_id: sessionId,
          documents: documentsInContext, // Send multiple documents
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to send message');
      }

      try {
        for await (const packet of handleSSEStream<PacketType>(response)) {
          if ('answer_piece' in packet) {
            const agentAnswerPiece = packet as AgentAnswerPiece;
            const answerPiece = agentAnswerPiece.answer_piece;
            
            if (answerPiece) {
              console.log('Processing answer piece:', {
                answerPiece: answerPiece.substring(0, 100) + '...',
                currentCitationMapSize: citationMapRef.current.size,
                currentDocumentsLength: documents.length,
                citationMapEntries: Array.from(citationMapRef.current.entries())
              });
              
              setMessages(prev => {
                const updatedMessages = [...prev];
                const lastMessage = updatedMessages[updatedMessages.length - 1];
                
                // If the last message is from the AI and not an intermediate output, append to it
                if (lastMessage && !lastMessage.isUser && !lastMessage.isIntermediateOutput && !lastMessage.isThinking) {
                  updatedMessages[updatedMessages.length - 1] = {
                    ...lastMessage,
                    text: lastMessage.text + answerPiece
                  };
                } else {
                  // Create a new AI response message
                  updatedMessages.push({
                    id: Date.now() + Math.random(),
                    text: answerPiece,
                    isUser: false,
                    isIntermediateOutput: false
                  });
                }
                
                return updatedMessages;
              });
            }
          } else if ('thinking_piece' in packet) {
            const thinkingPiece = (packet as ThinkingPiece).thinking_piece;
            
            if (thinkingPiece) {
              console.log('Processing thinking piece:', {
                thinkingPiece: thinkingPiece.substring(0, 100) + '...',
              });
              
              setMessages(prev => {
                const updatedMessages = [...prev];
                const lastMessage = updatedMessages[updatedMessages.length - 1];
                
                // If the last message is a thinking bubble, append to it
                if (lastMessage && !lastMessage.isUser && lastMessage.isThinking) {
                  updatedMessages[updatedMessages.length - 1] = {
                    ...lastMessage,
                    text: lastMessage.text + thinkingPiece
                  };
                } else {
                  // Create a new thinking bubble message
                  updatedMessages.push({
                    id: Date.now() + Math.random(),
                    text: thinkingPiece,
                    isUser: false,
                    isIntermediateOutput: false,
                    isThinking: true
                  });
                }
                
                return updatedMessages;
              });
            }
          } else if ('citation_num' in packet && 'document_id' in packet) {
            const citationInfo = packet as CitationInfo;
            console.log('Citation packet:', {
              citation_num: citationInfo.citation_num,
              document_id: citationInfo.document_id
            });
            
            setCitationMap(prev => {
              const newMap = new Map(prev);
              newMap.set(citationInfo.citation_num, citationInfo.document_id);
              // Update the ref immediately
              citationMapRef.current = newMap;
              console.log('Updated citation map:', Array.from(newMap.entries()));
              return newMap;
            });
          } else if ('id' in packet && packet.id == "document_editor_response") {
            // Extract the document_editor_response property from the packet
            const documentEditorResponse = packet.response as DocumentEditorResponse;
            const editedText = documentEditorResponse.edited_text;
            
            console.log('Document editor response received:', {
              success: documentEditorResponse.success,
              editedText: editedText ? editedText.substring(0, 200) + '...' : 'N/A',
              message: documentEditorResponse.message,
              documentId: documentEditorResponse.document_id,
              edited: documentEditorResponse.edited,
              availableDocuments: documents.length,
              citationMapSize: citationMapRef.current.size
            });
            
            // Log the raw content to see existing citations
            if (editedText) {
              console.log('Current document content before processing:', {
                hasExistingCitations: /citation-mark/.test(editedText),
                hasAdditionMarks: /<addition-mark>/.test(editedText),
                hasDeletionMarks: /<deletion-mark>/.test(editedText),
                contentPreview: editedText.substring(0, 500) + '...'
              });
            }
            
            if (documentEditorResponse.success && editedText && setContent) {
              // Wrap text with citations from current session
              const textWithCitations = wrapEntireTextWithCitations(
                editedText,
                citationMapRef.current
              );
              console.log('Final result from wrapEntireTextWithCitations:', {
                resultPreview: textWithCitations.substring(0, 500) + '...',
                hasCitationMarks: /citation-mark/.test(textWithCitations)
              });
              setContent(textWithCitations);
            } else if (!documentEditorResponse.success) {
              console.error('Document editing failed:', documentEditorResponse.message);
            }
          // Only display tool on receiving ToolCallKickoff packets, not ToolCallResult packets 
          // TODO: Add a symbol for tool completion
          } else if ('tool_name' in packet && !('tool_result' in packet)) {
            // Handle tool call packets for debugging display
            const toolName = (packet as any).tool_name;
            
            // Convert tool names to more friendly messages
            let friendlyToolName = "";
            if (toolName === 'run_search') friendlyToolName = "🔍 Searching for information";
            // TODO: The id for intermediate tool results is "id" not "tool_name"
            // else if (toolName === 'section_relevance') friendlyToolName = "📊 Analyzing relevance";
            // else if (toolName === 'context') friendlyToolName = "📚 Gathering context";
            else if (toolName === 'document_editor') friendlyToolName = "📝 Editing document";
            
            if (friendlyToolName) {
              setMessages(prev => {
                const updatedMessages = [...prev];
                const lastMessage = updatedMessages[updatedMessages.length - 1];
                
                // If the last message is an intermediate output (tool use), append to it
                if (lastMessage && !lastMessage.isUser && lastMessage.isIntermediateOutput) {
                  const currentText = lastMessage.text || '';
                  updatedMessages[updatedMessages.length - 1] = {
                    ...lastMessage,
                    text: currentText ? `${currentText}\n${friendlyToolName}` : friendlyToolName,
                    debugLog: [...(lastMessage.debugLog || []), { type: 'tool', name: toolName }]
                  };
                } else {
                  // Create a new intermediate output message
                  updatedMessages.push({
                    id: Date.now() + Math.random(),
                    text: friendlyToolName,
                    isUser: false,
                    isIntermediateOutput: true,
                    debugLog: [{ type: 'tool', name: toolName }]
                  });
                }
                
                return updatedMessages;
              });
            }
          } else if ('top_documents' in packet) {
            const documentPacket = packet as DocumentInfoPacket;
            if (documentPacket.top_documents && documentPacket.top_documents.length > 0) {
              console.log('DocumentInfoPacket received:', documentPacket.top_documents);
              setDocuments(prev => {
                const existingIds = new Set(prev.map(doc => doc.document_id));
                const newDocs = documentPacket.top_documents.filter(doc => !existingIds.has(doc.document_id));
                const updatedDocs = [...prev, ...newDocs];
                console.log('Updated documents array:', {
                  previousLength: prev.length,
                  newDocsAdded: newDocs.length,
                  totalLength: updatedDocs.length,
                  documentIds: updatedDocs.map(d => d.document_id)
                });
                return updatedDocs;
              });
            }
          } else if ('chat_complete' in packet) {
            console.log('Chat complete received');
            setIsLoading(false);
          }
        }
      } catch (error) {
        console.error('Error processing stream:', error);
      }
      
      setIsLoading(false);
      
    } catch (error) {
      console.error('Error sending message:', error);
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        text: "Sorry, I encountered an error. Please try again.",
        isUser: false
      }]);
      setIsLoading(false);
    }
  };

  const getThinkingPreview = (text: string, maxLength: number = 100) => {
    if (text.length <= maxLength) return text;
    const truncated = text.substring(0, maxLength);
    const lastSpace = truncated.lastIndexOf(' ');
    return (lastSpace > 0 ? truncated.substring(0, lastSpace) : truncated) + '...';
  };

  const toggleThinkingMessage = (messageId: number) => {
    setExpandedThinkingMessages(prev => {
      const newSet = new Set(prev);
      if (newSet.has(messageId)) {
        newSet.delete(messageId);
      } else {
        newSet.add(messageId);
      }
      return newSet;
    });
  };

  const isThinkingExpanded = (messageId: number) => expandedThinkingMessages.has(messageId);

  const handleDocumentChangeConfirmation = async (action: 'confirm' | 'reject') => {
    if (!setContent) return;
    
    try {
      const response = await fetch('/api/chat/confirm-document-changes', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          action: action,
          document_content: documentContent,
          session_id: sessionId
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to process document changes');
      }

      const result = await response.json();
      
      if (result.success) {
        setContent(result.processed_content);
        
        // Add a system message to the chat
        setMessages(prev => [...prev, {
          id: Date.now(),
          text: result.message,
          isUser: false,
          isIntermediateOutput: true
        }]);
      } else {
        console.error('Failed to process changes:', result.message);
      }
    } catch (error) {
      console.error('Error processing document changes:', error);
    }
  };

  return (
    <div
      className={`relative bg-background max-w-full border-l border-sidebar-border dark:border-neutral-700 h-screen`}
      style={{ width: initialWidth }}
    >
      <div className="h-full">
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="p-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-bold text-text-900">Chat</h2>
              <Button
                variant="create"
                size="xs"
                onClick={resetState}
                className="mr-8"
                tooltip="Start a new chat"
                icon={FiPlus}
              >
                New Chat
              </Button>
            </div>
            <div className="border-b border-divider-history-sidebar-bar" />
          </div>
          
          {/* Document Selector */}
          <DocumentSelector
            documentsInContext={documentsInContext}
            onAddDocument={handleAddDocument}
            onRemoveDocument={handleRemoveDocument}
            availableFiles={availableFiles}
          />

          {/* Messages */}
          <div className="flex-grow overflow-y-auto p-4 space-y-3">
            {messages.length === 0 ? (
              <div className="text-center text-muted-foreground py-8">
                <FiMessageSquare size={48} className="mx-auto mb-4 opacity-50" />
              </div>
            ) : (
              <>
                {messages.map((msg) => (
                  // Only render messages that have content
                  msg.text && (
                    <div key={msg.id} className={`flex ${msg.isUser ? 'justify-end' : 'justify-start'}`}>
                      <div 
                        className={`max-w-[80%] p-3 rounded-lg ${msg.isUser 
                          ? 'bg-accent text-accent-foreground border border-accent/50' 
                          : msg.isIntermediateOutput
                            ? 'bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-xs font-mono'
                            : msg.isThinking
                              ? (isThinkingExpanded(msg.id) 
                                ? 'bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700/50 text-blue-800 dark:text-blue-200' 
                                : 'bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700/50 text-blue-800 dark:text-blue-200 text-xs')
                              : 'bg-background-chat-hover'}`}
                        style={msg.isIntermediateOutput ? { maxHeight: '300px', overflowY: 'auto' } : {}}
                      >
                        {msg.isThinking ? (
                          <div>
                            {/* Clickable header */}
                            <div 
                              className={`flex items-center gap-2 text-xs opacity-70 cursor-pointer hover:opacity-90 transition-opacity ${
                                isThinkingExpanded(msg.id) ? 'mb-2' : 'mb-0'
                              }`}
                              onClick={() => toggleThinkingMessage(msg.id)}
                            >
                              <span>🧠 Thinking...</span>
                              {isThinkingExpanded(msg.id) ? (
                                <FiChevronDown size={12} />
                              ) : (
                                <FiChevronRight size={12} />
                              )}
                            </div>
                            {/* Collapsible content */}
                            {isThinkingExpanded(msg.id) ? (
                              <ReactMarkdown
                                className="prose dark:prose-invert max-w-full text-sm"
                                components={markdownComponents}
                                remarkPlugins={[remarkGfm, remarkMath]}
                                rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
                                urlTransform={transformLinkUri}
                              >
                                {preprocessLaTeX(preprocessCitations(msg.text))}
                              </ReactMarkdown>
                            ) : null}
                          </div>
                        ) : msg.isIntermediateOutput ? (
                          <pre className="whitespace-pre-wrap">{msg.text}</pre>
                        ) : (
                          <ReactMarkdown
                            className="prose dark:prose-invert max-w-full text-sm"
                            components={markdownComponents}
                            remarkPlugins={[remarkGfm, remarkMath]}
                            rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
                            urlTransform={transformLinkUri}
                          >
                            {preprocessLaTeX(preprocessCitations(msg.text))}
                          </ReactMarkdown>
                        )}
                      </div>
                    </div>
                  )
                ))}
                {isLoading && (
                  <div className="flex justify-start">
                    <div className="max-w-[80%] p-3 rounded-lg bg-background-chat-hover">
                      <div className="flex space-x-2">
                        <div className="h-2 w-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                        <div className="h-2 w-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                        <div className="h-2 w-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Document Change Confirmation UI */}
          {hasPendingChanges && (
            <div className="px-4 py-3 border-t border-border bg-amber-50 dark:bg-amber-900/20">
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm text-amber-800 dark:text-amber-200 font-medium">
                  Document changes pending
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDocumentChangeConfirmation('reject')}
                  className="text-red-600 border-red-300 hover:bg-red-50 dark:text-red-400 dark:border-red-700 dark:hover:bg-red-900/20"
                >
                  Reject Changes
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => handleDocumentChangeConfirmation('confirm')}
                  className="bg-green-600 hover:bg-green-700 text-white dark:bg-green-700 dark:hover:bg-green-800"
                >
                  Accept Changes
                </Button>
              </div>
            </div>
          )}

          {/* Input */}
          <div className="p-4 border-t border-border">
            {hasPendingChanges ? (
              <div className="text-center text-sm text-muted-foreground py-2">
                Please accept or reject document changes before continuing
              </div>
            ) : (
              <div className="flex gap-2">
                <textarea
                  ref={textAreaRef}
                  value={message}
                  onChange={(e) => {
                    setMessage(e.target.value);
                    // Auto-resize the textarea
                    if (textAreaRef.current) {
                      textAreaRef.current.style.height = 'auto';
                      textAreaRef.current.style.height = `${textAreaRef.current.scrollHeight}px`;
                    }
                  }}
                  placeholder="Ask anything"
                  className="flex-grow resize-none border border-border rounded-md p-2 text-sm min-h-[38px] overflow-hidden"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                />
                <button
                  onClick={handleSendMessage}
                  className="px-3 py-2 bg-accent text-accent-foreground rounded-md hover:bg-accent/80 transition-colors"
                >
                  <SendIcon size={16} />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
