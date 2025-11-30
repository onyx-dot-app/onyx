---
name: nextjs-enterprise-app
description: Next.js App Router patterns, server/client components, state management, and performance optimization for Onyx frontend. Use when building UI features, optimizing performance, or implementing routing.
---

# Next.js Enterprise App Skill for Onyx

## Overview
Onyx uses Next.js 14+ with App Router, TypeScript, and Tailwind CSS for its frontend.

## File Structure
```
web/
├── app/
│   ├── (auth)/
│   ├── (dashboard)/
│   ├── api/
│   └── layout.tsx
├── components/
│   ├── ui/
│   └── features/
└── lib/
```

## Server vs Client Components
```typescript
// Server Component (default in app directory)
async function DocumentList() {
  const docs = await fetchDocuments();
  return <div>{docs.map(d => <DocCard key={d.id} doc={d} />)}</div>;
}

// Client Component
'use client';
import { useState } from 'react';

function SearchBar() {
  const [query, setQuery] = useState('');
  return <input value={query} onChange={(e) => setQuery(e.target.value)} />;
}
```

## App Router Patterns
```typescript
// app/documents/page.tsx
export default async function DocumentsPage() {
  return <DocumentList />;
}

// app/documents/[id]/page.tsx
export default async function DocumentPage({ params }: { params: { id: string } }) {
  const doc = await getDocument(params.id);
  return <DocumentDetail doc={doc} />;
}

// app/api/search/route.ts
export async function POST(request: Request) {
  const { query } = await request.json();
  const results = await search(query);
  return Response.json(results);
}
```

## State Management with Zustand
```typescript
import { create } from 'zustand';

interface AppState {
  documents: Document[];
  selectedDoc: Document | null;
  setDocuments: (docs: Document[]) => void;
  selectDocument: (doc: Document) => void;
}

export const useStore = create<AppState>((set) => ({
  documents: [],
  selectedDoc: null,
  setDocuments: (documents) => set({ documents }),
  selectDocument: (selectedDoc) => set({ selectedDoc })
}));

// Usage
function MyComponent() {
  const { documents, setDocuments } = useStore();
  // ...
}
```

## Data Fetching
```typescript
// Server component with caching
async function fetchDocuments() {
  const res = await fetch('http://api/documents', {
    cache: 'force-cache', // or 'no-store'
    next: { revalidate: 3600 } // revalidate every hour
  });
  return res.json();
}

// Client component with SWR
'use client';
import useSWR from 'swr';

function DocumentList() {
  const { data, error, isLoading } = useSWR('/api/documents', fetcher);
  
  if (isLoading) return <Loading />;
  if (error) return <Error />;
  return <div>{data.map(...)}</div>;
}
```

## Streaming with Suspense
```typescript
import { Suspense } from 'react';

export default function Page() {
  return (
    <>
      <Header />
      <Suspense fallback={<DocumentsSkeleton />}>
        <DocumentList />
      </Suspense>
      <Suspense fallback={<AnalyticsSkeleton />}>
        <Analytics />
      </Suspense>
    </>
  );
}
```

## Middleware for Auth
```typescript
// middleware.ts
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const token = request.cookies.get('session');
  
  if (!token && !request.nextUrl.pathname.startsWith('/login')) {
    return NextResponse.redirect(new URL('/login', request.url));
  }
  
  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/api/:path*']
};
```

## Performance Optimization
```typescript
// Dynamic imports
import dynamic from 'next/dynamic';

const HeavyComponent = dynamic(() => import('./HeavyComponent'), {
  loading: () => <p>Loading...</p>,
  ssr: false // disable SSR for this component
});

// Image optimization
import Image from 'next/image';

<Image 
  src="/doc-thumbnail.jpg"
  alt="Document"
  width={300}
  height={200}
  loading="lazy"
/>

// Font optimization
import { Inter } from 'next/font/google';

const inter = Inter({ subsets: ['latin'] });

export default function Layout({ children }) {
  return <div className={inter.className}>{children}</div>;
}
```

## Error Handling
```typescript
// app/error.tsx
'use client';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div>
      <h2>Something went wrong!</h2>
      <button onClick={() => reset()}>Try again</button>
    </div>
  );
}

// app/not-found.tsx
export default function NotFound() {
  return <div>404 - Page Not Found</div>;
}
```

## Testing
```typescript
import { render, screen } from '@testing-library/react';
import DocumentList from './DocumentList';

test('renders document list', async () => {
  render(<DocumentList />);
  const heading = await screen.findByText(/documents/i);
  expect(heading).toBeInTheDocument();
});
```
