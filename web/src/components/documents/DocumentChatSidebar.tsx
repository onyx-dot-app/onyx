'use client';

import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { SendIcon } from '@/components/icons/icons';
import { FiMessageSquare } from 'react-icons/fi';
import { v4 as uuidv4 } from 'uuid';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypePrism from 'rehype-prism-plus';
import rehypeKatex from 'rehype-katex';
import { MemoizedAnchor, MemoizedParagraph } from '@/app/chat/message/MemoizedTextComponents';
import { extractCodeText, preprocessLaTeX } from '@/app/chat/message/codeUtils';
import { CodeBlock } from '@/app/chat/message/CodeBlock';
import { transformLinkUri } from '@/lib/utils';
import { handleSSEStream } from '@/lib/search/streamingUtils';
import { PacketType } from '@/app/chat/lib';
import { AgentAnswerPiece, OnyxDocument, DocumentInfoPacket } from '@/lib/search/interfaces';

interface CitationInfo {
  citation_num: number;
  document_id: string;
  level?: number | null;
  level_question_num?: number | null;
}

interface DocumentChatSidebarProps {
  initialWidth: number;
  documentIds?: string[]; // Accept document IDs from parent component
}

export function DocumentChatSidebar({ initialWidth, documentIds = [] }: DocumentChatSidebarProps) {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState<Array<{id: number, text: string, isUser: boolean, isIntermediateOutput?: boolean, debugLog?: Array<any>}>>([]);
  const [sessionId, setSessionId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [presentingDocument, setPresentingDocument] = useState<any>(null);
  const [documents, setDocuments] = useState<OnyxDocument[]>([]);
  const [citationMap, setCitationMap] = useState<Map<number, string>>(new Map());
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

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

  // Generate a session ID once when the component mounts
  useEffect(() => {
    setSessionId(uuidv4());
  }, []);

  const handleSendMessage = async () => {
    if (!message.trim()) return;
    setIsLoading(true);
    
    const newMessage = {
      id: Date.now(),
      text: message,
      isUser: true
    };
    
    setMessages(prev => [...prev, newMessage]);
    setMessage('');
    
    setDocuments([]);
    setCitationMap(new Map());
    
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
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to send message');
      }

      // Create placeholders for both the debug log and the AI response
      const debugLogId = Date.now() + 1;
      const aiResponseId = Date.now() + 2;
      
      setMessages(prev => [...prev, 
        {
          id: debugLogId,
          text: "",
          isUser: false,
          isIntermediateOutput: true,
          debugLog: []
        },
        {
          id: aiResponseId,
          text: "",
          isUser: false,
          isIntermediateOutput: false
        }
      ]);
      
      try {
        for await (const packet of handleSSEStream<PacketType>(response)) {
          console.log('DocumentChatSidebar packet:', packet);
          
          if ('answer_piece' in packet) {
            const agentAnswerPiece = packet as AgentAnswerPiece;
            const answerPiece = agentAnswerPiece.answer_piece;
            
            if (answerPiece && answerPiece.trim()) {
              setMessages(prev => {
                const updatedMessages = [...prev];
                
                const responseIndex = updatedMessages.findIndex(
                  msg => msg.id === aiResponseId && !msg.isIntermediateOutput
                );
                
                if (responseIndex !== -1) {
                  const newText = updatedMessages[responseIndex].text + answerPiece;
                  updatedMessages[responseIndex] = {
                    ...updatedMessages[responseIndex],
                    text: newText
                  };
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
              return newMap;
            });
          } else if ('tool_name' in packet) {
            // Handle tool call packets for debugging display
            const toolName = (packet as any).tool_name;
            
            setMessages(prev => {
              const updatedMessages = [...prev];
              
              // Find the debug log message
              const debugLogIndex = updatedMessages.findIndex(msg => msg.id === debugLogId);
              
              if (debugLogIndex !== -1) {
                // Convert tool names to more friendly messages
                let friendlyToolName = "🔍 Searching";
                if (toolName === 'document_chat') friendlyToolName = "💬 Finding relevant documents";
                else if (toolName === 'run_search') friendlyToolName = "🔍 Searching for information";
                else if (toolName.includes('section_relevance')) friendlyToolName = "📊 Analyzing relevance";
                else if (toolName.includes('context')) friendlyToolName = "📚 Gathering context";
                
                const intermediateInfo = friendlyToolName;
                
                const currentText = updatedMessages[debugLogIndex].text || '';
                updatedMessages[debugLogIndex] = {
                  ...updatedMessages[debugLogIndex],
                  text: currentText ? `${currentText}\n${intermediateInfo}` : intermediateInfo,
                  isIntermediateOutput: true,
                  debugLog: [...(updatedMessages[debugLogIndex].debugLog || []), { type: 'tool', name: toolName }]
                };
              }
              
              return updatedMessages;
            });
          } else if ('top_documents' in packet) {
            const documentPacket = packet as DocumentInfoPacket;
            if (documentPacket.top_documents && documentPacket.top_documents.length > 0) {
              console.log('DocumentInfoPacket received:', documentPacket.top_documents);
              setDocuments(prev => {
                const existingIds = new Set(prev.map(doc => doc.document_id));
                const newDocs = documentPacket.top_documents.filter(doc => !existingIds.has(doc.document_id));
                const updatedDocs = [...prev, ...newDocs];
                console.log('Updated documents array:', updatedDocs);
                return updatedDocs;
              });
            }
          }
        }
      } catch (error) {
        console.error('Error processing stream:', error);
      }
      
      // When all streams are done, ensure we have a proper response if none was generated
      setMessages(prev => {
        const updatedMessages = [...prev];
        
        // Find the AI response message
        const responseIndex = updatedMessages.findIndex(msg => msg.id === aiResponseId);
        
        // If response exists but is empty, add a default message
        if (responseIndex !== -1 && !updatedMessages[responseIndex].text.trim()) {
          updatedMessages[responseIndex] = {
            ...updatedMessages[responseIndex],
            text: "I've analyzed the documents. How can I help you further?"
          };
        }
        
        return updatedMessages;
      });
      
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

  return (
    <div
      className={`relative bg-background max-w-full border-l border-t border-sidebar-border dark:border-neutral-700 h-screen`}
      style={{ width: initialWidth }}
    >
      <div className="h-full">
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="p-4 flex items-center gap-x-2">
            <div className="flex items-center gap-x-2">
              <h2 className="text-xl font-bold text-text-900">Chat</h2>
            </div>
          </div>
          <div className="border-b border-divider-history-sidebar-bar mx-3" />

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
                            : 'bg-background-chat-hover'}`}
                        style={msg.isIntermediateOutput ? { maxHeight: '300px', overflowY: 'auto' } : {}}
                      >
                        {msg.isIntermediateOutput ? (
                          <pre className="whitespace-pre-wrap">{msg.text}</pre>
                        ) : (
                          <ReactMarkdown
                            className="prose dark:prose-invert max-w-full text-sm"
                            components={markdownComponents}
                            remarkPlugins={[remarkGfm, remarkMath]}
                            rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
                            urlTransform={transformLinkUri}
                          >
                            {preprocessLaTeX(msg.text)}
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

          {/* Input */}
          <div className="p-4 border-t border-border">
            <div className="flex gap-2">
              <textarea
                ref={textAreaRef}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Ask anything"
                className="flex-grow resize-none border border-border rounded-md p-2 text-sm max-h-20"
                rows={2}
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
          </div>
        </div>
      </div>
    </div>
  );
}
