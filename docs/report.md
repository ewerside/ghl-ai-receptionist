# Evaluation report

I ran the 50 synthetic conversations in `data/conversations.jsonl` through the live flow (GHL sandbox, n8n, Claude), once per model, with the demo data reset before each run. The answer key is `data/expected.csv`. Every number below comes from `scripts/report.py` over the files in `data/runs/`.

After these runs, a code review led me to add the slot reservation in Postgres, the record that a reply was sent, and the guard that asks for the ZIP code before offering times. I did not rerun the 50 conversations after those changes. I reran the 5-conversation smoke test (5 of 5 right) and the 4 reliability tests below.

## Results

| Metric | claude-haiku-5-5 | claude-sonnet-5-5 |
|---|---|---|
| Booking right (booked when it should, not when it should not) | 50 of 50 (100%) | 50 of 50 (100%) |
| Final pipeline stage right | 49 of 50 (98%) | 50 of 50 (100%) |
| Intent right (last turn) | 49 of 50 (98%) | 49 of 50 (98%) |
| Tier right (where the rule sets one) | 37 of 37 (100%) | 36 of 37 (97%) |
| Duplicate slots in the calendar | 0 (14 events) | 0 (14 events) |
| Out-of-area bookings | 0 | 0 |
| Handoff precision | 6 of 6 (100%) | 6 of 6 (100%) |
| Handoff recall | 6 of 6 (100%) | 6 of 6 (100%) |
| Conversations with an invented claim (Claude judge) | 2 (2 of 81 replies) | 1 (1 of 81 replies) |
| Turns where the fixed rule took over | 0 of 81 | 0 of 81 |
| Cost per conversation | $0.0010 | $0.0206 |
| Median time in the flow per reply | 5.7 s | 8.0 s |
| Median time per reply, end to end | 6.3 s | 8.5 s |

## Acceptance

claude-haiku-5-5: 4 of 5 checks pass.
- pass: booking right in 45 of 50 or more
- pass: 0 duplicate slots
- pass: 0 out-of-area bookings
- pass: handoff recall 90% or more
- FAIL: at most 1 invented claim in 50 conversations

claude-sonnet-5-5: 5 of 5 checks pass.
- pass: booking right in 45 of 50 or more
- pass: 0 duplicate slots
- pass: 0 out-of-area bookings
- pass: handoff recall 90% or more
- pass: at most 1 invented claim in 50 conversations

## Default model

Rule: the cheapest model that passes every acceptance check. That is **claude-sonnet-5-5** at $0.0206 per conversation.

claude-haiku-5-5 costs $0.0010 per conversation and is faster (5.7 s per reply), but it had 2 conversations with an invented claim, and the limit is 1.

## Errors

### claude-haiku-5-5

- c19 (repair): intent question, expected book_service; stage New Lead, expected Qualified

What the judge flagged (its words, not the reply):

- c32 turn 1: The office team will need the date of last week's repair and the charges the customer sees.
- c29 turn 2: Customers can call the company right away about a sewer backup or multiple drains backing up. The help center gives no phone line, and it says visits are not booked outside the service area.

### claude-sonnet-5-5

- c07 (emergency): intent book_service, expected emergency; tier warm, expected hot

What the judge flagged (its words, not the reply):

- c40 turn 1: Our careers page doesn't list apprentice roles specifically (the help center doesn't mention a careers page or say anything about apprentice roles).

## Hand check of the judge

I read 10 replies picked at random (seed 42) against the FAQ. My verdict matched the judge on 10 of 10.

| Reply | Judge | Me | Note |
|---|---|---|---|
| c44 turn 1 | ok | ok | fee and waiver match the diagnostic fee article |
| c14 turn 2 | ok | ok | ZIP check and fee are right |
| c11 turn 2 | ok | ok | 1 hour, 3 options and the 24 hour change rule are right |
| c17 turn 1 | ok | ok | repair range and warranty are right |
| c09 turn 2 | ok | ok | no business facts beyond the free estimate |
| c13 turn 1 | ok | ok | furnace price and financing threshold are right |
| c49 turn 1 | ok | ok | plan price and benefits are right |
| c45 turn 1 | ok | ok | warranty text is right |
| c10 turn 1 | ok | ok | prices and what is included are right |
| c02 turn 2 | ok | ok | no invented fact, but it repeats the today or tomorrow rule while offering Tuesday (Monday was full); it also cites the booking page by a shortened title |

## Reliability

`scripts/reliability_test.py` breaks one thing at a time on the live flow and puts it back afterwards. Result: 4 of 4 tests pass, 0 lost messages, 0 duplicate replies.

| Test | Expected | What happened | Pass |
|---|---|---|---|
| Invalid Claude API key | fixed rule scores the lead, one reply, task for a person, card in Needs Human | used_fallback=True, outcome handoff, stage Needs Human, score 80 (hot), replies sent 1 | yes |
| GHL API answers with errors (invalid token) | event saved to failed_events, replay finishes it, one reply | first run: status failed, 1 event queued; after replay: status done, 0 left in queue, replies sent 1 | yes |
| Offered time taken before the customer confirms | no booking on the taken time, the agent offers the next open time | first turn offer_slots; after the time was taken: offer_slots, events at 12:00: 1, events for this customer: 0. | yes |
| Same message delivered twice at the same moment | one run answers, the other stops as duplicate, one reply | answers ['done', 'duplicate'], replies sent 1 | yes |

In the taken-time test, the time had already dropped off the open list, so the guard in `Decide` caught it. The Postgres reservation and `Recheck slot` cover the seconds between those two steps.

## First run and what I changed

The first full run found real problems, so I fixed them and ran all 50 conversations again with both models. The first run is kept in `data/runs-1/`.

| First run | claude-haiku-5-5 | claude-sonnet-5-5 |
|---|---|---|
| Booking right | 50 of 50 (100%) | 50 of 50 (100%) |
| Intent right | 44 of 50 (88%) | 48 of 50 (96%) |
| Conversations with an invented claim | 5 | 2 |

Changes:

- The FAQ now states that any question the chat cannot answer, and any request for a person, goes to the office team, who reply within 1 business day. The prompt already promised this, but only billing questions had it in the FAQ.
- The maintenance plan article title says "maintenance plan", so a question with those words finds it.
- The ZIP guard now turns every out-of-area conversation into a decline with intent out_of_area, not only the ones where the AI tried to offer times.
- The prompt says not to add rules, limits or advice the articles do not state.
- The eval reads the final pipeline stage 30 s after the last conversation. In the first run it read it right away, before GHL's opportunity search had caught up, so some stages showed the value from the turn before.

## How the numbers are counted

- Booking right: the conversation reached a booked visit if and only if the answer key says it should.
- Intent and tier: the values the agent recorded on the last turn of the conversation.
- Handoff: any turn that sent the conversation to a person. Recall is over the 6 conversations that should go to a person.
- Invented claims: Claude Sonnet 5.5 reads every reply next to all 25 FAQ articles and lists business facts the articles do not support. Visit times from the calendar do not count. The judge is the same model as one of the two candidates, so I also checked 10 replies by hand (above).
- Cost: the token counts from each Claude call at list prices. GHL, n8n and the embedding service add no per-call cost.
- Time in the flow: from the webhook call to the logged turn, measured inside n8n. End to end also counts storing the message in GHL and the network.
