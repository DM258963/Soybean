#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import pathlib
import shlex
import subprocess
import sys
import uuid


def run(cmd: list[str], *, capture: bool = False) -> str:
    print("+", " ".join(shlex.quote(part) for part in cmd))
    result = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=capture,
    )
    if capture:
        return result.stdout.strip()
    return ""


def sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def psql_exec(service: str, db_user: str, db_name: str, sql: str) -> None:
    run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            service,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            db_user,
            "-d",
            db_name,
            "-c",
            sql,
        ]
    )


def normalize_header_name(header: str) -> str:
    return "".join(ch for ch in header.strip().lower() if ch.isalnum())


def detect_protein_copy_columns(protein_csv: pathlib.Path) -> list[str]:
    with protein_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        headers = next(reader, None)

    if not headers:
        raise ValueError(f"Protein CSV has no header: {protein_csv}")

    mapped: list[str] = []
    for header in headers:
        key = normalize_header_name(header)
        if key in {"protein", "sequence", "proteinsequence", "seq"}:
            mapped.append("protein")
        elif key in {"genename", "gene", "geneid"}:
            mapped.append("gene_name")
        else:
            raise ValueError(
                f"Unrecognized column '{header}' in {protein_csv.name}. "
                "Protein CSV should only contain columns like 'Gene name' and 'Protein'."
            )

    if mapped.count("gene_name") != 1 or mapped.count("protein") != 1:
        raise ValueError(
            f"{protein_csv.name} must include exactly one Gene name column and one Protein column."
        )

    return mapped


def detect_gs_copy_columns(gs_csv: pathlib.Path) -> list[str]:
    with gs_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        headers = next(reader, None)

    if not headers:
        raise ValueError(f"GS CSV has no header: {gs_csv}")

    key_map = {
        "organism": "organism",
        "class": "ptm_types",
        "ptmtypes": "ptm_types",
        "type": "record_type",
        "proteinacc": "protein_accession",
        "proteinaccession": "protein_accession",
        "position": "position",
        "aa": "amino_acid",
        "aminoacid": "amino_acid",
        "proteindescription": "protein_description",
        "genenam": "gene_name",
        "geneid": "transcript_id",
        "transcriptid": "transcript_id",
        "genenames": "gene_names",
        "w4m1": "w4m_1",
        "w4m2": "w4m_2",
        "w4m3": "w4m_3",
        "w12m1": "w12m_1",
        "w12m2": "w12m_2",
        "w12m3": "w12m_3",
        "w12mw4mratio": "w12m_w4m_ratio",
        "w12mw4mpvalue": "w12m_w4m_p_value",
        "w12mw4mtype": "w12m_w4m_type",
        "subcellularlocalization": "subcellular_localization",
        "keggkono": "kegg_ko_no",
        "kegggene": "kegg_gene",
        "keggpathway": "kegg_pathway",
        "biologicalprocess": "biological_process",
        "cellularcomponent": "cellular_component",
        "molecularfunction": "molecular_function",
        "pfamid": "pfam_id",
        "domaindescription": "domain_description",
        "sitedomain": "site_domain",
        "kogcategory": "kog_category",
        "kogno": "kog_no",
        "kogdescription": "kog_description",
        "keggkono2": "kegg_ko_no_2",
        "keggkono1": "kegg_ko_no_2",
        "cogcategory": "cog_category",
        "cogno": "cog_no",
        "cogdescription": "cog_description",
    }

    mapped: list[str] = []
    for header in headers:
        raw_header = header.strip()
        raw_lower = raw_header.lower()
        if raw_lower == "gene name":
            mapped.append("gene_name")
            continue
        if raw_header == "GeneName":
            mapped.append("gene_names")
            continue
        if raw_header == "GeneID":
            mapped.append("transcript_id")
            continue
        key = normalize_header_name(header)
        if key not in key_map:
            raise ValueError(
                f"Unrecognized column '{header}' in {gs_csv.name}. "
                "Please update GS header mapping in import_ptm_csv.py."
            )
        mapped.append(key_map[key])

    required = {"ptm_types", "position", "amino_acid", "gene_name"}
    if not required.issubset(set(mapped)):
        missing = ", ".join(sorted(required - set(mapped)))
        raise ValueError(f"{gs_csv.name} missing required GS columns: {missing}")

    return mapped


def copy_to_container(container_id: str, local_file: pathlib.Path) -> str:
    container_path = f"/tmp/{uuid.uuid4().hex}_{local_file.name}"
    run(["docker", "cp", str(local_file), f"{container_id}:{container_path}"])
    return container_path


