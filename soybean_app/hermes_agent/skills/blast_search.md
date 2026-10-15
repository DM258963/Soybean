# blast_search

Use this skill when the user provides an amino-acid sequence or explicitly asks for BLAST / similarity search.

## Arguments

- sequence: amino-acid sequence.
- species: `glycine_max` or `bradyrhizobium_diazoefficiens`.

## Endpoint

POST `/api/hermes/blast`

## Examples

User: `blast MAAAAAAAAGGGGGGGGGGSSSSSSSSSS`

```json
{"tool":"blast_search","arguments":{"sequence":"MAAAAAAAAGGGGGGGGGGSSSSSSSSSS","species":"glycine_max"}}
```

User: `Use Bradyrhizobium sequence MTEYKLVVVGAGGVGKSALTIQLIQNHFVDEYDPTIEDSYRKQ`

```json
{"tool":"blast_search","arguments":{"sequence":"MTEYKLVVVGAGGVGKSALTIQLIQNHFVDEYDPTIEDSYRKQ","species":"bradyrhizobium_diazoefficiens"}}
```
