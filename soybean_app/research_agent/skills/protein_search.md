# protein_search

Use this skill when the user asks about one or more gene names, protein accessions, transcript IDs, short identifiers, or PTM overview/details. It also supports comparisons between multiple proteins for accounts that are authorized to submit multiple identifiers.

## Arguments

- query: one or more gene names, protein accessions, transcript IDs, or short identifiers. Preserve all explicit identifiers and separate them with spaces.
- species: `glycine_max` or `bradyrhizobium_diazoefficiens`.

## Multi-protein comparison

Identifiers may appear in Markdown tables, bold text, HTML entities, or on separate lines. Extract every explicit identifier before calling the tool.

When the user asks for similarities or differences between two or more proteins:

1. Call `protein_search` once with all explicit identifiers in `query`.
2. Compare only fields present in the returned evidence: protein description, organism, PTM site count, PTM type count, PTM summary, and returned residue-level sites.
3. Present the response as common features, differences, and evidence limitations.
4. Do not claim a shared PTM type or residue-level site unless the returned records support it.
5. If `sites_truncated` is true, explain that the residue-level comparison covers only the returned subset.

The workflow enforces permissions. Never remove identifiers to bypass a multi-identifier restriction; wait for the workflow's identifier-selection interrupt.

## Endpoint

POST `/api/agent/protein`

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

User:

```text
| **I1LAY3** |
I1KP84&#x20;

Compare the similarities and differences between these proteins.
```

```json
{"tool":"protein_search","arguments":{"query":"I1LAY3 I1KP84","species":"glycine_max"}}
```
