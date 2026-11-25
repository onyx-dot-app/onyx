# A Samba Active Directory domain controller that also serves one file share.
# For the Windows file share (SMB) connector tests only.
FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        samba samba-ad-dc samba-ad-provision samba-dsdb-modules \
        samba-vfs-modules winbind krb5-user openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh seed.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/seed.sh

# SMB, Kerberos, LDAP with StartTLS, LDAPS.
EXPOSE 445 88 88/udp 389 636

HEALTHCHECK --interval=5s --timeout=3s --retries=60 \
    CMD test -f /var/lib/samba/.seeded

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
