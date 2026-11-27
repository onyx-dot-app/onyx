# Windows file share (SMB) connector tests

These tests need a file server and an Active Directory domain. `docker-compose.yml`
starts both in one container: a Samba Active Directory domain controller that
also serves the share `plans`.

Samba does not copy every NTFS behavior. See "What Samba cannot show" below.

## Start the server

Run these commands from this directory.

1. Map the server's name to your machine. LDAP with TLS and Kerberos need the
   name that is in the server's certificate.

   ```bash
   echo "127.0.0.1 dc1.onyx.test" | sudo tee -a /etc/hosts
   ```

2. Build and start the container. The first start provisions the domain and
   loads the fixtures, which takes about one minute.

   ```bash
   mkdir -p .certs && docker compose up -d --build --wait
   ```

The container writes the certificate of its test authority to `.certs/ca.pem`.

3. Install the Kerberos libraries for the Kerberos tests. They compile against
   the MIT Kerberos headers (`libkrb5-dev` on Debian and Ubuntu).

   ```bash
   uv sync --group kerberos
   ```

## Run the tests

Run this command from the repository root.

```bash
uv run pytest backend/tests/external_dependency_unit/connectors/smb
```

The tests need no Postgres and no other Onyx service. Each test writes its
files into its own folder of the share and removes the folder at the end.

## What the server holds

| Item | Value |
| --- | --- |
| File server and domain controller | `dc1.onyx.test` |
| SMB port on your machine | `1445` |
| LDAPS port on your machine | `1636` |
| LDAP port for StartTLS on your machine | `1389` |
| Kerberos port on your machine | `88` |
| Domain | `ONYXTEST` (realm `ONYX.TEST`) |
| Share | `plans` |
| Password of each account | `Onyx-Test-Passw0rd` |
| Administrator | `Administrator` |
| Service account for the connector | `svc-onyx` |

`samba/seed.sh` loads these users and groups:

| Principal | Notes |
| --- | --- |
| `alice`, `bob`, `carol` | Users with the mail `<name>@onyx.test`. |
| `dave` | A disabled user. |
| `svc-onyx` | No mail. Its user principal name is its address. |
| `Engineering` | Holds `bob` and the group `Backend`. |
| `Backend` | Holds `alice`. |
| `Restricted` | Holds `carol` and `dave`. |

The share holds the folder `Fixtures`:

- `Fixtures/readme.txt`: a file that each domain user can read.
- `Fixtures/NoAccess`: a folder that only administrators can open.
- `Fixtures/Loop/again`: a link to `Fixtures`, which Samba follows on the server.

To use other ports or another password, set `SMB_TEST_PORT`,
`SMB_TEST_LDAPS_PORT`, `SMB_TEST_LDAP_PORT` or `SMB_TEST_PASSWORD` for
`docker compose` and for `pytest`.

## Connect a local Onyx to the server

1. Start Onyx with the Enterprise Edition enabled, if you want permission sync.
2. Let connectors reach a private address. In the admin panel, open the
   security settings and set the SSRF protection level to **Validate LLM
   Requests** or lower. The loopback address needs the lowest level.
3. If Onyx runs in containers, use a name that reaches your machine from them,
   and add `dc1.onyx.test` for that address to the containers' hosts.
4. Add a **Windows File Share (SMB)** connector with these values:

   | Field | Value |
   | --- | --- |
   | File server | `dc1.onyx.test` |
   | Share | `plans` |
   | Port | `1445` |
   | Domain | `ONYXTEST` |
   | Username | `svc-onyx` |
   | Password | `Onyx-Test-Passw0rd` |

   For Kerberos, select the Kerberos sign-in method and add the realm
   `ONYX.TEST` and the KDC host `dc1.onyx.test`. The SMB port must then be
   `445` on the name `dc1.onyx.test`, because a Kerberos ticket names the
   server and not a port. The backend image holds the Kerberos libraries.

5. For permission sync, add these values to the credential, and turn on
   **Share Permissions Confirmed** on the connector:

   | Field | Value |
   | --- | --- |
   | LDAP host | `dc1.onyx.test` |
   | LDAP port | `1636` |
   | CA certificate | The content of `.certs/ca.pem` |

6. Sign in to Onyx as `alice@onyx.test` or `bob@onyx.test` to see what each
   user can find. The email of an Onyx user must equal the mail of the domain
   user.

To change who can read a file, set its NTFS access list in the container. This
example lets only the group `Engineering` and administrators read a file:

```bash
docker compose exec samba bash -c 'samba-tool ntacl set \
  "O:BAG:DUD:PAI(A;;FA;;;BA)(A;;FR;;;$(samba-tool group show Engineering | sed -n "s/^objectSid: //p"))" \
  /srv/plans/Fixtures/readme.txt'
```

Give the service account read access too, or Onyx cannot read the file.

## Stop the server

```bash
docker compose down -v
```

## What Samba cannot show

Check these on a real Windows Server that is joined to a test domain:

- A rename or a move sets a new change time on NTFS. Samba reports the last
  write time as the change time, so it shows no rename.
- A junction or a symbolic link has the reparse point attribute on NTFS. Samba
  follows a link on the server and shows a plain folder.
- Samba does not keep the offline attributes of tiered storage.
- NTFS copies inherited entries to each child. The tests set each access list
  directly.
- Requests and wall time for each 1,000 files, for the walk, indexing and the
  document permission sync.
