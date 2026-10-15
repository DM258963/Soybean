import csv
import re
from collections import defaultdict
from pathlib import Path

# 1) 输入 FASTA 文件（包含 Protein accession 和 sequence）
INPUT_FASTA = Path(r"E:\Project\网站\data\Glycine_max_3847_PR_20250516.fasta")

# 2) 输入 GS 数据文件（包含 Protein accession + Gene Name）
INPUT_GS_CSV = Path(r"E:\Project\网站\data\网站gs数据-V1-260423.csv")

# 3) 输出蛋白序列 CSV（用于导入，列名固定：Gene name, Protein）
OUTPUT_CSV = Path(r"E:\Project\网站\data\protein_sequence_utf8.csv")

# 4) GS 里列名（按你的表头写；如不一致可改这里）
GS_ACCESSION_COLUMN = "Protein accession"
GS_GENE_COLUMN = "Gene Names"

# 5) Gene name 处理模式：
# True  = 直接保留 GS 原单元格内容（推荐，符合“原样粘贴”）
# False = 尝试拆分别名并做规范化
KEEP_GS_GENE_CELL_AS_IS = True

# 当 KEEP_GS_GENE_CELL_AS_IS=False 时，是否规范化 GLYMA_18G041100 -> Glyma.18G041100
NORMALIZE_GLYMA_GENE_NAME = True


def normalize_gene_name(gene_name: str) -> str:
    raw = gene_name.strip()
    if not raw:
        return ""
    if not NORMALIZE_GLYMA_GENE_NAME:
        return raw

    m = re.match(r"^GLYMA_(.+)$", raw, flags=re.IGNORECASE)
    if m:
        suffix = m.group(1).strip()
        if suffix:
            return f"Glyma.{suffix}"
    return raw


def normalize_accession_key(value: str) -> str:
    # 统一 accession 比对键：去掉非字母数字，转大写
    return re.sub(r"[^A-Za-z0-9]", "", (value or "").strip()).upper()


def split_gene_aliases(gene_text: str) -> set[str]:
    raw = (gene_text or "").strip()
    if not raw:
        return set()

    aliases: set[str] = set()
    # 第一层：常见分隔符（; , / |）
    chunks = re.split(r"[;,/|]+", raw)
    for chunk in chunks:
        part = chunk.strip()
        if not part:
            continue
        # 第二层：有些记录把多个别名写在同一段里，用空格分隔
        for token in re.split(r"\s+", part):
            name = token.strip("()[]{}").strip()
            if not name:
                continue
            if len(name) < 2:
                continue
            if not re.search(r"[A-Za-z]", name):
                continue
            aliases.add(normalize_gene_name(name))

    return aliases


def extract_accession_from_header(header: str) -> str:
    # 支持两种常见 FASTA 标题：
    # 1) tr|A0A0R0E6H1|A0A0R0E6H1_SOYBN ...
    # 2) A0A0R0KCT9 Aurora kinase ...
    m_pipe = re.match(r"^[^|]*\|([^|]+)\|", header)
    if m_pipe:
        return m_pipe.group(1).strip()

    first_token = header.split()[0].strip()
    return first_token


def clean_sequence(seq_lines: list[str]) -> str:
    seq = "".join(line.strip() for line in seq_lines)
    seq = "".join(ch for ch in seq if ch.isalpha())
    return seq.upper()


def parse_fasta_to_accession_map(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"FASTA not found: {path}")

    accession_to_seq: dict[str, str] = {}
    current_header = ""
    seq_lines: list[str] = []

    def flush_one() -> None:
        nonlocal current_header, seq_lines
        if not current_header:
            return

        accession = extract_accession_from_header(current_header)
        key = normalize_accession_key(accession)
        protein = clean_sequence(seq_lines)
        if key and protein:
            accession_to_seq[key] = protein

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                flush_one()
                current_header = line[1:].strip()
                seq_lines = []
            else:
                seq_lines.append(line)
        flush_one()

    return accession_to_seq


def detect_column_name(headers: list[str], expected: str) -> str:
    # 优先精确匹配；否则按去空格小写匹配
    if expected in headers:
        return expected

    expected_norm = re.sub(r"\s+", "", expected).lower()
    for h in headers:
        if re.sub(r"\s+", "", h).lower() == expected_norm:
            return h

    raise ValueError(f"Column not found: {expected}. Available: {headers}")


def parse_gs_accession_gene_map(path: Path) -> dict[str, set[str]]:
    if not path.exists():
        raise FileNotFoundError(f"GS CSV not found: {path}")

    acc_to_genes: dict[str, set[str]] = defaultdict(set)

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("GS CSV has no header")

        acc_col = detect_column_name(reader.fieldnames, GS_ACCESSION_COLUMN)
        gene_col = detect_column_name(reader.fieldnames, GS_GENE_COLUMN)

        for row in reader:
            acc_raw = (row.get(acc_col) or "").strip()
            gene_raw = (row.get(gene_col) or "").strip()
            if not acc_raw or not gene_raw:
                continue

            key = normalize_accession_key(acc_raw)
            if not key:
                continue

            if KEEP_GS_GENE_CELL_AS_IS:
                acc_to_genes[key].add(gene_raw)
            else:
                genes = split_gene_aliases(gene_raw)
                if not genes:
                    gene = normalize_gene_name(gene_raw)
                    if gene:
                        acc_to_genes[key].add(gene)
                else:
                    acc_to_genes[key].update(genes)

    return acc_to_genes


def build_output_rows(accession_to_seq: dict[str, str], gs_map: dict[str, set[str]]) -> tuple[list[tuple[str, str]], list[str]]:
    rows: list[tuple[str, str]] = []
    missing_accessions: list[str] = []

    for acc_key in sorted(gs_map.keys()):
        protein = accession_to_seq.get(acc_key)
        if not protein:
            missing_accessions.append(acc_key)
            continue

        for gene_name in sorted(gs_map[acc_key]):
            rows.append((gene_name, protein))

    return rows, missing_accessions


def main() -> None:
    accession_to_seq = parse_fasta_to_accession_map(INPUT_FASTA)
    gs_map = parse_gs_accession_gene_map(INPUT_GS_CSV)
    rows, missing_accessions = build_output_rows(accession_to_seq, gs_map)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Gene name", "Protein"])
        writer.writerows(rows)

    print(f"Done: {INPUT_FASTA} + {INPUT_GS_CSV} -> {OUTPUT_CSV}")
    print(f"FASTA accessions: {len(accession_to_seq)}")
    print(f"GS accessions: {len(gs_map)}")
    print(f"Output rows (gene-expanded): {len(rows)}")
    print(f"Missing accessions in FASTA: {len(missing_accessions)}")

    if missing_accessions:
        preview = ", ".join(missing_accessions[:20])
        print(f"First missing accession keys: {preview}")


if __name__ == "__main__":
    main()
