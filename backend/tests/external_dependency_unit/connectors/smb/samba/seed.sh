#!/bin/bash
# Loads the users, the groups and the fixed part of the fixture tree. The
# tests write the files they change into their own folders.
set -euo pipefail

PASSWORD="${SMB_TEST_PASSWORD:-Onyx-Test-Passw0rd}"
SHARE_PATH="${SMB_TEST_SHARE_PATH:-/srv/plans}"
MAIL_DOMAIN="${SMB_TEST_MAIL_DOMAIN:-onyx.test}"

# The directory service takes a few seconds to answer after Samba starts.
for _ in $(seq 1 60); do
    if samba-tool user list >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
samba-tool user list >/dev/null

# The service account the connector signs in with: a plain domain user.
samba-tool user create svc-onyx "${PASSWORD}"
for user in alice bob carol dave; do
    samba-tool user create "${user}" "${PASSWORD}" \
        --mail-address="${user}@${MAIL_DOMAIN}"
done
# A disabled account gets no access.
samba-tool user disable dave

samba-tool group add Engineering
samba-tool group add Backend
samba-tool group add Restricted
# alice is in Engineering only through the nested group.
samba-tool group addmembers Backend alice
samba-tool group addmembers Engineering Backend,bob
samba-tool group addmembers Restricted carol,dave

# Tests make their own folders here as the administrator.
mkdir -p "${SHARE_PATH}/Fixtures/NoAccess" "${SHARE_PATH}/Fixtures/Loop"
echo "secret" > "${SHARE_PATH}/Fixtures/NoAccess/secret.txt"
echo "fixture" > "${SHARE_PATH}/Fixtures/readme.txt"
# A link to the folder above it. Samba follows it on the server and shows a
# plain folder, so a walk without a depth limit never ends.
ln -sfn .. "${SHARE_PATH}/Fixtures/Loop/again"

# Authenticated Users: read. Administrators: full control. Children inherit.
samba-tool ntacl set "O:BAG:DUD:PAI(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;AU)" \
    "${SHARE_PATH}"
samba-tool ntacl set "O:BAG:DUD:PAI(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;AU)" \
    "${SHARE_PATH}/Fixtures"
# Only administrators may open this folder: the service account cannot list it.
samba-tool ntacl set "O:BAG:DUD:PAI(A;OICI;FA;;;BA)" \
    "${SHARE_PATH}/Fixtures/NoAccess"
