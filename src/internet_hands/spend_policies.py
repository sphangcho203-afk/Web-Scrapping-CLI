"""Account/key credit caps derived from authoritative usage and reservations."""
from datetime import UTC, timedelta

from .control_store import WALLET_UNITS_PER_USD, ControlError

LIMITS = ('single_run_limit_credits', 'daily_limit_credits', 'monthly_limit_credits')
SCHEMA = """
CREATE TABLE IF NOT EXISTS ih_spend_policies (
 user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
 scope_id text NOT NULL,
 api_key_id text REFERENCES ih_api_keys(id) ON DELETE CASCADE,
 single_run_limit_credits integer CHECK(single_run_limit_credits BETWEEN 0 AND 1000000000),
 daily_limit_credits integer CHECK(daily_limit_credits BETWEEN 0 AND 1000000000),
 monthly_limit_credits integer CHECK(monthly_limit_credits BETWEEN 0 AND 1000000000),
 version bigint NOT NULL CHECK(version>0),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,scope_id),
 CHECK((api_key_id IS NULL AND scope_id='account') OR (api_key_id IS NOT NULL AND scope_id=api_key_id))
);
"""


def _periods(as_of):
    day = as_of.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    following = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return day, month, following


def _owned_key(cur, owner, scope):
    if scope == 'account':
        return
    cur.execute('SELECT id FROM ih_api_keys WHERE id=%s AND user_id=%s', (scope, owner))
    if not cur.fetchone():
        raise ControlError('api_key_not_found', 'API key not found for this account.', 404)


def _policy(cur, owner, scope):
    cur.execute('''SELECT scope_id,version,single_run_limit_credits,daily_limit_credits,
        monthly_limit_credits,updated_at FROM ih_spend_policies WHERE user_id=%s AND scope_id=%s''',
        (owner, scope))
    row = cur.fetchone()
    return dict(row) if row else {'scope_id':scope, 'version':0, 'updated_at':None,
                                  **{name:None for name in LIMITS}}


def _usage(cur, owner, scope, as_of):
    day, month, following = _periods(as_of)
    cur.execute('''WITH measured AS (
        SELECT created_at,CASE WHEN status='reserved' THEN 0 ELSE GREATEST(credits_charged,0) END AS charged,
        CASE WHEN status='reserved' AND metadata#>>'{reservation,credits}' ~ '^[0-9]{1,10}$'
            THEN (metadata#>>'{reservation,credits}')::bigint ELSE 0 END AS reserved,
        CASE WHEN status='reserved' AND NOT COALESCE(metadata#>>'{reservation,credits}' ~ '^[0-9]{1,10}$',false)
            THEN 1 ELSE 0 END AS unknown
        FROM ih_usage_events WHERE user_id=%s AND created_at>=%s AND created_at<%s
            AND (%s='account' OR api_key_id=%s))
        SELECT COALESCE(sum(charged),0) AS monthly_charged,COALESCE(sum(reserved),0) AS monthly_reserved,
            COALESCE(sum(unknown),0) AS monthly_unknown,
            COALESCE(sum(charged) FILTER(WHERE created_at>=%s),0) AS daily_charged,
            COALESCE(sum(reserved) FILTER(WHERE created_at>=%s),0) AS daily_reserved,
            COALESCE(sum(unknown) FILTER(WHERE created_at>=%s),0) AS daily_unknown FROM measured''',
        (owner,month,as_of,scope,scope,day,day,day))
    row = cur.fetchone()
    return {'as_of':as_of,'timezone':'UTC','day_start':day,'day_end':day+timedelta(days=1),
            'month_start':month,'month_end':following,
            **{period:{'charged_credits':int(row[period+'_charged']),
                       'reserved_credits':int(row[period+'_reserved']),
                       'committed_credits':int(row[period+'_charged']+row[period+'_reserved']),
                       'unknown_reservation_count':int(row[period+'_unknown'])}
               for period in ('daily','monthly')}}


def _snapshot(cur, owner, scope, as_of):
    policy = _policy(cur,owner,scope)
    usage = _usage(cur,owner,scope,as_of)
    for period in ('daily','monthly'):
        limit = policy[period+'_limit_credits']
        usage[period]['remaining_credits'] = (None if limit is None or usage[period]['unknown_reservation_count']
            else max(0,limit-usage[period]['committed_credits']))
    return {'policy':policy,'usage':usage,'enforcement':'hard_stop','unit':'wallet_credit',
            'wallet_units_per_usd':WALLET_UNITS_PER_USD}


