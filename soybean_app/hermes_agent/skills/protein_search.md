# protein_search

Use this skill when the user asks about a gene, protein accession, transcript id, short identifier, or PTM overview/details for one identifier.

## Arguments

- query: gene name, protein accession, transcript id, or short identifier.
- species: `glycine_max` or `bradyrhizobium_diazoefficiens`.

## Endpoint

POST `/api/hermes/protein`

## Examples

User: `GLYMA_10G142500`

```json
{"tool":"protein_search","arguments":{"query":"GLYMA_10G142500","species":"glycine_max"}}
```

User: `Does I1LAY3 have PTM sites?`

```json
{"tool":"protein_search","arguments":{"query":"I1LAY3","species":"glycine_max"}}
```

User: `Bradyrhizobium nifD PTM`

```json
{"tool":"protein_search","arguments":{"query":"nifD","species":"bradyrhizobium_diazoefficiens"}}
```
