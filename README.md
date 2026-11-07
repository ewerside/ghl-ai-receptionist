# AI receptionist for GoHighLevel

Kestrel Air & Plumbing is a made-up company. All names, emails and phone numbers in this project are synthetic.

Work in progress. The full write-up comes at the end of the project.

## Notes

- The GHL developer sandbox can now create Private Integration Tokens. Older docs said it could not.
- Sandbox API limit: 25 requests per 10 seconds and 10,000 per day, per location.
- The new sub-account had 0 users, so I gave the agency user access to it.
- Channel: GHL web chat. `POST /conversations/messages/inbound` with type `Live_Chat` adds the customer message and `POST /conversations/messages` sends the reply. Both show in the Conversations inbox. No custom provider was needed, and web chat needs no A2P or email setup.
- The docs list `Version: v3` for the message routes. `2021-07-28` also works, so I use one version for every call.
