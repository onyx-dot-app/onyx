'use client';

import React, { useState, useRef, useEffect } from 'react';
import { SendIcon } from '@/components/icons/icons';
import { FiMessageSquare } from 'react-icons/fi';
import { v4 as uuidv4 } from 'uuid';

interface DocumentChatSidebarProps {
  initialWidth: number;
  documentIds?: string[]; // Accept document IDs from parent component
}

export function DocumentChatSidebar({ initialWidth, documentIds = [] }: DocumentChatSidebarProps) {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState<Array<{id: number, text: string, isUser: boolean, isIntermediateOutput?: boolean, debugLog?: Array<any>}>>([]);
  const [sessionId, setSessionId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

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
      
      const reader = response.body?.getReader();
      
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          const chunk = new TextDecoder().decode(value);
          const lines = chunk.split('\n').filter(line => line.trim());
          
          for (const line of lines) {
            try {
              const data = JSON.parse(line);
              if (data.type === 'stream' && data.data) {
                // Extract answer_piece from the string format "answer_piece='...'" 
                const answerPieceMatch = data.data.match(/answer_piece='(.*)'/); 
                
                // Extract tool call information for visual debugging
                const toolCallMatch = data.data.match(/tool_name='([^']+)'(.*)/); 
                
                // Handle answer pieces by appending them to the existing text
                if (answerPieceMatch && answerPieceMatch[1]) {
                  const answerPiece = answerPieceMatch[1];
                  // Only update if answer piece has content
                  if (answerPiece.trim()) {
                    setMessages(prev => {
                      const updatedMessages = [...prev];
                      
                      // Find the dedicated response message
                      const responseIndex = updatedMessages.findIndex(
                        msg => msg.id === aiResponseId && !msg.isIntermediateOutput
                      );
                      
                      if (responseIndex !== -1) {
                        // Append this piece to the existing response text
                        updatedMessages[responseIndex] = {
                          ...updatedMessages[responseIndex],
                          text: updatedMessages[responseIndex].text + answerPiece
                        };
                      }
                      
                      return updatedMessages;
                    });
                  }
                }
                // Display tool calls as intermediate output for visualization
                else if (toolCallMatch) {
                  const toolName = toolCallMatch[1];
                  // We don't need to use toolArgs, just extract the tool name
                  
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
                      
                      // Append to existing log instead of replacing
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
                }
                // Handle other interesting streams like search responses
                else if (data.data.includes('id=\'search_response_summary\'') || 
                         data.data.includes('id=\'section_relevance_list\'') ||
                         data.data.includes('id=\'final_context_documents\'')) {
                  const idMatch = data.data.match(/id='([^']+)'/);
                  const id = idMatch ? idMatch[1] : 'unknown';
                  
                  setMessages(prev => {
                    const updatedMessages = [...prev];
                    
                    // Find the debug log message
                    const debugLogIndex = updatedMessages.findIndex(msg => msg.id === debugLogId);
                    
                    if (debugLogIndex !== -1) {
                      // Convert processing steps to more friendly messages
                      let friendlyProcessing = "📊 Analyzing results";
                      if (id === 'search_response_summary') friendlyProcessing = "🔍 Reviewing search results";
                      else if (id === 'section_relevance_list') friendlyProcessing = "📋 Identifying relevant sections";
                      else if (id === 'final_context_documents') friendlyProcessing = "📚 Reading documents";
                      else friendlyProcessing = `📊 Processing: ${id}`;
                      
                      const processingInfo = friendlyProcessing;
                      
                      // Append to existing log instead of replacing
                      const currentText = updatedMessages[debugLogIndex].text || '';
                      updatedMessages[debugLogIndex] = {
                        ...updatedMessages[debugLogIndex],
                        text: currentText ? `${currentText}\n${processingInfo}` : processingInfo,
                        isIntermediateOutput: true,
                        debugLog: [...(updatedMessages[debugLogIndex].debugLog || []), { type: 'processing', id }]
                      };
                    }
                    
                    return updatedMessages;
                  });
                }
              }
            } catch (error) {
              console.debug('Error parsing stream data:', error);
              // Continue processing other lines
            }
          }
        }
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
                        {msg.isIntermediateOutput
                          ? <pre className="whitespace-pre-wrap">{msg.text}</pre>
                          : msg.text}
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
