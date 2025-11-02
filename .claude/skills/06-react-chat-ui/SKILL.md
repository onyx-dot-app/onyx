---
name: react-chat-ui
description: Real-time chat interface patterns with WebSockets/SSE, message streaming, virtual scrolling, and markdown rendering. Use when building chat features or real-time UI components.
---

# React Chat UI Skill for Onyx

## Overview
Onyx chat interface supports real-time messaging with LLM streaming responses.

## Server-Sent Events for Streaming
```typescript
'use client';
import { useState } from 'react';

function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  
  async function sendMessage(content: string) {
    const userMsg = { role: 'user', content, id: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    
    setStreaming(true);
    const assistantMsg = { role: 'assistant', content: '', id: Date.now() + 1 };
    setMessages(prev => [...prev, assistantMsg]);
    
    const response = await fetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message: content }),
    });
    
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6));
          
          if (data.type === 'token') {
            setMessages(prev => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              last.content += data.content;
              return updated;
            });
          }
        }
      }
    }
    
    setStreaming(false);
  }
  
  return (
    <div>
      <MessageList messages={messages} />
      <MessageInput onSend={sendMessage} disabled={streaming} />
    </div>
  );
}
```

## Virtual Scrolling with react-virtual
```typescript
import { useVirtualizer } from '@tanstack/react-virtual';
import { useRef } from 'react';

function MessageList({ messages }: { messages: Message[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 100,
    overscan: 5,
  });
  
  return (
    <div
      ref={parentRef}
      style={{ height: '600px', overflow: 'auto' }}
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => (
          <div
            key={virtualRow.key}
            data-index={virtualRow.index}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              transform: `translateY(${virtualRow.start}px)`,
            }}
          >
            <Message message={messages[virtualRow.index]} />
          </div>
        ))}
      </div>
    </div>
  );
}
```

## Markdown Rendering with Code Highlighting
```typescript
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';

function MessageContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      components={{
        code({ node, inline, className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || '');
          return !inline && match ? (
            <SyntaxHighlighter
              style={vscDarkPlus}
              language={match[1]}
              PreTag="div"
            >
              {String(children).replace(/\n$/, '')}
            </SyntaxHighlighter>
          ) : (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
        a({ href, children }) {
          return (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          );
        }
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
```

## Optimistic Updates
```typescript
function useChatMessages() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [optimisticIds, setOptimisticIds] = useState<Set<string>>(new Set());
  
  async function sendMessage(content: string) {
    const tempId = `temp-${Date.now()}`;
    const optimisticMsg: Message = {
      id: tempId,
      content,
      role: 'user',
      createdAt: new Date(),
    };
    
    // Add optimistic message
    setMessages(prev => [...prev, optimisticMsg]);
    setOptimisticIds(prev => new Set(prev).add(tempId));
    
    try {
      const response = await fetch('/api/messages', {
        method: 'POST',
        body: JSON.stringify({ content }),
      });
      
      const savedMessage = await response.json();
      
      // Replace optimistic with real message
      setMessages(prev =>
        prev.map(m => m.id === tempId ? savedMessage : m)
      );
      setOptimisticIds(prev => {
        const updated = new Set(prev);
        updated.delete(tempId);
        return updated;
      });
      
    } catch (error) {
      // Rollback on error
      setMessages(prev => prev.filter(m => m.id !== tempId));
      setOptimisticIds(prev => {
        const updated = new Set(prev);
        updated.delete(tempId);
        return updated;
      });
      
      toast.error('Failed to send message');
    }
  }
  
  return { messages, sendMessage, optimisticIds };
}
```

## Auto-scroll to Bottom
```typescript
import { useEffect, useRef } from 'react';

function MessageList({ messages }: { messages: Message[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  
  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, autoScroll]);
  
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
    const isAtBottom = Math.abs(scrollHeight - scrollTop - clientHeight) < 10;
    setAutoScroll(isAtBottom);
  };
  
  return (
    <div onScroll={handleScroll} className="overflow-auto h-full">
      {messages.map(msg => <Message key={msg.id} message={msg} />)}
      <div ref={bottomRef} />
    </div>
  );
}
```

## File Upload Preview
```typescript
function FileUpload({ onUpload }: { onUpload: (file: File) => void }) {
  const [preview, setPreview] = useState<string | null>(null);
  
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    // Show preview for images
    if (file.type.startsWith('image/')) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setPreview(reader.result as string);
      };
      reader.readAsDataURL(file);
    }
    
    onUpload(file);
  };
  
  return (
    <div>
      <input type="file" onChange={handleFileChange} />
      {preview && <img src={preview} alt="Preview" className="w-32 h-32" />}
    </div>
  );
}
```

## Typing Indicator
```typescript
function TypingIndicator({ isTyping }: { isTyping: boolean }) {
  if (!isTyping) return null;
  
  return (
    <div className="flex gap-1 p-3">
      <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </div>
  );
}
```

## Copy Code Button
```typescript
function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);
  
  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  
  return (
    <div className="relative">
      <button
        onClick={copyToClipboard}
        className="absolute top-2 right-2 px-2 py-1 bg-gray-700 rounded"
      >
        {copied ? 'Copied!' : 'Copy'}
      </button>
      <SyntaxHighlighter language={language}>
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
```
