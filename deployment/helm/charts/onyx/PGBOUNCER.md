# PgBouncer Configuration Guide

PgBouncer is a lightweight connection pooler for PostgreSQL that can significantly improve the scalability and performance of your Onyx deployment by reducing the number of direct connections to PostgreSQL.

## Overview

By default, PgBouncer is **disabled** in Onyx. When enabled, all application components (API servers, Celery workers, etc.) connect through PgBouncer instead of directly to PostgreSQL.

### Benefits

- **Reduced Database Load**: Fewer backend connections to PostgreSQL
- **Better Scalability**: Support for more API/worker pods without increasing database connections
- **Connection Reuse**: Faster connection establishment for short-lived queries
- **Resource Efficiency**: Lower memory usage on PostgreSQL server
- **Flexible Deployment**: Enable only when needed, no application code changes required

### How It Works

```
┌─────────────┐
│  API Pods   │─┐
└─────────────┘ │
                │     ┌──────────────┐     ┌──────────────┐
┌─────────────┐ │────▶│  PgBouncer   │────▶│ PostgreSQL   │
│Celery Worker│─┤     │   (1-2 pods) │     │   Cluster    │
└─────────────┘ │     └──────────────┘     └──────────────┘
                │
┌─────────────┐ │
│  Slackbot   │─┘
└─────────────┘
```

When PgBouncer is enabled:
1. Applications connect to PgBouncer (many client connections)
2. PgBouncer maintains a smaller pool of connections to PostgreSQL (fewer server connections)
3. PgBouncer efficiently multiplexes client connections onto server connections

## Enabling PgBouncer

### Basic Configuration

Add to your `values.yaml`:

```yaml
pgbouncer:
  enabled: true
```

That's it! This enables PgBouncer with sensible defaults.

### Advanced Configuration

For production deployments or custom requirements:

```yaml
pgbouncer:
  enabled: true
  replicaCount: 2  # Run 2 PgBouncer instances for HA

  config:
    # Pool mode: transaction (recommended), session, or statement
    poolMode: "transaction"

    # Maximum client connections (total across all databases)
    maxClientConn: 1000

    # Default pool size per database/user
    defaultPoolSize: 25

    # Minimum pool size to maintain
    minPoolSize: 5

    # Additional connections for reserve pool
    reservePoolSize: 5

    # Connection lifetime settings
    serverLifetime: 3600      # Close connections after 1 hour
    serverIdleTimeout: 600    # Close idle connections after 10 minutes

  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
```

## Pool Modes

PgBouncer supports three pool modes:

### Transaction Mode (Recommended)
```yaml
pgbouncer:
  config:
    poolMode: "transaction"
```

**Characteristics:**
- Server connection returned to pool after each transaction
- Best balance of efficiency and compatibility
- Suitable for most applications
- **Limitation**: Does not support prepared statements across transactions

**Use Case**: Production deployments of Onyx (default)

### Session Mode
```yaml
pgbouncer:
  config:
    poolMode: "session"
```

**Characteristics:**
- One server connection per client connection for the session duration
- Full PostgreSQL feature support
- Less efficient connection reuse
- Supports prepared statements

**Use Case**: Applications requiring prepared statements or complex session state

### Statement Mode
```yaml
pgbouncer:
  config:
    poolMode: "statement"
```

**Characteristics:**
- Server connection returned after each statement
- Most restrictive mode
- Breaks multi-statement transactions
- Highest connection reuse

**Use Case**: Read-only workloads with simple queries

## Sizing Recommendations

### Small Deployment (< 10 pods)
```yaml
pgbouncer:
  config:
    maxClientConn: 500
    defaultPoolSize: 15
    minPoolSize: 3
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
```

### Medium Deployment (10-50 pods)
```yaml
pgbouncer:
  config:
    maxClientConn: 1000
    defaultPoolSize: 25
    minPoolSize: 5
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
```

### Large Deployment (50+ pods)
```yaml
pgbouncer:
  replicaCount: 2
  config:
    maxClientConn: 2000
    defaultPoolSize: 50
    minPoolSize: 10
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 1Gi
```

## External PostgreSQL

