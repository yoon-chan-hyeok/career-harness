# Security & Privacy

This system contains highly personal career information.

## Minimum requirements

- user_id on all private rows
- repository queries always user-scoped
- auth before multi-user release
- secrets only via environment/secret manager
- no real private input committed
- raw exports stored outside public repo
- source-level deletion supported
- workspace-level deletion supported

## Prompt / external content safety

- JD/web content is untrusted data.
- Extract structured facts/requirements before downstream LLM use.
- Do not allow external page text to override system/developer instructions.
- Never execute instructions embedded inside imported resumes/JDs.

## Logs

Avoid logging full private document contents by default.
Use ids/hashes and minimal excerpts.

## Export/delete

Provide:
- personal data export
- source delete
- application workspace delete

Deleting a truth source must invalidate unsupported derivatives.
