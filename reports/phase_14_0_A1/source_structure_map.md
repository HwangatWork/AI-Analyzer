# source_structure_map.md

**File**: `tools/consensus/source_access_audit.py`
**Total lines**: 446

## Module-level constants (lines 36-99)

| Lines | Name | Role |
|---|---|---|
| 36-41 | `EXIT_OK` / `EXIT_INVALID_SOURCES` / `EXIT_WRITE_FAILED` / `EXIT_UNSAFE_FLAG` / `EXIT_INVALID_POLICY` / `EXIT_SCHEMA_FAILED` | Exit-code constants (0/1/2/4/5/6) |
| 44-56 | `REQUIRED_SOURCE_FIELDS` | Tuple of required fields per source-config entry |
| 58-65 | `REQUIRED_POLICY_CATEGORIES` | Tuple of required policy-keyword categories |
| 67-78 | `REQUIRED_OUTPUT_TOP_LEVEL` | Tuple of required output-JSON top-level fields |
| 80-99 | `REQUIRED_OUTPUT_SOURCE_FIELDS` | Tuple of required fields per output source entry |

## Classes and functions

| Lines | Symbol | One-line responsibility |
|---|---|---|
| 101-102 | `class NetworkAccessForbidden(RuntimeError)` | Raised if any code path tries to open a socket during dry-run. |
| 105-119 | `def _install_network_guard()` | Patches `socket.socket` and `socket.create_connection` to raising stubs so any accidental network call hard-fails. |
| 121-122 | `def _now_iso()` | Returns ISO-8601 timestamp with local timezone offset, second precision. |
| 125-127 | `def _load_json(path)` | Reads a UTF-8 JSON file. Raises `FileNotFoundError` / `json.JSONDecodeError`. |
| 130-169 | `def validate_sources_config(cfg)` | Validates the source-config object: root shape, ≥7 sources, required fields present, unique provider names, `financial_data_fetch_allowed=False` everywhere. Returns `(ok, errors)`. |
| 171-193 | `def validate_policy_config(cfg)` | Validates the policy-keyword object: required categories present, each has non-empty `ko` and `en` term lists. Returns `(ok, errors)`. |
| 195-232 | `def assess_license_risk(src)` | Heuristic 3-tier classification (`low` / `medium` / `high` / `unknown`) with explicit `risk_reason_codes`. Decision tree based on `requires_login`, `requires_api_key`, `source_type`, provider name. |
| 234-321 | `def build_output(sources_cfg, policy_cfg, ...)` | Assembles the output JSON: target, defaults, per-source entries (incl. risk classification + readiness flags), summary counts. Pure function; no I/O. |
| 323-348 | `def verify_output_schema(obj)` | Validates the *output* JSON before write: required top-level fields, `network_calls_made == 0`, `mode == 'dry_run_static_audit'`, per-source required fields. Returns `(ok, errors)`. |
| 350-362 | `def _parse_args(argv)` | argparse setup. Declares `--live` / `--fetch-data` as known flags so main() can reject them deliberately with EXIT_UNSAFE_FLAG. Uses `parse_known_args` to also catch raw `--live` / `--fetch-data` in unknown args. |
| 364-443 | `def main(argv)` | Orchestrator: parse args → reject forbidden flags → install network guard → load configs → validate sources → validate policy → build output → verify schema → write JSON → print DONE_CRITERIA. Returns exit code. |

## Function call graph (top-down)

```
main()
  ├─ _parse_args()              # may exit with EXIT_UNSAFE_FLAG (4)
  ├─ _install_network_guard()
  ├─ _load_json(args.config)    # may exit with EXIT_INVALID_SOURCES (1)
  ├─ _load_json(args.policy)    # may exit with EXIT_INVALID_POLICY (5)
  ├─ validate_sources_config()  # may exit with EXIT_INVALID_SOURCES (1)
  ├─ validate_policy_config()   # may exit with EXIT_INVALID_POLICY (5)
  ├─ build_output()
  │    └─ assess_license_risk() (per source)
  ├─ verify_output_schema()     # may exit with EXIT_SCHEMA_FAILED (6)
  └─ json.dump + os.makedirs    # may exit with EXIT_WRITE_FAILED (2)
```

## Structural assessment

- **Single-responsibility separation**: validation / output-build / output-verify / I/O are each in their own function. `main()` is purely orchestration (~70 lines, fully linear).
- **No state**: no module-level mutable state. All data flows are explicit function arguments.
- **No external libraries**: standard library only (`argparse`, `datetime`, `json`, `os`, `socket`, `sys`).
- **Refactor verdict**: **not required** — structure is appropriate for the size and scope; further decomposition would add cost without value.
