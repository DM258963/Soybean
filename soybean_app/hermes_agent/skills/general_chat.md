# general_chat

Use this skill when the user is greeting the assistant, asking what the assistant can do, asking what the website/page does, asking for help or usage instructions, asking about navigation, or asking for a general explanation that does not require database lookup.

Also use this skill when the user asks which function, feature, module, or page they should use. In that case, answer with a specific website recommendation:

- Protein Search for one gene/protein/transcript/accession, PTM overview, or modified residue/site details.
- PTM Search for PTM motif, PTM expression, modification type, sequence-context pattern, or crosstalk/co-occurring modification searches.
- BLAST / Sequence Search for pasted amino-acid sequences, similarity, homology, or alignment.
- Proteome for expression profiles, abundance, quantification, and stage comparisons.
- Analysis / List Analysis for batch protein/gene lists and list-level PTM statistics.
- Browse for browsing curated records.
- Data / Raw Data for raw tables, CSV files, or downloads.
- Data / Submit Data for uploading or submitting new datasets.
- About for project introduction, citation, version notes, or contact information.

For broad questions like `我要查询大豆的 PTM 应该使用哪个功能`, explain the distinction instead of giving a generic page description: use Protein Search for one gene/protein's PTM sites, PTM Search for motif/type/pattern searches, and BLAST / Sequence Search for amino-acid sequences.

When unsure whether a message is a real gene/protein identifier, PTM motif, or amino-acid sequence, use this skill instead of a search skill.

This skill maps to router tool value `none`.

## Arguments

- question: original user message.
- species: default to `glycine_max` unless the user clearly mentions another species.

## Examples

User: `hello`

```json
{"tool":"none","arguments":{"question":"hello","species":"glycine_max"}}
```

User: `what is PTM?`

```json
{"tool":"none","arguments":{"question":"what is PTM?","species":"glycine_max"}}
```

User: `这个网页有什么功能`

```json
{"tool":"none","arguments":{"question":"这个网页有什么功能","species":"glycine_max"}}
```

User: `我要查询大豆的 PTM 应该使用哪个功能`

```json
{"tool":"none","arguments":{"question":"我要查询大豆的 PTM 应该使用哪个功能","species":"glycine_max"}}
```

User: `蛋白表达谱在哪查`

```json
{"tool":"none","arguments":{"question":"蛋白表达谱在哪查","species":"glycine_max"}}
```
