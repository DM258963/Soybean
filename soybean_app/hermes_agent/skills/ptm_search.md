# ptm_search

Use this skill when the user asks for a PTM motif, PTM expression pattern, modification pattern, or motif search.

## Arguments

- expression: PTM expression or motif, such as `S[ph]`, `K[ub]`, or `S[ph]P`.
- species: `glycine_max` or `bradyrhizobium_diazoefficiens`.

## Endpoint

POST `/api/hermes/ptm`

## Examples

User: `Find motif S[ph]P`

```json
{"tool":"ptm_search","arguments":{"expression":"S[ph]P","species":"glycine_max"}}
```

User: `PTM expression K[ub]`

```json
{"tool":"ptm_search","arguments":{"expression":"K[ub]","species":"glycine_max"}}
```
