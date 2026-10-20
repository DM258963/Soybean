from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.tools import InjectedToolArg, tool

from soybean_app.services.agent import (
    _agent_blast_service,
    _agent_protein_service,
    _agent_ptm_service,
)


SpeciesKey = Literal[
    "glycine_max",
    "bradyrhizobium_diazoefficiens",
]


@tool
def protein_search(
    query: str,
    species: SpeciesKey = "glycine_max",
    limit: int = 10,
    site_limit: int = 10,
    allow_multiple_identifiers: Annotated[bool, InjectedToolArg] = False,
) -> dict:
    """Search one or more protein identifiers and return PTM evidence.

    Use one query containing every explicit identifier when the user requests a
    comparison. Multi-identifier execution is authorized by the application and
    is not a model-controlled argument.
    """

    return _agent_protein_service(
        {
            "query": query,
            "species": species,
            "limit": limit,
            "site_limit": site_limit,
            "_allow_multiple_identifiers": allow_multiple_identifiers,
        }
    )


@tool
def ptm_search(
    expression: str,
    species: SpeciesKey = "glycine_max",
    sequence_length: int = 7,
    representative_only: bool = False,
    peptides_unique: bool = False,
    limit: int = 10,
) -> dict:
    """Search PTM motifs, modification expressions, and sequence-context patterns."""

    return _agent_ptm_service(
        {
            "expression": expression,
            "species": species,
            "sequence_length": sequence_length,
            "representative_only": representative_only,
            "peptides_unique": peptides_unique,
            "limit": limit,
        }
    )


@tool
def blast_search(
    sequence: str,
    species: SpeciesKey = "glycine_max",
    max_hits: int = 10,
    identity_min: float = 0,
    e_value_max: float = 10,
    query_cover_min: float = 0,
) -> dict:
    """Run a protein sequence similarity search against the selected organism."""

    return _agent_blast_service(
        {
            "sequence": sequence,
            "species": species,
            "max_hits": max_hits,
            "identity_min": identity_min,
            "e_value_max": e_value_max,
            "query_cover_min": query_cover_min,
        }
    )


AGENT_TOOLS = [protein_search, ptm_search, blast_search]
AGENT_TOOLS_BY_NAME = {agent_tool.name: agent_tool for agent_tool in AGENT_TOOLS}

