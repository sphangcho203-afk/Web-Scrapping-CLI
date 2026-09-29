# OpenCrawl rewards and redemption

OpenCrawl rewards are deliberately separate from the USD service wallet.

## Earning points

Reward earning is based on underlying metered OpenCrawl work rather than whichever wallet-burn multiplier is currently used for pricing.

The base rate is controlled by:

```env
OPENCRAWL_REWARD_UNITS_PER_POINT=250
OPENCRAWL_CREDIT_BURN_MULTIPLIER=3
```

With the default 3× wallet burn, one reward point requires 750 charged wallet units. This normalization preserves the same underlying 250-unit earning threshold instead of making rewards three times easier to earn when wallet consumption is accelerated.

Accrual normalizes **each settled usage event** using the multiplier recorded on that event. New events persist their final `raw_settled` work directly; legacy events without multiplier metadata are treated as 1× because their historical wallet charge already matched raw work. Changing the multiplier later therefore does not reprice old, unprocessed reward usage.

User-owned connected apps and user-owned remote MCP servers that cost $0 in the OpenCrawl wallet therefore do not mint reward points merely for passing through the Tool Mesh.

Reward earning is cumulative and idempotent. OpenCrawl records how many usage-derived points have already been credited so refreshing the page or retrying a request cannot duplicate points.

## Prize catalog

The initial catalog contains wallet-credit prizes:

| Prize | Cost | Fulfillment |
| --- | ---: | --- |
| $0.25 rollover wallet credit | 100 points | 1,250 wallet units |
| $1.00 rollover wallet credit | 350 points | 5,000 wallet units |
| $5.00 rollover wallet credit | 1,500 points | 25,000 wallet units |

The catalog is stored server-side in `ih_reward_catalog`. The browser never decides a prize value or points cost.

## Redemption transaction

`POST /api/rewards/{reward_slug}/redeem` requires a verified signed-in account.

For a wallet-credit prize the server performs these operations in one database transaction:

1. synchronize any newly earned usage points;
2. lock the reward account and catalog row;
3. verify the point balance;
4. deduct reward points;
5. create an immutable reward-ledger entry;
6. create the redemption record;
7. add the wallet prize to rollover/purchased credits;
8. add the corresponding wallet-ledger entry;
9. mark the redemption fulfilled.

If wallet fulfillment fails, the database transaction rolls back, including the point deduction. The system therefore does not leave a user with spent points and no wallet prize.

## Future prize types

The schema also supports `manual` fulfillment. This is intended for prizes that cannot be delivered by a deterministic server-side mutation. Such redemptions remain `pending` until an operator or future fulfillment worker completes them.

Do not implement external prize delivery by trusting browser-provided amounts, URLs, gift-code values, or provider identifiers. Fulfillment data must come from the server-side reward catalog.


## Community reward codes

OpenCrawl supports operator-created codes for community drops. A code can grant either reward points or rollover wallet credit without requiring the user to spend points first.

Users redeem a code from **Dashboard → Rewards → Community Drop**. The browser sends only the entered code to:

```text
POST /api/rewards/codes/redeem
{"code":"DISCORD100"}
```

The server normalizes the code, verifies its keyed hash, checks its active window and global claim limit, and enforces one claim per account. Fulfillment and the claim record are committed in one database transaction.

Raw codes are not stored in the database. Configure a dedicated hashing secret and an operator token:

```env
OPENCRAWL_REWARD_CODE_SECRET=<long-random-secret>
OPENCRAWL_REWARD_ADMIN_TOKEN=<different-long-random-secret>
```

### Create a community drop

The operator endpoint requires the admin token in the `X-OpenCrawl-Admin-Token` header. The `code` field is optional; when omitted, OpenCrawl generates a code and returns it once.

Points example:

```bash
curl -X POST https://YOUR_OPENCRAWL_ORIGIN/api/admin/reward-codes \
  -H "Content-Type: application/json" \
  -H "X-OpenCrawl-Admin-Token: $OPENCRAWL_REWARD_ADMIN_TOKEN" \
  -d '{
    "code": "DISCORD100",
    "label": "Discord launch drop",
    "reward_type": "points",
    "reward_value": 100,
    "max_redemptions": 500,
    "expires_at": "2026-10-31T23:59:59Z"
  }'
```

Wallet-credit example:

```bash
curl -X POST https://YOUR_OPENCRAWL_ORIGIN/api/admin/reward-codes \
  -H "Content-Type: application/json" \
  -H "X-OpenCrawl-Admin-Token: $OPENCRAWL_REWARD_ADMIN_TOKEN" \
  -d '{
    "label": "Community wallet drop",
    "reward_type": "wallet_credit",
    "reward_value": 2500,
    "max_redemptions": 100
  }'
```

At the default denomination of 5,000 wallet units per USD, `reward_value: 2500` grants **$0.50** of rollover service balance.

The create response contains the raw code only so it can be copied into Discord, Telegram, announcements, or another community channel. Later admin listings return only a short code hint, not the original secret code.

### Campaign controls

Each code supports:

- `max_redemptions`: optional global claim cap;
- `starts_at`: optional ISO-8601 activation time;
- `expires_at`: optional ISO-8601 expiry;
- one redemption per OpenCrawl account;
- `points` or `wallet_credit` fulfillment;
- server-side redemption counters and user claim history.

List configured campaigns with:

```text
GET /api/admin/reward-codes
X-OpenCrawl-Admin-Token: <operator token>
```

Do not put the admin token or reward-code hashing secret in browser JavaScript, public repositories, community posts, or client-side environment variables.
