#!/bin/bash
# Provisions the domain on the first start, then runs Samba and seeds it.
set -euo pipefail

REALM="${SMB_TEST_REALM:-ONYX.TEST}"
DOMAIN="${SMB_TEST_DOMAIN:-ONYXTEST}"
HOST_NAME="${SMB_TEST_HOST_NAME:-dc1}"
ADMIN_PASSWORD="${SMB_TEST_PASSWORD:-Onyx-Test-Passw0rd}"
SHARE_PATH="${SMB_TEST_SHARE_PATH:-/srv/plans}"
TLS_DIR=/etc/samba/tls
CERT_EXPORT_DIR="${SMB_TEST_CERT_EXPORT_DIR:-/certs}"
FQDN="${HOST_NAME}.${REALM,,}"

if [ ! -f /var/lib/samba/private/sam.ldb ]; then
    rm -f /etc/samba/smb.conf
    # xattr_tdb keeps NT access lists in a database, so the share works on a
    # file system without extended attributes.
    samba-tool domain provision \
        --realm="${REALM}" \
        --domain="${DOMAIN}" \
        --server-role=dc \
        --dns-backend=SAMBA_INTERNAL \
        --adminpass="${ADMIN_PASSWORD}" \
        --host-name="${HOST_NAME}" \
        --option="vfs objects = dfs_samba4 acl_xattr xattr_tdb"

    # Samba's own certificate has no authority key identifier, which Python
    # 3.13 refuses. Issue one from a test authority.
    mkdir -p "${TLS_DIR}"
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -keyout "${TLS_DIR}/ca.key" -out "${TLS_DIR}/ca.pem" \
        -subj "/CN=Onyx SMB Test CA" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign"
    openssl req -newkey rsa:2048 -nodes \
        -keyout "${TLS_DIR}/dc.key" -out "${TLS_DIR}/dc.csr" -subj "/CN=${FQDN}"
    cat > "${TLS_DIR}/dc.ext" <<EXT
subjectAltName=DNS:${FQDN},DNS:${HOST_NAME},DNS:localhost,IP:127.0.0.1
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
authorityKeyIdentifier=keyid
subjectKeyIdentifier=hash
EXT
    openssl x509 -req -in "${TLS_DIR}/dc.csr" -CA "${TLS_DIR}/ca.pem" \
        -CAkey "${TLS_DIR}/ca.key" -CAcreateserial -days 3650 \
        -out "${TLS_DIR}/dc.pem" -extfile "${TLS_DIR}/dc.ext"
    chmod 600 "${TLS_DIR}/dc.key" "${TLS_DIR}/ca.key"

    # Active Directory takes a Kerberos bind with no signing layer on a TLS
    # connection. Samba needs this setting to do the same.
    sed -i "s|^\[global\]|[global]\n\ttls enabled = yes\n\ttls keyfile = ${TLS_DIR}/dc.key\n\ttls certfile = ${TLS_DIR}/dc.pem\n\ttls cafile = ${TLS_DIR}/ca.pem\n\tldap server require strong auth = allow_sasl_over_tls|" \
        /etc/samba/smb.conf
    mkdir -p "${SHARE_PATH}"
    cat >> /etc/samba/smb.conf <<CONF

[plans]
	path = ${SHARE_PATH}
	read only = no
	vfs objects = acl_xattr xattr_tdb
CONF
fi

# The tests trust the domain controller through this certificate.
if [ -d "${CERT_EXPORT_DIR}" ]; then
    cp "${TLS_DIR}/ca.pem" "${CERT_EXPORT_DIR}/ca.pem"
    chmod 644 "${CERT_EXPORT_DIR}/ca.pem"
fi

samba --foreground --no-process-group &
samba_pid=$!

if [ ! -f /var/lib/samba/.seeded ]; then
    "$(dirname "$0")/seed.sh"
    touch /var/lib/samba/.seeded
fi

wait "${samba_pid}"
