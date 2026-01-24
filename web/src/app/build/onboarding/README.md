# Build User Persona Cookie

This document explains how the build user persona data is stored and used.

## Cookie Structure

User persona information (work area and level) is stored in a single consolidated cookie named `build_user_persona`.

**Cookie Name:** `build_user_persona`

**Cookie Value:** JSON-encoded object with the following structure:

```typescript
{
  workArea: string,    // e.g., "engineering", "product", "sales"
  level?: string       // e.g., "ic", "manager" (optional)
}
```

**Example Cookie Value:**

```
build_user_persona={"workArea":"engineering","level":"ic"}
```

## Reading the Cookie

### Frontend (TypeScript/React)

Use the helper function `getBuildUserPersona()`:

```typescript
import { getBuildUserPersona } from "@/app/build/onboarding/constants";

// Get the persona data
const persona = getBuildUserPersona();

if (persona) {
  console.log("Work Area:", persona.workArea); // "engineering"
  console.log("Level:", persona.level); // "ic"
}
```

### Backend (Python)

Parse the cookie from the request:

```python
import json
from urllib.parse import unquote
from fastapi import Request

def get_build_user_persona(request: Request) -> dict | None:
    """Parse build user persona from cookie."""
    cookie_value = request.cookies.get("build_user_persona")
    if not cookie_value:
        return None

    try:
        # URL decode and parse JSON
        decoded = unquote(cookie_value)
        persona = json.loads(decoded)
        return {
            "work_area": persona.get("workArea"),
            "level": persona.get("level")
        }
    except (json.JSONDecodeError, ValueError):
        return None

# Usage in an endpoint
@router.post("/sessions")
def create_session(request: Request):
    persona = get_build_user_persona(request)
    if persona:
        work_area = persona["work_area"]  # "engineering"
        level = persona["level"]           # "ic"
```

## Writing the Cookie

### Frontend (TypeScript/React)

Use the helper function `setBuildUserPersona()`:

```typescript
import { setBuildUserPersona } from "@/app/build/onboarding/constants";

// Set the persona data
setBuildUserPersona({
  workArea: "engineering",
  level: "ic",
});
```

## API Integration

The persona data is automatically included when creating new build sessions:

```typescript
import { createSession } from "@/app/build/services/apiServices";
import { getBuildUserPersona } from "@/app/build/onboarding/constants";

// Parse persona from cookie
const persona = getBuildUserPersona();

// Create session with persona data
const session = await createSession({
  demoDataEnabled: true,
  userWorkArea: persona?.workArea || null,
  userLevel: persona?.level || null,
});
```

The backend receives this in the `SessionCreateRequest`:

```python
class SessionCreateRequest(BaseModel):
    name: str | None = None
    demo_data_enabled: bool = True
    user_work_area: str | None = None  # From cookie
    user_level: str | None = None      # From cookie
```

## Available Options

### Work Areas

- `engineering` - Engineering
- `product` - Product
- `executive` - Executive
- `sales` - Sales
- `marketing` - Marketing
- `other` - Other

### Levels

- `ic` - IC (Individual Contributor)
- `manager` - Manager

Note: Level is only required for certain work areas (engineering, product, sales).
