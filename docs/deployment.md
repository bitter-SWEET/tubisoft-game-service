# Restricted beta deployment

Tubisoft is a standalone Python service with a private SQLite/key volume. The observed game workflow is playable, but the legacy protocol and incomplete session authentication are unsuitable for an unrestricted public registration service. Limit the beta to intended testers.

## Configuration and ports

Copy `.env.example` to the ignored `.env`, set its permissions to 0600, and replace its example values. `TUBISOFT_ADVERTISE_IP` must be the IPv4 address reachable by the games, not a wildcard/container address. `TUBISOFT_ALLOWED_CIDRS` is a comma-separated list of tester public `/32` addresses, trusted LANs, or VPN ranges. Both router TCP connections and NAT discovery use that allowlist. Moving the files to another machine requires its own environment and fresh runtime secrets.

| Listener | Role | Sharing plan |
| --- | --- | --- |
| TCP 80 | Retail bootstrap | Existing HTTP proxy forwards only `/gsinit.php` to loopback 18080. |
| TCP/UDP 30000 | Router, lobby, host reliable UDP | Tubisoft listener; allow tester sources. |
| TCP 30001 | Launcher/registration | Tubisoft listener; allow tester sources. |
| UDP 30002 | NAT discovery/probe | Tubisoft listener; allow tester sources. |
| UDP 53 and TCP 443 | Existing DNS and DNAS | Reuse the platform setup; Tubisoft does not bind either. |
| Host game UDP, commonly 7777 | Direct peer gameplay | Runs on the player PC/PS2, not the VPS. Guest ports may be dynamic. |

The Compose image runs as UID/GID 10001 with a read-only root, no added capabilities, a temporary `/tmp`, bounded logs, and persistent `/state`. The service creates `/state/accounts.sqlite3` and `/state/router-private.pem` with private file permissions. Log addresses are replaced by per-process peer IDs; IDs intentionally change on restart. Do not publish raw infrastructure/proxy logs.

There are connection/concurrency and authentication-attempt limits; password hashing is offloaded with a bounded worker semaphore. These do not replace firewall restrictions. UDP host state and the NAT helper are bounded but do not implement every original SDK reliability/error branch.

## Start and inspect

```sh
docker compose --env-file .env config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 game-service
curl --noproxy '*' 'http://127.0.0.1:18080/healthz'
curl --noproxy '*' 'http://127.0.0.1:18080/gsinit.php?dp=XIIIPS2US'
```

Use the existing HTTP server and [bootstrap location](../deploy/nginx-bootstrap.conf) rather than replacing its configuration. Test the existing TSFP site and DNAS afterward. Keep the existing TSFP DNS responder and add only the Ubisoft bootstrap hostname to its redirect configuration. The operator must verify those integration changes against the actual host before enabling them.

A second emulator must resolve `gsconnect.ubisoft.com` to this service and complete the existing DNAS path. PCSX2 DHCP DNS settings require automatic DNS in the saved PS2 profile; see [the tester guide](local-test.md).

## Backup and restore

Account creation and successful login update SQLite; rooms, membership, and handoffs are intentionally transient. Passwords use per-account random salt and scrypt with N=16384, r=8, p=1, 32-byte output. The schema stores case-folded/display names, password salt/hash, creation time, and last successful login time. It stores no email or client address. Legacy schema-zero databases are migrated in place without changing names, salts, or password hashes; unknown future versions are refused.

Create a consistent snapshot while the service runs, including committed WAL state:

```sh
docker compose exec game-service tubisoft-admin backup \
  --database /state/accounts.sqlite3 --output /state/backups/accounts-YYYYMMDD.sqlite3
mkdir -m 700 -p ../tubisoft-private-backups
docker compose cp game-service:/state/backups/accounts-YYYYMMDD.sqlite3 ../tubisoft-private-backups/
chmod 600 ../tubisoft-private-backups/accounts-YYYYMMDD.sqlite3
```

Create `private-backups` outside the checkout with mode 0700 and the copied snapshot with mode 0600. Store a copy off-host. The command refuses to overwrite an existing destination. Test restoration on an isolated container before relying on the backup. Preserve the router key in private backups as well; it is never part of a release archive.

To restore or import a legacy database: stop Tubisoft, preserve the current volume and a fresh snapshot, restore the database into the volume as UID/GID 10001 with mode 0600, remove stale WAL/SHM sidecars only while stopped, then start the service and verify login. Do not place a live SQLite file in a release checkout or copy the old lab accounts into the public repository. Do not remove the volume with `down -v` during upgrades.

## Updating and rollback

The repository includes CI for tests, publication audit, and image build. It intentionally has no automatic VPS deployment or shared TSFP infrastructure mutations. Deploy an audited commit, back up state first, and retain the previous image/configuration. A rollback must retain the account/key volume and use a compatible schema; do not overwrite newer account state with an old release's files.

For a shared VPS, first inspect current listeners, container names, memory/disk headroom, firewall, HTTP proxy, and DNS backend. Reserve Tubisoft's ports and a separate volume/project. Do not restart TSFP, replace DNS/DNAS, alter existing databases, or copy its credentials into Tubisoft. Separate-network peer gameplay is still a beta acceptance test even if all VPS service ports respond.

## Publication boundary

Only source, synthetic tests, deployment templates, tooling, and sanitized research notes belong in Git. `work`, account databases/backups, `.env`, keys/certificates, captures/logs, disc/overlay contents, memory cards, and generated disassembly/decompilation stay private. `.dockerignore` also prevents those files entering the build context. Run `python tools/publication_audit.py --git` in the clean publication checkout before each push. Review the staged file list and the commit's author identity too.
