# OpenCrawl rewards and redemption

OpenCrawl rewards are deliberately separate from the USD service wallet.

## Earning points

By default, one reward point is earned for every 250 wallet units of metered OpenCrawl usage. At the default denomination of 5,000 wallet units per USD, that is one point per $0.05 of actual OpenCrawl-funded usage.

The rate is controlled by:

```env
OPENCRAWL_REWARD_UNITS_PER_POINT=250
```

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
