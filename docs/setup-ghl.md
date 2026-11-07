# GoHighLevel setup

What I set up by hand in the GHL screens, and what `scripts/setup_ghl.py` does through the API. Follow these steps in order to rebuild the demo sub-account.

## 1. Developer account and sandbox (by hand)

1. Sign up at marketplace.gohighlevel.com.
2. Top menu: **Testing** > **+ Create app test account**. Name: `Kestrel Demo Agency`. Pick a password and click **Create**.
3. Log in to app.gohighlevel.com with the test account.

## 2. Sub-account (by hand)

1. **Sub-Accounts** > **Create New** > **Regular Account** > **Blank snapshot** > **Add Manually**.
2. Fill in synthetic data only:
   - Name: Dana Reyes, email `office@kestrel.example.com`, phone +1 512-555-0100
   - Business name: `Kestrel Air & Plumbing (demo)`
   - Address: 100 Example Way, Austin, TX 78701, United States
   - Time zone: `America/Chicago`
3. Turn off **Include sample data in this sub-account**, keep **This is my client's account** and click **Add Sub-Account**.
4. Agency **Settings** > **Users** > edit the agency user > **Roles & permissions** > **Add sub-accounts**: add the Kestrel sub-account and save. Without this the sub-account has 0 users, and the agent has no one to assign tasks to.

## 3. Private Integration Token (by hand)

1. In the sub-account: **Settings** > **Private Integrations** > **Create new integration**.
2. Name: `ghl-ai-receptionist`. Click **Next**.
3. Scopes (18): `locations.readonly`, `users.readonly`, `contacts.readonly`, `contacts.write`, `conversations.readonly`, `conversations.write`, `conversations/message.readonly`, `conversations/message.write`, `calendars.readonly`, `calendars.write`, `calendars/events.readonly`, `calendars/events.write`, `opportunities.readonly`, `opportunities.write`, `locations/customFields.readonly`, `locations/customFields.write`, `locations/tags.readonly`, `locations/tags.write`.
4. Click **Create**, copy the token and put it in `.env` as `GHL_TOKEN`. Put the sub-account id (it is in the URL after `/location/`) in `GHL_LOCATION_ID`.
5. Check: `python scripts/check_env.py` prints the sub-account name and at least 1 user.

## 4. Pipeline (by hand)

A Private Integration Token cannot create pipelines (the API answers 401, scope not authorized), so this one is made in the screen.

1. **Opportunities** > **Pipelines** > **Create pipeline**.
2. Name: `Service Leads`.
3. Stages, in this order, with the win probability:

| Stage | Probability |
|---|---|
| New Lead | 10% |
| Qualified | 40% |
| Booked | 90% |
| Needs Human | 30% |
| Lost | 0% |

4. Click **Create**.

## 5. Everything else (script)

`python scripts/setup_ghl.py` creates what is missing and is safe to run again:

- 7 contact fields: AI Score (number), AI Tier (hot, warm, cold), AI Intent (8 options), AI Reason (long text), Service Type, Zip Code, Urgency (emergency, this_week, flexible).
- 5 tags: `needs-human`, `out-of-area`, `spam`, `job-seeker`, `ai-test`. Every contact the test scripts create gets `ai-test`, so `reset_demo.py` deletes only those.
- Calendar `Service Visit`: event type, Monday to Saturday, 8 am to 6 pm Central, 2-hour visits starting at 8, 10, 12, 14 and 16.

Then it reads the pipeline, checks every id against GHL (including the free slots for the next 8 days) and saves them to `config/ghl_ids.json`.
