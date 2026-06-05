# Messaging Setup Guide

Step-by-step guide for wiring this project to the WhatsApp Cloud API: Meta setup, template creation, outbound dispatch, inbound webhook (via ngrok), and the STOP opt-out flow.

---

## Contents

1. [Meta Cloud API setup](#1-meta-cloud-api-setup)
2. [Message templates](#2-message-templates)
3. [Outbound — sending messages](#3-outbound--sending-messages)
   - [Quick test with `test_meta_sender.py`](#3a-quick-test-with-test_meta_senderpy)
   - [Full blast through the API](#3b-full-blast-through-the-api)
4. [Inbound — webhook receiver](#4-inbound--webhook-receiver)
   - [Local dev with ngrok](#4a-local-dev-with-ngrok)
   - [Configuring the webhook in Meta](#4b-configuring-the-webhook-in-meta)
5. [Opt-out flow (STOP keyword)](#5-opt-out-flow-stop-keyword)

---

## 1. Meta Cloud API setup

You need a Meta developer app with the WhatsApp product added.

1. Go to [developers.facebook.com](https://developers.facebook.com) → **My Apps** → **Create App**
2. Choose **Business** as the app type
3. After creation, add the **WhatsApp** product to the app
4. In the WhatsApp setup screen you'll get:
   - A **temporary access token** (24-hour expiry — fine for testing)
   - A **test phone number ID** (e.g. `1096549583541266`)
   - Up to 5 recipient numbers you can verify and message in dev mode

Add a few verified recipients (your own number first) under **API Setup → Recipient phone number → Add phone number**. Meta sends a verification code via WhatsApp.

### Environment variables

Put these in your project's `.env`:

```
WA_ACCESS_TOKEN=EAA...   # the temporary token (or a permanent System User token)
WA_PHONE_NUMBER_ID=1096549583541266
SENDER_MODE=meta         # or "mock" for offline testing
WA_VERIFY_TOKEN=wa_verify_token   # any random string you invent — used by the webhook
```

⚠️ **Never commit `.env`** — it's already in `.gitignore`. Treat `WA_ACCESS_TOKEN` like a password.

---

## 2. Message templates

Meta requires every outbound message to use a **pre-approved template**. There is no free-form outbound — even messaging your own number from your own app requires this.

### Template variables: named vs positional

When you create a template, you choose the variable style. **This must match what your sending code sends in the payload.**

| Style          | Template body                        | Payload format                                                   |
| -------------- | ------------------------------------ | ---------------------------------------------------------------- |
| **Positional** | `Hi {{1}}, your code is {{2}}`       | `[{"type":"text","text":"Alice"}, {"type":"text","text":"ABC"}]` |
| **Named**      | `Hi {{name}}, your code is {{code}}` | `[{"type":"text","parameter_name":"name","text":"Alice"}, ...]`  |

This project uses **named** variables. See [Pipeline/messaging/constructor.py](Pipeline/messaging/constructor.py) and [Pipeline/messaging/meta_sender.py](Pipeline/messaging/meta_sender.py) for how the payload is built.

### Creating the `reengagement_promo` template

In Meta Business Manager → WhatsApp → Message Templates → **Create Template**:

| Field         | Value                             |
| ------------- | --------------------------------- |
| Name          | `reengagement_promo`              |
| Category      | **Marketing**                     |
| Language      | English (US) — language code `en` |
| Body          | (see below)                       |
| Variable type | Name                              |

**Body:**

```
Hi {{name}}, we miss you!

It's been a while since your last visit.
Here's a personal offer just for you: {{promo_value}}.

Use code {{promo_code}} - valid for {{expiry_days}} days.

See you soon!

_To unsubscribe from promotional messages, reply *STOP* at any time_
```

Add **Variable Samples** for each variable (e.g. `Samuel`, `20% off your next order`, `BACK20`, `30`). Meta uses these to review the template.

Submit for approval. Marketing templates typically clear in minutes to a few hours.

### WABA scope (important gotcha)

Templates are scoped to the WhatsApp Business Account (WABA) tied to your phone number. **A template created in WABA A cannot be used by a phone number from WABA B.** If you switch to a different test number or business number, recreate the template under that WABA's app.

---

## 3. Outbound — sending messages

The outbound path is fully wired in this project. Two ways to trigger a send:

- **[`test_meta_sender.py`](#3a-quick-test-with-test_meta_senderpy)** — single message to one customer from a tiny test fixture; ideal for verifying templates and connectivity
- **[`POST /blast/send`](#3b-full-blast-through-the-api)** — full blast through the FastAPI server with DB persistence and cooldown/opt-out filtering

Prerequisites for both:

- `.env` has `SENDER_MODE=meta`, a valid `WA_ACCESS_TOKEN`, and `WA_PHONE_NUMBER_ID`
- The recipient's number is verified in your Meta app (required in Development mode)
- The template you reference (`reengagement_promo` by default) is **approved** under the WABA tied to your phone number

### 3a. Quick test with `test_meta_sender.py`

This is a dev script ([test_meta_sender.py](test_meta_sender.py) at the repo root) that exercises the whole outbound path end-to-end, but only sends to **one** customer. Use it to confirm your access token, phone number ID, template, and message construction all line up before running a real blast.

**What it does (in order):**

1. Loads customers from `Pipeline/test_transactions.csv` (a tiny test fixture, not the real dataset)
2. Runs `analyze()` to score them and pick the at-risk list
3. Takes the **first** at-risk customer
4. Assigns a promo via [Pipeline/promo/mapping.py](Pipeline/promo/mapping.py)
5. Constructs the message via [Pipeline/messaging/constructor.py](Pipeline/messaging/constructor.py)
6. Runs `validate_message` — aborts if any template parameter is empty or the body exceeds 1024 chars
7. Sends via [Pipeline/messaging/meta_sender.py](Pipeline/messaging/meta_sender.py)
8. Prints status, `message_id` on success, or `error_code` + `error_reason` on failure

**Run it:**

```powershell
python test_meta_sender.py
```

**Successful output:**

```
[loader] loaded 1 customers (1 skipped) from test_transactions.csv
[test] customer : CUST001 — Marchel
[test] phone    : +6282123501897
[test] risk     : HIGH (rules: ['R01', 'R03'])
[test] promo    : discount_30 — 30% off your next purchase (BACK30)

[test] message preview:
Hi Marchel, we miss you!
...

[test] sending reengagement_promo to +6282123501897...
[test] status    : sent
[test] message_id: wamid.HBgL...
```

**The `test_transactions.csv` cutoff trick:**

The loader derives `date_cutoff = max(purchase_date)` from the CSV. If you only have one customer, their most recent purchase IS the cutoff — so they have 0 days inactive, no rules fire, and they get filtered out. `at_risk` ends up empty.

To avoid that, the fixture includes a **CUTOFF anchor row** with an invalid phone (skipped by the loader) but a future `purchase_date` that pushes the cutoff forward:

```csv
customer_id,customer_name,phone_number,created_at,purchase_date,order_value,product_category
CUST001,Marchel,082123501897,2023-01-01,2023-08-10,250000,Electronics
CUST001,Marchel,082123501897,2023-01-01,2023-09-15,175000,Electronics
CUST001,Marchel,082123501897,2023-01-01,2023-10-02,320000,Fashion
CUTOFF,Cutoff,INVALID,2020-01-01,2024-11-01,10000,Other
```

CUST001's last purchase (2023-10-02) is ~390 days before the cutoff (2024-11-01) — well past `INACTIVITY_THRESHOLD_DAYS`, so R01 fires and they show as HIGH risk.

Change the phone, dates, or amounts in this CSV to test different customer states.

**Testing connectivity with `hello_world` first:**

If `reengagement_promo` is still pending approval, you can swap to Meta's pre-approved `hello_world` template (no parameters, available in every new app) to verify the API connection. The file has a commented-out `hello_world` block at the top — uncomment it, comment out the promo block below, and run again. A successful send through `hello_world` proves your token, phone number ID, and webhook plumbing are all correct.

### 3b. Full blast through the API

For a real blast through the production pipeline (DB persistence, cooldown filter, opt-out filter, a UUID `blast_id`), use the FastAPI server:

```powershell
# Terminal 1 — start the API
uvicorn Pipeline.api.main:app --reload

# Then open the Swagger UI in a browser:
# http://localhost:8000/docs → POST /blast/send → Try it out
```

Or via PowerShell directly:

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/blast/send" -ContentType "application/json" -Body '{"ml_enabled":true}'
```

This route writes to `blast_log` and upserts `customer` for each send. See [Pipeline/api/routes/blast.py](Pipeline/api/routes/blast.py).

---

## 4. Inbound — webhook receiver

The webhook ([webhook.py](webhook.py)) is a small Flask app that:

- Verifies Meta's GET handshake (required before Meta will send anything)
- Receives POST notifications for inbound messages and delivery statuses
- Persists every inbound message to `incoming_messages` in the SQLite DB
- Detects `STOP` and flips `customer.is_unsubscribe = 1`

Meta requires a **public HTTPS URL** for the webhook — `localhost` won't work. Use ngrok to expose your local Flask app with a temporary public HTTPS URL.

### 4a. Local dev with ngrok

ngrok creates a public HTTPS tunnel to your local Flask app — perfect for fast iteration without redeploying.

**Install ngrok:**

On **Windows**:

```powershell
# Option A — winget
winget install ngrok.ngrok

# Option B — chocolatey
choco install ngrok

# Option C — download from https://ngrok.com/download
```

On **macOS**:

```bash
# Option A — Homebrew (recommended)
brew install --cask ngrok

# Option B — download from https://ngrok.com/download
```

Verify the install on either OS:

```
ngrok version
```

**Sign up and authenticate (one-time):**

1. Sign up at [ngrok.com](https://ngrok.com) — free tier is enough
2. Copy your auth token from [dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken)
3. Run:

```powershell
ngrok config add-authtoken YOUR_TOKEN
```

**Run the webhook locally:**

```powershell
# Terminal 1 — Flask app
pip install flask
python webhook.py
# webhook listening on http://localhost:5000
```

**Start the tunnel:**

```powershell
# Terminal 2 — ngrok
ngrok http 5000
```

You'll see something like:

```
Forwarding   https://opponent-disobey-unretired.ngrok-free.dev -> http://localhost:5000
```

That HTTPS URL is what you give to Meta. Keep both terminals running while testing.

**ngrok free tier caveats:**

| Issue                                     | Workaround                                                                     |
| ----------------------------------------- | ------------------------------------------------------------------------------ |
| URL changes every restart                 | Re-enter it in Meta's Callback URL each time, or pay $8/mo for a static domain |
| Browser visitors see an interstitial page | Doesn't affect Meta's webhook calls                                            |
| ~2-hour session limit                     | Restart ngrok and update the Meta URL                                          |

### 4b. Configuring the webhook in Meta

1. Meta Developer portal → your app → **WhatsApp → Configuration**
2. Under **Webhook**, click **Edit**:

   | Field        | Value                                                             |
   | ------------ | ----------------------------------------------------------------- |
   | Callback URL | `https://YOUR_BASE_URL/webhook` (the `/webhook` path is required) |
   | Verify token | Same string as `WA_VERIFY_TOKEN`                                  |

3. Click **Verify and save** — Meta sends a GET request; if the token matches you'll see a green checkmark
4. Under **Webhook fields**, click **Manage** → subscribe to **`messages`** (covers inbound messages, delivery statuses, read receipts)
5. Click **Test** to send a sample payload — check your terminal/Render logs for `[webhook] message from ...`

### Development mode caveat

While your app is in **Development** mode (unpublished), Meta only delivers webhook events from the dashboard's **Test** button — **not** real customer messages, even from your own test number. To receive real inbound replies, you must **Publish** the app (requires a Privacy Policy URL and a few other small things, but no formal App Review for WhatsApp Cloud API messaging).

---

## 5. Opt-out flow (STOP keyword)

End-to-end behavior:

1. Customer texts `STOP` (case-insensitive, whitespace-trimmed) to your WhatsApp business number
2. Meta delivers the POST to your webhook
3. [webhook.py](webhook.py) saves the message to `incoming_messages` and runs:
   ```sql
   UPDATE customer SET is_unsubscribe = 1
   WHERE REPLACE(phone_number, '+', '') = ?
   ```
4. On the next `POST /blast/preview` or `POST /blast/send`, `_filter_unsubscribed()` in [Pipeline/api/routes/blast.py](Pipeline/api/routes/blast.py) drops opted-out customers from the at-risk list — they never have a promo assigned and never receive another message

Only the exact keyword `STOP` triggers opt-out. Compound phrases like "I want to stop" are intentionally ignored (Meta's recommendation, to avoid false positives).
