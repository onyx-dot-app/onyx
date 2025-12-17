# License Infrastructure

Data plane infrastructure for cryptographic license verification and storage.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Control Plane  │────▶│   Data Plane    │────▶│     Redis       │
│ (signs license) │     │ (verifies sig)  │     │   (caches)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │   PostgreSQL    │
                        │ (license table) │
                        └─────────────────┘
```

## License Format

A license is a base64-encoded JSON containing a payload and RSA-4096 signature:

```python
class LicensePayload(BaseModel):
    version: str
    tenant_id: str
    organization_name: str | None
    issued_at: datetime
    expires_at: datetime
    seats: int
    plan_type: PlanType  # monthly | annual
    grace_period_days: int = 30
    stripe_subscription_id: str | None
    stripe_customer_id: str | None

class LicenseData(BaseModel):
    payload: LicensePayload
    signature: str  # base64-encoded RSA signature
```

## Database

Single `license` table using singleton pattern (only one row, enforced by unique index):

```sql
CREATE TABLE license (
    id INTEGER PRIMARY KEY,
    license_data TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE UNIQUE INDEX idx_license_singleton ON license ((true));
```

## Redis Cache

License metadata cached for 24 hours to avoid repeated DB + crypto verification:

```python
class LicenseMetadata(BaseModel):
    tenant_id: str
    seats: int
    used_seats: int  # computed on cache refresh
    plan_type: PlanType
    expires_at: datetime
    status: str  # ACTIVE | GRACE_PERIOD | GATED_ACCESS
    source: LicenseSource  # auto_fetch | manual_upload
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/license` | GET | Get current license status |
| `/license/seats` | GET | Get seat usage details |
| `/license/fetch` | POST | Pull license from control plane |
| `/license/upload` | POST | Manual file upload (air-gapped) |
| `/license/refresh` | POST | Force cache refresh |
| `/license` | DELETE | Remove license |

## Status States

| Status | Meaning |
|--------|---------|
| `ACTIVE` | License valid, not expired |
| `GRACE_PERIOD` | Expired but within grace period (default 30 days) |
| `GATED_ACCESS` | Expired and grace period ended |

## Seat Counting

- **Multi-tenant**: Uses `get_tenant_count()` for the tenant
- **Self-hosted**: Counts active users in the `User` table
