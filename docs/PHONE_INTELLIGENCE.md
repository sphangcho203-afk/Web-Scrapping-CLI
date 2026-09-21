# Phone number intelligence MCP tool

Internet Hands exposes phone-number intelligence as an MCP/Tool Mesh capability. It is **not** an account-verification or OTP feature.

## Interfaces

Direct MCP tool:

```text
phone_number_lookup
```

Raw Tool Mesh reference:

```text
phoneintel:lookup
```

Semantic capability:

```text
phone.number.lookup
```

Input:

```json
{
  "number": "+14155552671",
  "region": "US",
  "external": true,
  "providers": ["veriphone", "abstract", "numverify", "twilio"]
}
```

Only `number` is required. `region` helps parse numbers that are not already in international/E.164 form.

## Always-available local intelligence

The local libphonenumber layer requires no API key and returns:

- E.164, national, international and RFC3966 formats;
- validity and possibility;
- country calling code and numbering region;
- line type such as mobile, fixed line or VoIP;
- original numbering-range carrier metadata where available;
- offline geographic description;
- time zones;
- regional validity;
- a conservative SMS-capability heuristic;
- non-identifying risk/route flags.

Carrier metadata from libphonenumber describes the original numbering range and can be stale after number portability.

## Optional external enrichment

Configure any subset:

```text
PHONE_INTEL_PROVIDERS=veriphone,abstract,numverify,twilio

VERIPHONE_API_KEY=
VERIPHONE_MODE=static

ABSTRACT_PHONE_API_KEY=

NUMVERIFY_API_KEY=
# or:
APILAYER_API_KEY=

TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
# or:
TWILIO_API_KEY=
TWILIO_API_SECRET=

TWILIO_LOOKUP_SIM_SWAP=0
```

External enrichment can add current carrier/line-type metadata, MCC/MNC, provider risk scores, quota hints and eligible SIM-swap signals.

## Privacy boundary

The provider intentionally filters third-party responses through an allowlist. It does not return private subscriber identity, SIM-owner name, personal address, or other reverse-person records, even if an upstream response contains such fields.

Public/business identity should be handled by separate public-business search capabilities, not by treating a telephone number as authority to identify a private subscriber.