If using an external PostgreSQL instance (not the bundled PostgreSQL):

```yaml
postgresql:
  enabled: false  # Disable bundled PostgreSQL

pgbouncer:
  enabled: true
  postgresql:
    host: "my-postgres.example.com"
    port: 5432
    database: "onyx"
```

## Monitoring PgBouncer

### Accessing PgBouncer Stats

Connect to PgBouncer admin console:

```bash
# Port-forward to PgBouncer
kubectl port-forward svc/onyx-pgbouncer 5432:5432

# Connect with psql
psql -h localhost -p 5432 -U postgres -d pgbouncer

# View pool stats
SHOW POOLS;

# View client connections
SHOW CLIENTS;

# View server connections
SHOW SERVERS;

# View configuration
SHOW CONFIG;
```

### Key Metrics to Monitor

1. **Pool Saturation**: Check if `cl_waiting > 0` in `SHOW POOLS`
2. **Connection Churn**: Monitor `total_query_count` growth rate
3. **Wait Times**: Check `maxwait` in `SHOW POOLS`
4. **Error Rate**: Look for connection failures in logs

## Troubleshooting

### Issue: "Connection pool exhausted"

**Symptoms**: Applications can't get connections, timeouts

**Solution**: Increase pool size
```yaml
pgbouncer:
  config:
    defaultPoolSize: 50  # Increase from 25
    reservePoolSize: 10  # Increase reserve
```

### Issue: "Prepared statement does not exist"

**Symptoms**: Application errors about missing prepared statements

**Solution**: Switch to session mode
```yaml
pgbouncer:
  config:
    poolMode: "session"
```

Or disable prepared statements in application (PgBouncer transaction mode is generally better).

### Issue: High connection churn

**Symptoms**: PgBouncer logs show many connects/disconnects

**Solution**: Increase server lifetime and adjust pool settings
```yaml
pgbouncer:
  config:
    serverLifetime: 7200     # 2 hours
    serverIdleTimeout: 1200  # 20 minutes
    minPoolSize: 10          # Maintain more connections
```

### Issue: Applications timeout connecting

**Symptoms**: Connection timeouts, slow responses

**Solution**: Increase max client connections or add replicas
```yaml
pgbouncer:
  replicaCount: 2
  config:
    maxClientConn: 2000
```

## Disabling PgBouncer

To disable PgBouncer and return to direct PostgreSQL connections:

```yaml
pgbouncer:
  enabled: false
```

Applications will automatically reconnect directly to PostgreSQL on the next deployment.

## Best Practices

1. **Start with defaults**: Enable PgBouncer with default settings first
2. **Monitor before tuning**: Observe actual connection patterns before adjusting
3. **Use transaction mode**: Best for stateless applications like Onyx
4. **Size PostgreSQL max_connections**: Ensure PostgreSQL `max_connections` > sum of all PgBouncer pool sizes
5. **Run multiple replicas**: Use 2 PgBouncer replicas for production HA
6. **Test failover**: Verify application behavior when PgBouncer pods restart
7. **Watch for prepared statements**: If you see errors, switch to session mode

## Security Considerations

- PgBouncer uses the same PostgreSQL credentials configured in Helm secrets
- Authentication type defaults to `scram-sha-256` (recommended)
- All connections are within the Kubernetes cluster (ClusterIP service)
- For external access, use Kubernetes ingress/load balancer with TLS

## Performance Impact

### With PgBouncer (Transaction Mode)
- **PostgreSQL connections**: ~25 per database (configurable)
- **Client connections**: Up to 1000 (configurable)
- **Connection multiplexing**: ~40:1 ratio
- **Latency overhead**: ~0.1-0.5ms per query

### Without PgBouncer (Direct)
- **PostgreSQL connections**: 1 per application worker/thread
- **Typical connections**: 200-500+ for medium deployments
- **Connection multiplexing**: 1:1
- **Latency overhead**: 0ms

## Additional Resources

- [PgBouncer Documentation](https://www.pgbouncer.org/)
- [Connection Pooling Best Practices](https://www.postgresql.org/docs/current/runtime-config-connection.html)
- [Onyx Helm Chart Documentation](../README.md)
