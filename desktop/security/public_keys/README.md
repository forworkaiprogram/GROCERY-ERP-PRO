# Embedded cloud public keys

`cloud_ed25519.pub` in this directory is the Ed25519 **public** verification
key the EXE embeds. It is provisioned at build time by
`scripts/generate_signing_keys.py` from the keys generated on the release
server. **Never place a private key here** (the product rule: the private
update/entitlement signing keys never leave the cloud).

If this file is missing, update verification and entitlement snapshot
verification fail closed — ships without it are rejected.
