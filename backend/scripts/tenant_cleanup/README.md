## How to Tenant Cleanup

Three main steps.

### Build a list of tenants to cleanup

Use the `analyze_current_tenants.py` script:

```
PYTHONPATH=. \
CONTROL_PLANE_RDS_HOST=<PROD_CONTROL_PLANE_RDS_HOST> \
CONTROL_PLANE_RDS_PASSWORD=<PROD_CONTROL_PLANE_RDS_PASSWORD> \
BASTION_HOST=<BASTION_IP_ADDRESS> \
PEM_FILE_LOCATION=<PEM_FILE_LOCATION_WHICH_GIVES_ACCESS_TO_BASTION> \
python scripts/tenant_cleanup/analyze_current_tenants.py
```

This will create a `.csv` called something like `gated_tenants_no_query_3mo_20251012_161102.csv` in the `backend` dir.


### Delete all documents within these tenants

Use the `mark_connectors_for_deletion.py` script:

```
PYTHONPATH=. \
CONTROL_PLANE_RDS_HOST=<PROD_CONTROL_PLANE_RDS_HOST> \
CONTROL_PLANE_RDS_PASSWORD=<PROD_CONTROL_PLANE_RDS_PASSWORD> \
BASTION_HOST=<BASTION_IP_ADDRESS> \
PEM_FILE_LOCATION=<PEM_FILE_LOCATION_WHICH_GIVES_ACCESS_TO_BASTION> \
python scripts/tenant_cleanup/mark_connectors_for_deletion.py --csv gated_tenants_no_query_3mo_<your_datetime>.csv --force
```

Replace `gated_tenants_no_query_3mo_<your_datetime>.csv` with the CSV name from step (1).

This will update the data plane database to 1/ cancel all index attempts 2/ mark all connectors as up for deletion.
We now need to wait for the deletion to run.

It's done this way to re-use as much of the existing code + take advantage of existing infra for parallelized, long running jobs. These 
deletion jobs can take a LONG time (>6hrs), so having it performed syncronously by a script is not really tenable.


### Cleanup the tenants

Use the `cleanup_tenants.py` script:

```
PYTHONPATH=. \
CONTROL_PLANE_RDS_HOST=<PROD_CONTROL_PLANE_RDS_HOST> \
CONTROL_PLANE_RDS_PASSWORD=<PROD_CONTROL_PLANE_RDS_PASSWORD> \
BASTION_HOST=<BASTION_IP_ADDRESS> \
PEM_FILE_LOCATION=<PEM_FILE_LOCATION_WHICH_GIVES_ACCESS_TO_BASTION> \
python scripts/tenant_cleanup/cleanup_tenants.py --csv gated_tenants_no_query_3mo_<your_datetime>.csv --force
```

This will drop the tenant schema from the data plane DB, cleanup the `user_tenant_mapping` table, and 
clean up any control plane DB tables associated with each tenant.

NOTE: if the previous step has not completed, tenants with documents will throw an exception.
