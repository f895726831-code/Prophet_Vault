# Model change report

**Old snapshot**: `demo_2026-01` (146 variables)
**New snapshot**: `demo_2026-02` (148 variables)

## Summary

| Change type | Count |
|-------------|-------|
| Variables added | 3 |
| Variables deleted | 1 |
| Formulas changed | 1 |
| Descriptions changed | 1 |
| Indicators changed | 0 |
| References changed | 1 |
| Unchanged | 142 |

## Added variables (3)

- `NEW_FEATURE_A`
- `NEW_FEATURE_B`
- `NEW_FEATURE_C`

## Deleted variables (1)

- ~~`FLOW_007`~~

## Formula changes (1)

### `FLOW_010`

Before:

```prophet
IF t = 0 THEN
  LAPSE_TBL_06 * LAPSE_TBL_01
ELSE
  EXPNS_IN_01(t-1) + LAPSE_TBL_06 * LAPSE_TBL_01
```

After:

```prophet
IF t = 0 THEN
  LAPSE_TBL_06  / 2 * LAPSE_TBL_01
ELSE
  EXPNS_IN_01(t-1) + LAPSE_TBL_06 * LAPSE_TBL_01
```

## Dependency changes (1)

- `AGG_016`: +- / -`FLOW_007`