def ensure_container_running(service: str) -> str:
    cid = run(["docker", "compose", "ps", "-q", service], capture=True)
    if cid:
        return cid

    print("No running container found, starting service...")
    run(["docker", "compose", "up", "-d", service])
    cid = run(["docker", "compose", "ps", "-q", service], capture=True)
    if not cid:
        raise RuntimeError(f"Could not start docker compose service: {service}")
    return cid


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import GS/protein CSV into ptm_prod through staging tables."
    )
    parser.add_argument("--gs-csv", help="Path to GS CSV file.")
    parser.add_argument("--protein-csv", help="Path to protein sequence CSV file.")
    parser.add_argument("--service", default="postgres", help="Compose service name.")
    parser.add_argument("--db-user", default="myuser", help="PostgreSQL user.")
    parser.add_argument("--db-name", default="ptm_prod", help="PostgreSQL database name.")
    parser.add_argument(
        "--encoding",
        default="UTF8",
        help="CSV encoding used by psql \\copy (default: UTF8).",
    )
    parser.add_argument(
        "--source-version",
        default=dt.date.today().isoformat(),
        help="Value passed to apply functions as source_version.",
    )
    parser.add_argument(
        "--gs-source-name",
        default=None,
        help="Override source_name for GS import. Default is gs csv filename stem.",
    )
    parser.add_argument(
        "--protein-source-name",
        default=None,
        help="Override source_name for protein import. Default is protein csv filename stem.",
    )
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help="Do not truncate staging tables before import.",
    )
    args = parser.parse_args()

    if not args.gs_csv and not args.protein_csv:
        parser.error("Provide at least one of --gs-csv or --protein-csv.")

    gs_csv = pathlib.Path(args.gs_csv).resolve() if args.gs_csv else None
    protein_csv = pathlib.Path(args.protein_csv).resolve() if args.protein_csv else None

    if gs_csv and not gs_csv.exists():
        raise FileNotFoundError(f"GS CSV not found: {gs_csv}")
    if protein_csv and not protein_csv.exists():
        raise FileNotFoundError(f"Protein CSV not found: {protein_csv}")

    container_id = ensure_container_running(args.service)

    container_files: dict[str, str] = {}
    if gs_csv:
        container_files["gs"] = copy_to_container(container_id, gs_csv)
    if protein_csv:
        container_files["protein"] = copy_to_container(container_id, protein_csv)

    if not args.keep_staging:
        truncates: list[str] = []
        if gs_csv:
            truncates.append("ptm.stg_gs_ptm")
        if protein_csv:
            truncates.append("ptm.stg_protein_sequence")
        if truncates:
            psql_exec(
                args.service,
                args.db_user,
                args.db_name,
                "TRUNCATE TABLE " + ", ".join(truncates) + ";",
            )

    if gs_csv:
        gs_path_sql = container_files["gs"].replace("'", "''")
        gs_copy_columns = ", ".join(detect_gs_copy_columns(gs_csv))
        psql_exec(
            args.service,
            args.db_user,
            args.db_name,
            (
                f"\\copy ptm.stg_gs_ptm ({gs_copy_columns}) "
                f"FROM '{gs_path_sql}' WITH (FORMAT csv, HEADER true, ENCODING '{args.encoding}')"
            ),
        )
        gs_source_name = args.gs_source_name or gs_csv.stem
        psql_exec(
            args.service,
            args.db_user,
            args.db_name,
            (
                "SELECT ptm.apply_stg_gs_ptm("
                f"{sql_literal(gs_source_name)}, "
                f"{sql_literal(args.source_version)}"
                ");"
            ),
        )

    if protein_csv:
        protein_path_sql = container_files["protein"].replace("'", "''")
        protein_copy_columns = ", ".join(detect_protein_copy_columns(protein_csv))
        psql_exec(
            args.service,
            args.db_user,
            args.db_name,
            (
                f"\\copy ptm.stg_protein_sequence ({protein_copy_columns}) "
                f"FROM '{protein_path_sql}' WITH (FORMAT csv, HEADER true, ENCODING '{args.encoding}')"
            ),
        )
        protein_source_name = args.protein_source_name or protein_csv.stem
        psql_exec(
            args.service,
            args.db_user,
            args.db_name,
            (
                "SELECT ptm.apply_stg_protein_sequence("
                f"{sql_literal(protein_source_name)}, "
                f"{sql_literal(args.source_version)}"
                ");"
            ),
        )

    psql_exec(
        args.service,
        args.db_user,
        args.db_name,
        (
            "SELECT COUNT(*) AS gs_rows FROM ptm.gs_ptm; "
            "SELECT COUNT(*) AS seq_rows FROM ptm.protein_sequence;"
        ),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}", file=sys.stderr)
        raise
