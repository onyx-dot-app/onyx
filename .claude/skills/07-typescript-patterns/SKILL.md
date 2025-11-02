---
name: typescript-patterns
description: Strict typing, discriminated unions, type-safe API clients, and utility types for enterprise TypeScript. Use when writing TypeScript code or ensuring type safety across the codebase.
---

# TypeScript Enterprise Patterns for Onyx

## Overview
Onyx uses strict TypeScript throughout for type safety and better developer experience.

## Type-Safe API Client
```typescript
interface ApiResponse<T> {
  data: T;
  error?: string;
  status: number;
}

async function apiClient<T>(
  endpoint: string,
  options?: RequestInit
): Promise<ApiResponse<T>> {
  const response = await fetch(endpoint, options);
  const data = await response.json();
  
  return {
    data,
    status: response.status,
    error: response.ok ? undefined : data.message
  };
}

// Usage with type inference
const response = await apiClient<Document[]>('/api/documents');
if (response.error) {
  console.error(response.error);
} else {
  const documents = response.data; // Type is Document[]
}
```

## Discriminated Unions for State
```typescript
type LoadingState<T> = 
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: T }
  | { status: 'error'; error: string };

function DataDisplay({ state }: { state: LoadingState<Document[]> }) {
  switch (state.status) {
    case 'idle':
      return <div>Click to load</div>;
    case 'loading':
      return <Spinner />;
    case 'success':
      // TypeScript knows state.data exists here
      return <div>{state.data.map(doc => <div key={doc.id}>{doc.title}</div>)}</div>;
    case 'error':
      // TypeScript knows state.error exists here
      return <div>Error: {state.error}</div>;
  }
}
```

## Generic Utility Types
```typescript
// Make specific fields optional
type PartialBy<T, K extends keyof T> = Omit<T, K> & Partial<Pick<T, K>>;

interface User {
  id: string;
  name: string;
  email: string;
}

// id is optional, rest required
type UserCreate = PartialBy<User, 'id'>;

// Make specific fields required
type RequiredBy<T, K extends keyof T> = T & Required<Pick<T, K>>;

// Deep partial
type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};

// Deep readonly
type DeepReadonly<T> = {
  readonly [P in keyof T]: T[P] extends object ? DeepReadonly<T[P]> : T[P];
};
```

## Type Guards
```typescript
interface Document {
  id: string;
  title: string;
  content: string;
}

interface Folder {
  id: string;
  name: string;
  items: (Document | Folder)[];
}

// Type guard
function isDocument(item: Document | Folder): item is Document {
  return 'content' in item;
}

function isFolder(item: Document | Folder): item is Folder {
  return 'items' in item;
}

// Usage
function processItem(item: Document | Folder) {
  if (isDocument(item)) {
    console.log(item.content); // TypeScript knows it's Document
  } else {
    console.log(item.items); // TypeScript knows it's Folder
  }
}
```

## Zod for Runtime Validation
```typescript
import { z } from 'zod';

const DocumentSchema = z.object({
  id: z.string().uuid(),
  title: z.string().min(1).max(200),
  content: z.string(),
  tags: z.array(z.string()).optional(),
  metadata: z.record(z.string(), z.any()).optional(),
  createdAt: z.string().datetime(),
});

type Document = z.infer<typeof DocumentSchema>;

// Validate at runtime
function validateDocument(data: unknown): Document {
  return DocumentSchema.parse(data); // Throws if invalid
}

// Safe parse (returns result object)
function safeValidateDocument(data: unknown) {
  const result = DocumentSchema.safeParse(data);
  
  if (result.success) {
    return result.data;
  } else {
    console.error('Validation errors:', result.error.errors);
    return null;
  }
}

// Use in API route
export async function POST(request: Request) {
  const body = await request.json();
  const validation = DocumentSchema.safeParse(body);
  
  if (!validation.success) {
    return Response.json(
      { error: 'Invalid data', details: validation.error.errors },
      { status: 400 }
    );
  }
  
  const document = validation.data;
  // Now fully typed and validated
  await saveDocument(document);
  
  return Response.json(document);
}
```

