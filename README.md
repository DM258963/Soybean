# Soybean PTM Viewer

Soybean PTM Viewer 是一个面向大豆与根瘤菌蛋白质翻译后修饰（PTM）数据的检索和分析平台。项目使用 FastAPI 提供 Web 服务，通过 PostgreSQL 管理 PTM 位点与蛋白序列，并集成 NCBI BLAST+ 完成本地序列比对。

## 功能

- 按基因名称、蛋白 accession 和转录本标识检索蛋白质
- 按修饰类型、氨基酸及位点组合查询 PTM 记录
- 支持大豆和根瘤菌数据集
- 使用 NCBI BLAST+ 完成本地蛋白序列比对
- 展示蛋白表达谱、修饰位点和统计结果
- 支持检索结果分页、排序与 CSV 导出
- 使用 Docker Compose 初始化 PostgreSQL 数据库

## 技术栈

- Python 3.10+
- FastAPI、Jinja2
- PostgreSQL、psycopg 3
- NCBI BLAST+
- Pandas、OpenPyXL
- Docker Compose

## 项目结构

```text
Soybean/
├── app.py                 # FastAPI 应用及检索服务
├── config.py              # 可选的运行配置
├── import_ptm_csv.py      # PostgreSQL 数据导入工具
├── initdb/                # 数据库初始化和迁移脚本
├── static/                # CSS、JavaScript 和图片资源
├── templates/             # Jinja2 页面模板
├── 数据处理/              # 原始数据预处理脚本
├── docker-compose.yml
└── requirements.txt
```

数据集、BLAST 索引、数据库文件和本地凭据不包含在公开仓库中。

## 本地运行

### 1. 创建环境

```bash
python -m venv .venv
```

Windows：

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux/macOS：

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

复制示例配置并设置本地数据库密码：

```powershell
Copy-Item .env.example .env
```

FastAPI 不会自动读取 `.env`。启动前需要将变量加载到当前终端，或在 IDE、容器及系统环境中配置同名变量。

### 3. 启动 PostgreSQL

```bash
docker compose up -d postgres
```

首次启动时，`initdb/` 中的 SQL 脚本会创建数据库结构。生产数据不随仓库发布，需要自行准备并导入。

### 4. 导入数据

```bash
python import_ptm_csv.py --gs-csv path/to/gs.csv --protein-csv path/to/protein_sequence.csv
```

GS 数据至少需要包含修饰类型、位点、氨基酸和基因名称字段；蛋白序列 CSV 需要包含 `Gene name` 与 `Protein` 两列。

### 5. 启动应用

```bash
python app.py
```

浏览器访问 `http://127.0.0.1:5000`。

## BLAST 配置

应用优先使用 `data/blastdb/` 下的本地 BLAST 数据库；如果索引不存在，可根据数据库中的蛋白序列在 `blastdb_cache/` 中生成缓存。两类目录都不会提交到 Git。

运行 BLAST 功能前，请安装 NCBI BLAST+ 并确保 `blastp` 与 `makeblastdb` 可通过系统 `PATH` 访问。

## 数据与隐私

公开仓库不包含以下内容：

- 原始 Excel、CSV、FASTA、RAW 或 TIFF 数据
- PostgreSQL 本地数据目录
- 自动生成的 BLAST 索引
- 云服务账号、数据库口令及其他本地凭据

提交代码前可运行以下命令确认待提交内容：

```bash
git status --short
git ls-files
```

## 数据来源

使用者需要确认数据集的授权范围，并在发布衍生结果时按照原始数据源要求进行引用。仓库仅提供数据处理、检索和分析代码。
