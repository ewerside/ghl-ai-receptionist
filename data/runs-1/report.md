# Evaluation report

I ran the 50 synthetic conversations in `data/conversations.jsonl` through the live flow (GHL sandbox, n8n, Claude), once per model, with the demo data reset before each run. The answer key is `data/expected.csv`. Every number below comes from `scripts/report.py` over the files in `data/runs/`.

## Results

| Metric | claude-haiku-5-5 | claude-sonnet-5-5 |
|---|---|---|
| Booking right (booked when it should, not when it should not) | 50 of 50 (100%) | 50 of 50 (100%) |
| Final pipeline stage right | 46 of 50 (92%) | 43 of 50 (86%) |
| Intent right (last turn) | 44 of 50 (88%) | 48 of 50 (96%) |
| Tier right (where the rule sets one) | 37 of 37 (100%) | 36 of 37 (97%) |
| Duplicate slots in the calendar | 0 (14 events) | 0 (14 events) |
| Out-of-area bookings | 0 | 0 |
| Handoff precision | 6 of 7 (86%) | 6 of 7 (86%) |
| Handoff recall | 6 of 6 (100%) | 6 of 6 (100%) |
| Conversations with an invented claim (Claude judge) | 5 (5 of 81 replies) | 2 (2 of 81 replies) |
| Turns where the fixed rule took over | 0 of 81 | 0 of 81 |
| Cost per conversation | $0.0010 | $0.0205 |
| Median time in the flow per reply | 5.9 s | 8.1 s |
| Median time per reply, end to end | 6.7 s | 8.8 s |

## Acceptance

claude-haiku-5-5: 4 of 5 checks pass.
- pass: booking right in 45 of 50 or more
- pass: 0 duplicate slots
- pass: 0 out-of-area bookings
- pass: handoff recall 90% or more
- FAIL: at most 1 invented claim in 50 conversations

claude-sonnet-5-5: 4 of 5 checks pass.
- pass: booking right in 45 of 50 or more
- pass: 0 duplicate slots
- pass: 0 out-of-area bookings
- pass: handoff recall 90% or more
- FAIL: at most 1 invented claim in 50 conversations

## Errors

### claude-haiku-5-5

- c30 (out_of_area): intent book_service, expected out_of_area
- c49 (question): stage Needs Human, expected New Lead
- c19 (repair): intent question, expected book_service; stage New Lead, expected Qualified
- c28 (out_of_area): intent install_quote, expected out_of_area
- c27 (out_of_area): intent question, expected out_of_area
- c48 (question): stage None, expected New Lead
- c03 (emergency): stage Qualified, expected Booked
- c29 (out_of_area): intent book_service, expected out_of_area
- c26 (out_of_area): intent book_service, expected out_of_area

Replies the judge flagged:

- c31 turn 0: We cover "nearby ZIP codes" beyond Austin, Round Rock, Pflugerville and Cedar Park. The help center says visits are booked only in the listed ZIP codes and no others.
- c49 turn 0: The office team will reply to the maintenance plan question within 1 business day. The help center gives that response time only for questions about a bill, a refund or a complaint.
- c09 turn 1: The free in-home estimate includes the city permit and haul-away of the old equipment. The help center says the installed price includes the permit and haul-away, not the free estimate visit.
- c03 turn 1: Until we arrive, avoid running water and flushing toilets (attributed to the "How do I book a visit?" page, which has no such guidance)
- c29 turn 0: Today is not possible for a simple clogged drain because it is a regular repair visit rather than an emergency.

### claude-sonnet-5-5

- c49 (question): stage Needs Human, expected New Lead
- c44 (question): stage None, expected New Lead
- c19 (repair): intent question, expected book_service; stage New Lead, expected Qualified
- c07 (emergency): intent book_service, expected emergency; tier warm, expected hot
- c11 (install_owner): stage Qualified, expected Booked
- c47 (question): stage None, expected New Lead
- c37 (handoff): stage None, expected Needs Human
- c35 (handoff): stage None, expected Needs Human

Replies the judge flagged:

- c49 turn 0: A team member from the office will follow up within 1 business day. The help center gives the 1-business-day reply time only for bill, refund and complaint questions, not for questions about maintenance plans.
- c34 turn 0: A team member will reply within 1 business day. The help center gives this reply time only for questions about a bill, a refund or a complaint, and the customer asked only to talk to a person.

## How the numbers are counted

- Booking right: the conversation reached a booked visit if and only if the answer key says it should.
- Intent and tier: the values the agent recorded on the last turn of the conversation.
- Handoff: any turn that sent the conversation to a person. Recall is over the 6 conversations that should go to a person.
- Invented claims: Claude Sonnet 5.5 reads every reply next to all 25 help center articles and lists business facts the articles do not support. Visit times from the calendar do not count.
- Cost: the token counts from each Claude call at list prices. GHL, n8n and the embedding service add no per-call cost.
- Time in the flow: from the webhook call to the logged turn, measured inside n8n. End to end also counts storing the message in GHL and the network.