def enforce(cur, owner, key_id, reserved, as_of):
    """Caller holds the account wallet lock through usage insertion."""
    if reserved == 0:
        return []
    scopes = ['account'] + ([key_id] if key_id else [])
    cur.execute('''SELECT scope_id,version,single_run_limit_credits,daily_limit_credits,monthly_limit_credits
        FROM ih_spend_policies WHERE user_id=%s AND scope_id=ANY(%s) ORDER BY scope_id''',(owner,scopes))
    applied = []
    for policy in cur.fetchall():
        if all(policy[name] is None for name in LIMITS):
            continue
        label = 'account' if policy['scope_id']=='account' else 'API key'
        single = policy['single_run_limit_credits']
        if single is not None and reserved>single:
            raise ControlError('spend_policy_exceeded',
                f"The {label} per-run limit allows {single} credits; this run requires {reserved}.",409)
        usage = _usage(cur,owner,policy['scope_id'],as_of) if any(
            policy[name] is not None for name in ('daily_limit_credits','monthly_limit_credits')) else None
        for period in ('daily','monthly'):
            limit = policy[period+'_limit_credits']
            if limit is None:
                continue
            if usage[period]['unknown_reservation_count']:
                raise ControlError('spend_usage_unavailable',
                    'An active reservation has unknown credit usage. Resolve it before starting more paid work.',409)
            committed = usage[period]['committed_credits']
            if committed+reserved>limit:
                raise ControlError('spend_policy_exceeded',
                    f"The {label} {period} limit is {limit} credits; {committed} are charged or reserved, and this run requires {reserved}.",409)
        applied.append(dict(policy))
    return applied


class SpendPolicyStore:
    def __init__(self, control):
        self.control = control

    def get(self, owner, scope='account', *, as_of=None):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            _owned_key(cur,owner,scope)
            cur.execute('SELECT clock_timestamp() AS now')
            current_time = cur.fetchone()['now']
            return _snapshot(cur,owner,scope,as_of or current_time)

    def put(self, owner, scope, body):
        if not isinstance(body,dict) or set(body)!=set(LIMITS)|{'expected_version'}:
            raise ControlError('invalid_spend_policy','Supply all three limits and expected_version.',422)
        for name in LIMITS:
            value = body[name]
            if value is not None and (type(value) is not int or not 0<=value<=1_000_000_000):
                raise ControlError('invalid_spend_policy',f'{name} must be null or an integer from 0 to 1000000000.',422)
        if type(body['expected_version']) is not int or not 0<=body['expected_version']<=9_000_000_000_000_000:
            raise ControlError('invalid_spend_policy','expected_version must be a nonnegative integer.',422)
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            # Take the FK-compatible owner lock before the wallet. Durable job
            # creation locks the owner first; reversing that order can deadlock.
            cur.execute('SELECT id FROM ih_users WHERE id=%s FOR KEY SHARE',(owner,))
            cur.execute('SELECT user_id FROM ih_wallets WHERE user_id=%s FOR UPDATE',(owner,))
            if not cur.fetchone():
                raise ControlError('wallet_missing','Wallet not found.',404)
            _owned_key(cur,owner,scope)
            current = _policy(cur,owner,scope)
            if current['version']!=body['expected_version']:
                raise ControlError('spend_policy_changed','Spending limits changed. Reload them before saving.',409)
            cur.execute('''INSERT INTO ih_spend_policies(user_id,scope_id,api_key_id,
                single_run_limit_credits,daily_limit_credits,monthly_limit_credits,version)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,scope_id) DO UPDATE SET
                single_run_limit_credits=EXCLUDED.single_run_limit_credits,daily_limit_credits=EXCLUDED.daily_limit_credits,
                monthly_limit_credits=EXCLUDED.monthly_limit_credits,version=EXCLUDED.version,updated_at=clock_timestamp()''',
                (owner,scope,None if scope=='account' else scope,*(body[name] for name in LIMITS),current['version']+1))
            cur.execute('SELECT clock_timestamp() AS now')
            return _snapshot(cur,owner,scope,cur.fetchone()['now'])
