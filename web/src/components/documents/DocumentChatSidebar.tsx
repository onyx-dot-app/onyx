'use client';

import React, { useState, useRef } from 'react';
import { SendIcon } from '@/components/icons/icons';
import { XIcon } from 'lucide-react';
import { FiMessageSquare } from 'react-icons/fi';

interface DocumentChatSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  initialWidth: number;
}

export function DocumentChatSidebar({ isOpen, onClose, initialWidth }: DocumentChatSidebarProps) {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState<Array<{id: number, text: string, isUser: boolean}>>([]);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  const handleSendMessage = () => {
    if (!message.trim()) return;
    
    const newMessage = {
      id: Date.now(),
      text: message,
      isUser: true
    };
    
    setMessages(prev => [...prev, newMessage]);
    setMessage('');
    
    setTimeout(() => {
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        text: "I can help you analyze and work with the documents in this sidebar. What would you like to know?",
        isUser: false
      }]);
    }, 1000);
  };

  return (
    <div
      className={`relative bg-background max-w-full border-l border-t border-sidebar-border dark:border-neutral-700 h-[105vh]`}
      style={{ width: initialWidth }}
    >
      <div className={`h-full transition-transform ease-in-out duration-300 ${isOpen ? 'translate-x-0' : 'translate-x-[10%]'}`}>
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="p-4 flex items-center justify-between gap-x-2">
            <div className="flex items-center gap-x-2">
              <FiMessageSquare size={18} />
              <h2 className="text-xl font-bold text-text-900">Document Chat</h2>
            </div>
            <button className="my-auto" onClick={onClose}>
              <XIcon size={16} />
            </button>
          </div>
          <div className="border-b border-divider-history-sidebar-bar mx-3" />

          {/* Messages */}
          <div className="flex-grow overflow-y-auto p-4 space-y-3">
            {messages.length === 0 ? (
              <div className="text-center text-muted-foreground py-8">
                <FiMessageSquare size={48} className="mx-auto mb-4 opacity-50" />
                <p>Start a conversation about your documents</p>
              </div>
            ) : (
              messages.map((msg) => (
                <div key={msg.id} className={`flex ${msg.isUser ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] p-3 rounded-lg ${msg.isUser ? 'bg-accent text-accent-foreground' : 'bg-background-chat-hover'}`}>
                    {msg.text}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Input */}
          <div className="p-4 border-t border-border">
            <div className="flex gap-2">
              <textarea
                ref={textAreaRef}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Ask about these documents..."
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
