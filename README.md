# AI receptionist for GoHighLevel

Kestrel Air & Plumbing is a made-up company. All names, emails and phone numbers in this project are synthetic.

Work in progress. The full write-up comes at the end of the project.

## Notes

- The GHL developer sandbox can now create Private Integration Tokens. Older docs said it could not.
- Sandbox API limit: 25 requests per 10 seconds and 10,000 per day, per location.
- The new sub-account had 0 users, so I gave the agency user access to it.
- Channel: GHL web chat. `POST /conversations/messages/inbound` with type `Live_Chat` adds the customer message and `POST /conversations/messages` sends the reply. Both show in the Conversations inbox. No custom provider was needed, and web chat needs no A2P or email setup.
- A Private Integration Token cannot create pipelines (401, scope not authorized). I made the pipeline in the GHL screen and the setup script reads its ids. Steps are in `docs/setup-ghl.md`.
- The create calendar route stored a 2-hour slot as 0.03 hours. I send 120 minutes instead.
- A round robin calendar also applies the user's own working hours, which default to Monday to Friday, so Saturday had no slots. I use an event calendar, which follows only its own open hours.
- n8n cannot run fastembed, so a small container on the n8n server embeds each question (`embed/`, steps in `docs/server.md`). The KB loader and the container use the same model.
- The Postgres credential checks Supabase's certificate. The n8n server trusts Supabase's root CA through `NODE_EXTRA_CA_CERTS` instead of skipping the check.
- Claude Haiku 5.5 takes a forced tool call. Claude Sonnet 5.5 rejects `tool_choice` `tool` with a 400, so for Sonnet the flow sends `auto` with a strict tool schema.
- Strict tool schemas reject an `enum` that lists `null`; the optional `urgency` field uses `anyOf` with a null type.
- In n8n 2.26 the error workflow only runs when it is active, so the deploy script activates both workflows.
- The test scripts play the customer: they store each message in GHL through the API and then call the n8n webhook with the same ids that a GHL workflow webhook would send.
- The n8n retry is a fixed wait (3 s, 4 tries) on every GHL call, not an exponential backoff. With the sandbox limit of 25 requests per 10 s that is enough for one conversation at a time.
- The docs list `Version: v3` for the message routes. `2021-07-28` also works, so I use one version for every call.