## Branded Types
```typescript
type DocumentId = string & { readonly __brand: 'DocumentId' };
type UserId = string & { readonly __brand: 'UserId' };

function createDocumentId(id: string): DocumentId {
  return id as DocumentId;
}

function createUserId(id: string): UserId {
  return id as UserId;
}

function getDocument(id: DocumentId): Document {
  // Implementation
}

const docId = createDocumentId('doc-123');
const userId = createUserId('user-456');

getDocument(docId); // ✓ OK
getDocument(userId); // ✗ Error: Type 'UserId' not assignable to 'DocumentId'
```

## Const Assertions
```typescript
// Without const assertion
const config = {
  apiUrl: 'https://api.example.com',
  timeout: 5000,
};
// Type: { apiUrl: string; timeout: number; }

// With const assertion
const configConst = {
  apiUrl: 'https://api.example.com',
  timeout: 5000,
} as const;
// Type: { readonly apiUrl: "https://api.example.com"; readonly timeout: 5000; }

// Array with const assertion
const DOCUMENT_TYPES = ['pdf', 'docx', 'txt'] as const;
type DocumentType = typeof DOCUMENT_TYPES[number]; // 'pdf' | 'docx' | 'txt'
```

## Template Literal Types
```typescript
type HTTPMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';
type APIVersion = 'v1' | 'v2';
type APIPath = `/api/${APIVersion}/${string}`;

function makeRequest(path: APIPath, method: HTTPMethod) {
  // Implementation
}

makeRequest('/api/v1/documents', 'GET'); // ✓ OK
makeRequest('/api/v2/users', 'POST'); // ✓ OK
makeRequest('/documents', 'GET'); // ✗ Error
```

## Mapped Types
```typescript
type Optional<T> = {
  [P in keyof T]?: T[P];
};

type Nullable<T> = {
  [P in keyof T]: T[P] | null;
};

type ReadonlyDeep<T> = {
  readonly [P in keyof T]: T[P] extends object ? ReadonlyDeep<T[P]> : T[P];
};

interface User {
  id: string;
  name: string;
  email: string;
}

type OptionalUser = Optional<User>;
// { id?: string; name?: string; email?: string; }

type NullableUser = Nullable<User>;
// { id: string | null; name: string | null; email: string | null; }
```

## Function Overloads
```typescript
function processData(data: string): string;
function processData(data: number): number;
function processData(data: boolean): boolean;
function processData(data: string | number | boolean): string | number | boolean {
  if (typeof data === 'string') {
    return data.toUpperCase();
  } else if (typeof data === 'number') {
    return data * 2;
  } else {
    return !data;
  }
}

const result1 = processData('hello'); // Type: string
const result2 = processData(42); // Type: number
const result3 = processData(true); // Type: boolean
```

## Conditional Types
```typescript
type IsString<T> = T extends string ? true : false;

type Test1 = IsString<string>; // true
type Test2 = IsString<number>; // false

// More complex example
type ExtractArrayType<T> = T extends (infer U)[] ? U : T;

type StringArray = string[];
type ExtractedType = ExtractArrayType<StringArray>; // string

// Exclude null and undefined
type NonNullable<T> = T extends null | undefined ? never : T;

type MaybeString = string | null | undefined;
type DefiniteString = NonNullable<MaybeString>; // string
```

## Testing
```typescript
import { describe, it, expect } from 'vitest';

describe('Type-safe API client', () => {
  it('should return typed response', async () => {
    const response = await apiClient<{ message: string }>('/api/test');
    
    expect(response.data).toHaveProperty('message');
    expect(typeof response.data.message).toBe('string');
  });
  
  it('should handle errors', async () => {
    const response = await apiClient<never>('/api/error');
    
    expect(response.error).toBeDefined();
  });
});
```
