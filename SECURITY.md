# Security

These applications are local research tools, not hardened multi-user services.
Keep the API App bound to loopback; do not expose it directly to the Internet.
Use narrowly scoped database users and your own provider credentials.

Never put credentials, database dumps, or complete provider responses in issues
or pull requests. If a credential is exposed, revoke or rotate it first; deleting
the latest file does not remove it from Git history or existing clones.

Report security concerns to the repository owner privately, with redacted steps
and affected component/version. Do not publish a working secret or exploit against
someone else's instance. Supply synthetic fixtures instead of personal data.
