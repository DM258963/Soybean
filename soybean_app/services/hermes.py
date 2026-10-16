from soybean_app.services import *

HERMES_TOOL_RECORD_LIMIT_DEFAULT = int(os.getenv("HERMES_TOOL_RECORD_LIMIT_DEFAULT", "10"))
HERMES_TOOL_RECORD_LIMIT_MAX = int(os.getenv("HERMES_TOOL_RECORD_LIMIT_MAX", "50"))
HERMES_BLAST_SEQUENCE_MAX = int(os.getenv("HERMES_BLAST_SEQUENCE_MAX", "5000"))
HERMES_OLLAMA_ENABLED = _env_bool("HERMES_OLLAMA_ENABLED", True)
HERMES_OLLAMA_BASE_URL = os.getenv("HERMES_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
HERMES_OLLAMA_MODEL = os.getenv("HERMES_OLLAMA_MODEL", "qwen3:8b")
HERMES_OLLAMA_TIMEOUT = float(os.getenv("HERMES_OLLAMA_TIMEOUT", "30"))
HERMES_OLLAMA_ROUTER_TIMEOUT = float(os.getenv("HERMES_OLLAMA_ROUTER_TIMEOUT", "8"))
HERMES_OLLAMA_SUMMARY_TIMEOUT = float(os.getenv("HERMES_OLLAMA_SUMMARY_TIMEOUT", "12"))
HERMES_CHAT_PROVIDER = os.getenv("HERMES_CHAT_PROVIDER", "ollama").strip().lower()
HERMES_CHAT_ENABLED = _env_bool("HERMES_CHAT_ENABLED", HERMES_OLLAMA_ENABLED)
HERMES_ASSISTANT_ENABLED = _env_bool("HERMES_ASSISTANT_ENABLED", HERMES_CHAT_ENABLED)
HERMES_CHAT_BASE_URL = os.getenv("HERMES_CHAT_BASE_URL", HERMES_OLLAMA_BASE_URL).rstrip("/")
HERMES_CHAT_MODEL = os.getenv("HERMES_CHAT_MODEL", HERMES_OLLAMA_MODEL)
HERMES_CHAT_API_KEY = os.getenv("HERMES_CHAT_API_KEY", "")
HERMES_AGENT_DIR = PACKAGE_DIR / os.getenv("HERMES_AGENT_DIR", "hermes_agent")
HERMES_AGENT_FILE = HERMES_AGENT_DIR / "agent.md"
HERMES_SKILL_DIR = HERMES_AGENT_DIR / "skills"
HERMES_SKILL_FILES = [
    "protein_search.md",
    "ptm_search.md",
    "blast_search.md",
    "general_chat.md",
]


def _require_hermes_assistant_enabled() -> None:
    if not HERMES_ASSISTANT_ENABLED:
        raise HTTPException(status_code=404, detail="Soybean Assistant is disabled.")


HERMES_ROUTER_TEST_CASES = [
    {
        "message": "查一下 GLYMA_10G142500",
        "expected_tool": "protein_search",
        "expected_species": "glycine_max",
    },
    {
        "message": "I1LAY3 有哪些修饰位点？",
        "expected_tool": "protein_search",
        "expected_species": "glycine_max",
    },
    {
        "message": "soybean GLYMA_10G142500 的 PTM 概况",
        "expected_tool": "protein_search",
        "expected_species": "glycine_max",
    },
    {
        "message": "查询 Bradyrhizobium diazoefficiens 的 nifD",
        "expected_tool": "protein_search",
        "expected_species": "bradyrhizobium_diazoefficiens",
    },
    {
        "message": "查一下 motif S[ph]P 的 PTM 模式",
        "expected_tool": "ptm_search",
        "expected_species": "glycine_max",
    },
    {
        "message": "PTM expression K[ub] 限定肽段",
        "expected_tool": "ptm_search",
        "expected_species": "glycine_max",
    },
    {
        "message": "blast MAAAAAAAAGGGGGGGGGGSSSSSSSSSS",
        "expected_tool": "blast_search",
        "expected_species": "glycine_max",
    },
    {
        "message": "用 Bradyrhizobium 序列 MTEYKLVVVGAGGVGKSALTIQLIQNHFVDEYDPTIEDSYRKQ 做 blast",
        "expected_tool": "blast_search",
        "expected_species": "bradyrhizobium_diazoefficiens",
    },
    {
        "message": "hello",
        "expected_tool": "none",
        "expected_species": "glycine_max",
    },
    {
        "message": "what is PTM?",
        "expected_tool": "none",
        "expected_species": "glycine_max",
    },
    {
        "message": "我要查询大豆的ptm应该使用哪个功能",
        "expected_tool": "none",
        "expected_species": "glycine_max",
    },
    {
        "message": "查某个大豆基因有哪些修饰位点应该用哪个功能",
        "expected_tool": "none",
        "expected_species": "glycine_max",
    },
    {
        "message": "我要查 PTM motif 应该去哪里查",
        "expected_tool": "none",
        "expected_species": "glycine_max",
    },
    {
        "message": "氨基酸序列找相似蛋白用哪个模块",
        "expected_tool": "none",
        "expected_species": "glycine_max",
    },
    {
        "message": "蛋白表达谱在哪查",
        "expected_tool": "none",
        "expected_species": "glycine_max",
    },
    {
        "message": "批量蛋白列表分析应该使用哪个功能",
        "expected_tool": "none",
        "expected_species": "glycine_max",
    },
    {
        "message": "原始数据表在哪里下载",
        "expected_tool": "none",
        "expected_species": "glycine_max",
    },
]


def _hermes_ollama_endpoint() -> str:
    base = HERMES_CHAT_BASE_URL.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _hermes_ollama_native_endpoint() -> str:
    base = HERMES_CHAT_BASE_URL.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/api/chat"


def _hermes_call_ollama(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 512,
    timeout: float = HERMES_OLLAMA_TIMEOUT,
    json_mode: bool = False,
) -> str:
    if not HERMES_CHAT_ENABLED or HERMES_CHAT_PROVIDER in {"", "none", "off", "disabled"}:
        raise RuntimeError("Hermes chat model integration is disabled.")
    provider = HERMES_CHAT_PROVIDER

    if provider == "ollama":
        payload = {
            "model": HERMES_CHAT_MODEL,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"
        request = urllib.request.Request(
            _hermes_ollama_native_endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            message = body.get("message") if isinstance(body, dict) else {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content.strip()
        except Exception as native_exc:
            native_error = native_exc
        else:
            native_error = RuntimeError("Ollama returned an empty native response.")

        host = urllib.parse.urlparse(HERMES_CHAT_BASE_URL).hostname or ""
        if host in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError(f"Ollama native request failed: {native_error}") from native_error
    else:
        native_error = None

    fallback_payload = {
        "model": HERMES_CHAT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        fallback_payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if HERMES_CHAT_API_KEY:
        headers["Authorization"] = f"Bearer {HERMES_CHAT_API_KEY}"
    request = urllib.request.Request(
        _hermes_ollama_endpoint(),
        data=json.dumps(fallback_payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as fallback_exc:
        if provider == "ollama":
            raise RuntimeError(f"Ollama request failed: native={native_error}; openai={fallback_exc}") from fallback_exc
        raise RuntimeError(f"Chat provider request failed: {fallback_exc}") from fallback_exc
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("Ollama returned no choices.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Ollama returned an empty message.")
    return content.strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(clean[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


def _hermes_read_text_file(path: Path, fallback: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return fallback.strip()


def _hermes_skill_paths() -> list[Path]:
    preferred = [HERMES_SKILL_DIR / name for name in HERMES_SKILL_FILES]
    preferred_existing = [path for path in preferred if path.exists()]
    preferred_names = {path.name for path in preferred}
    extra = sorted(
        path for path in HERMES_SKILL_DIR.glob("*.md")
        if path.name not in preferred_names
    ) if HERMES_SKILL_DIR.exists() else []
    return [*preferred_existing, *extra]


def _hermes_skill_docs() -> str:
    docs: list[str] = []
    for path in _hermes_skill_paths():
        content = _hermes_read_text_file(path)
        if content:
            docs.append(f"<!-- skill: {path.name} -->\n{content}")
    return "\n\n".join(docs)


def _hermes_router_prompt() -> str:
    agent_text = _hermes_read_text_file(
        HERMES_AGENT_FILE,
        (
            "You are the website assistant for Soybean PTM Viewer.\n"
            "Return exactly one JSON object when routing.\n"
            "Use only these tool values: protein_search, ptm_search, blast_search, none."
        ),
    )
    skill_text = _hermes_skill_docs()
    if not skill_text:
        skill_text = (
            "# protein_search\nUse for gene, protein accession, transcript id, or PTM overview.\n\n"
            "# ptm_search\nUse for PTM motif or expression pattern searches.\n\n"
            "# blast_search\nUse for amino-acid sequence similarity search.\n\n"
            "# general_chat\nUse tool value `none` for greetings, help, and explanations."
        )
    return (
        f"{agent_text}\n\n"
        "## Available Skills\n\n"
        f"{skill_text}\n\n"
        "Route the next user message according to the agent and skill instructions."
    )


def _hermes_agent_text() -> str:
    return _hermes_read_text_file(
        HERMES_AGENT_FILE,
        "You are the website assistant for Soybean PTM Viewer.",
    )


def _hermes_normalize_species_from_text(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ["bradyrhizobium", "diazoefficiens", "rhizobium", "nif"]):
        return "bradyrhizobium_diazoefficiens"
    return DEFAULT_SPECIES


def _hermes_sequence_from_text(text: str) -> str:
    candidates = re.findall(r"[ACDEFGHIKLMNPQRSTVWYXBZUOJ]{10,}", text.upper())
    if not candidates:
        return ""
    return max(candidates, key=len)


def _hermes_looks_like_sequence(text: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    clean = "".join(text.split()).upper()
    return len(clean) >= 20 and bool(re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWYXBZUOJ]+", clean))


def _hermes_identifier_candidate(text: str) -> str:
    patterns = [
        r"(?<![A-Za-z0-9])GLYMA[._-]?\d+G\d+(?:[._-]?P)?(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])\d+G\d+(?:[._-]?P)?(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])[A-Z][0-9][A-Z0-9]{3,9}(?![A-Za-z0-9])",
    ]
    for pattern in patterns:
        matched = re.search(pattern, text, flags=re.IGNORECASE)
        if matched:
            return matched.group(0)

    stopwords = {
        "search", "query", "protein", "gene", "ptm", "blast", "soybean",
        "glycine", "max", "bradyrhizobium", "diazoefficiens", "rhizobium",
    }
    for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{1,14}\b", text):
        if token.lower() in stopwords:
            continue
        if any(ch.isupper() for ch in token[1:]) or any(ch.isdigit() for ch in token):
            return token
    return ""


def _hermes_looks_like_identifier(text: str) -> bool:
    return bool(_hermes_identifier_candidate(text))


def _hermes_looks_like_ptm_query(text: str) -> bool:
    clean = text.strip()
    lowered = clean.lower()
    if "[" in clean and "]" in clean:
        return True
    ptm_terms = [
        "motif", "ptm expression", "modification pattern",
        "\u4fee\u9970\u6a21\u5f0f", "\u4f4d\u70b9\u6a21\u5f0f", "\u6a21\u4f53",
    ]
    return any(term in lowered or term in clean for term in ptm_terms)


def _hermes_looks_like_tool_query(text: str) -> bool:
    return (
        _hermes_looks_like_sequence(text)
        or _hermes_looks_like_ptm_query(text)
        or _hermes_looks_like_identifier(text)
    )


def _hermes_contains_any(text: str, markers: list[str]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _hermes_wants_navigation_recommendation(text: str) -> bool:
    return _hermes_contains_any(
        text,
        [
            "which function", "which feature", "which module", "which page",
            "where can i", "where should i", "what should i use", "how should i search",
            "where to search", "where to download", "where is", "where are", "use for",
            "入口", "模块", "哪个功能", "哪一个功能",
            "那个功能", "哪项功能", "用什么功能", "使用什么功能", "使用哪个功能",
            "应该用", "应该使用", "在哪查", "哪里查", "去哪里查", "从哪里查",
            "在哪", "哪里", "下载", "提交", "上传", "浏览",
        ],
    )


def _hermes_is_general_message(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return True
    lowered = clean.lower()
    if _hermes_wants_navigation_recommendation(clean):
        return True
    if _hermes_looks_like_tool_query(clean):
        return False

    exact_messages = {
        "hi", "hello", "hey", "thanks", "thank you", "ok", "okay",
        "\u4f60\u597d", "\u60a8\u597d", "\u55e8", "\u8c22\u8c22",
        "\u597d\u7684", "\u65e9\u4e0a\u597d", "\u4e0b\u5348\u597d", "\u665a\u4e0a\u597d",
    }
    if lowered in exact_messages:
        return True

    general_markers = [
        "what is", "what are", "how to", "how do", "help", "explain", "meaning",
        "who are you", "what can you do", "function", "feature", "website", "webpage", "page",
        "\u662f\u4ec0\u4e48", "\u4ec0\u4e48\u610f\u601d", "\u600e\u4e48\u7528",
        "\u5982\u4f55", "\u5e2e\u52a9", "\u4ecb\u7ecd", "\u4f60\u80fd\u505a\u4ec0\u4e48",
        "\u7f51\u9875", "\u9875\u9762", "\u529f\u80fd", "\u5e72\u4ec0\u4e48", "\u505a\u4ec0\u4e48",
        "\u5982\u4f55\u67e5\u8be2", "\u600e\u4e48\u67e5", "\u4f7f\u7528", "\u54ea\u4e2a",
        "\u54ea\u4e00\u4e2a", "\u6a21\u5757", "\u5165\u53e3",
    ]
    if any(marker in lowered or marker in clean for marker in general_markers):
        return True
    return False


def _hermes_navigation_answer(message: str) -> str:
    if not _hermes_wants_navigation_recommendation(message):
        return ""

    lowered = message.lower()
    text = message
    if _hermes_contains_any(
        text,
        [
            "blast", "sequence", "similarity", "homolog", "alignment",
            "序列", "氨基酸", "相似", "同源", "比对",
        ],
    ):
        return (
            "如果你有一段氨基酸序列，建议用 BLAST/Sequence Search。"
            "它会在本地蛋白库里找相似蛋白，并保留命中的 PTM 注释，方便看同源蛋白的修饰位点。"
        )

    if _hermes_contains_any(
        text,
        [
            "expression", "abundance", "profile", "quantification", "proteome",
            "表达", "丰度", "表达谱", "定量", "蛋白组", "w4", "w12",
        ],
    ):
        return (
            "如果你要看蛋白表达量、丰度变化或不同阶段的表达谱，建议用 Proteome。"
            "输入基因名、蛋白 accession 或序列后，可以查看对应的表达 profile。"
        )

    if _hermes_contains_any(
        text,
        [
            "list", "analysis", "enrichment", "statistics", "protein list",
            "列表", "批量", "富集", "统计", "分析", "蛋白列表",
        ],
    ):
        return (
            "如果你有一批蛋白或基因列表，建议用 Analysis/List Analysis。"
            "它适合做列表级 PTM 统计、类型分布和后续结果导出。"
        )

    if _hermes_contains_any(text, ["submit", "upload", "contribute", "提交", "上传", "贡献"]):
        return (
            "如果你要提交新的 PTM 数据，建议用 Data/Submit Data。"
            "那里适合上传数据和查看提交模板。"
        )

    if _hermes_contains_any(
        text,
        [
            "download", "raw", "csv", "table", "dataset", "data",
            "下载", "原始数据", "数据表", "数据集", "表格",
        ],
    ):
        return (
            "如果你想看或下载原始数据表，建议用 Data/Raw Data。"
            "如果只是浏览已经整理好的 PTM 记录，可以用 Browse。"
        )

    if _hermes_contains_any(
        text,
        [
            "browse", "curated", "records", "catalog", "浏览", "记录", "条目", "整理好的", "已整理",
        ],
    ):
        return (
            "如果你只是想浏览已经整理好的 PTM 记录，建议用 Browse。"
            "如果你已经有具体基因、蛋白或 motif，再分别用 Protein Search 或 PTM Search。"
        )

    if _hermes_contains_any(text, ["about", "citation", "contact", "version", "关于", "引用", "联系", "版本"]):
        return (
            "如果你要查看项目介绍、版本信息、引用方式或联系方式，建议用 About。"
            "数据查询类问题再回到 Protein Search、PTM Search、Proteome 或 BLAST。"
        )

    if _hermes_contains_any(
        text,
        [
            "motif", "pattern", "crosstalk", "co-occurring", "ptm expression",
            "表达式", "模式", "模体", "基序", "修饰类型", "共修饰", "共现", "组合",
        ],
    ):
        return (
            "如果你要按 PTM motif、修饰类型、修饰模式或共修饰组合来筛选，建议用 PTM Search。"
            "例如 K[ub]、S[ph]P 这类表达式适合放在 PTM Search 里查。"
        )

    protein_markers = [
        "gene", "protein", "accession", "identifier", "transcript", "uniprot",
        "glyma", "nif", "基因", "蛋白", "编号", "登录号", "转录本",
        "修饰位点", "位点", "ptm概况", "ptm 概况", "有哪些修饰", "某个",
    ]
    if _hermes_contains_any(text, protein_markers):
        return (
            "如果你要查某个大豆基因或蛋白的 PTM 概况、修饰位点和序列标注，建议用 Protein Search。"
            "可以输入基因名、UniProt accession、转录本 ID 或短编号。"
        )

    if "ptm" in lowered or "修饰" in text:
        return (
            "查询大豆 PTM 要看你的问题类型：查某个基因/蛋白有哪些 PTM 位点，用 Protein Search；"
            "按修饰类型、motif 或共修饰模式筛选，用 PTM Search；"
            "如果输入的是氨基酸序列找相似蛋白，用 BLAST/Sequence Search。"
        )

    return (
        "如果你要查单个基因或蛋白，用 Protein Search；查 PTM motif、修饰类型或共修饰模式，用 PTM Search；"
        "粘贴氨基酸序列找相似蛋白，用 BLAST/Sequence Search；查表达谱用 Proteome；批量列表分析用 Analysis。"
    )


def _hermes_general_fallback_answer(message: str) -> str:
    clean = message.strip().lower()
    greeting_messages = {
        "hi", "hello", "hey", "\u4f60\u597d", "\u60a8\u597d", "\u55e8",
        "\u65e9\u4e0a\u597d", "\u4e0b\u5348\u597d", "\u665a\u4e0a\u597d",
    }
    if clean in greeting_messages:
        return (
            "\u4f60\u597d\uff01\u6211\u53ef\u4ee5\u5e2e\u4f60\u67e5\u8be2\u57fa\u56e0/"
            "\u86cb\u767d\u3001PTM \u4f4d\u70b9\u6216 BLAST \u5e8f\u5217\uff0c"
            "\u4e5f\u53ef\u4ee5\u7b80\u8981\u89e3\u91ca\u9875\u9762\u91cc\u7684\u5b57\u6bb5\u3002"
        )
    navigation_answer = _hermes_navigation_answer(message)
    if navigation_answer:
        return navigation_answer
    page_help_markers = [
        "website", "webpage", "page", "function", "feature", "how to use",
        "\u7f51\u9875", "\u9875\u9762", "\u529f\u80fd", "\u600e\u4e48\u7528",
        "\u5e72\u4ec0\u4e48", "\u505a\u4ec0\u4e48", "\u5982\u4f55\u67e5\u8be2", "\u600e\u4e48\u67e5",
    ]
    if any(marker in clean or marker in message for marker in page_help_markers):
        return (
            "\u8fd9\u4e2a\u9875\u9762\u53ef\u4ee5\u67e5\u8be2\u5927\u8c46\u53ca\u76f8\u5173\u6839\u7624\u83cc\u7684"
            "\u57fa\u56e0/\u86cb\u767d PTM \u6982\u51b5\u3001\u4fee\u9970\u4f4d\u70b9\u548c PTM motif\uff0c"
            "\u4e5f\u652f\u6301\u8f93\u5165\u6c28\u57fa\u9178\u5e8f\u5217\u505a BLAST \u76f8\u4f3c\u6027\u67e5\u8be2\u3002"
        )
    return (
        "\u6211\u53ef\u4ee5\u8fdb\u884c\u7b80\u77ed\u5bf9\u8bdd\u548c\u89e3\u91ca\uff0c"
        "\u9700\u8981\u6570\u636e\u65f6\u518d\u81ea\u52a8\u67e5\u8be2\u57fa\u56e0/"
        "\u86cb\u767d\u3001PTM motif \u6216 BLAST \u5e8f\u5217\u3002"
    )


def _hermes_identifier_from_text(text: str) -> str:
    return _hermes_identifier_candidate(text) or text.strip()


def _hermes_route_with_ollama(message: str, payload: dict[str, Any]) -> dict[str, Any]:
    prompt = _hermes_router_prompt()
    content = _hermes_call_ollama(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": message},
        ],
        temperature=0,
        max_tokens=240,
        timeout=HERMES_OLLAMA_ROUTER_TIMEOUT,
        json_mode=True,
    )
    routed = _extract_json_object(content)
    tool = str(routed.get("tool") or "").strip().lower()
    arguments = routed.get("arguments") if isinstance(routed.get("arguments"), dict) else {}
    aliases = {
        "protein": "protein_search",
        "gene": "protein_search",
        "ptm": "ptm_search",
        "blast": "blast_search",
        "sequence": "blast_search",
        "general": "none",
        "help": "none",
    }
    tool = aliases.get(tool, tool)
    if tool not in {"protein_search", "ptm_search", "blast_search", "none"}:
        raise ValueError(f"Unsupported routed tool: {tool}")

    if tool == "protein_search":
        candidate = _hermes_identifier_candidate(str(arguments.get("query") or message))
        if not candidate:
            tool = "none"
            arguments = {"question": message}
        else:
            arguments["query"] = candidate
    elif tool == "ptm_search" and not _hermes_looks_like_ptm_query(str(arguments.get("expression") or message)):
        tool = "none"
        arguments = {"question": message}
    elif tool == "blast_search" and not (_hermes_sequence_from_text(str(arguments.get("sequence") or message)) or "blast" in message.lower()):
        tool = "none"
        arguments = {"question": message}

    species = normalize_species_key(str(arguments.get("species") or payload.get("species") or _hermes_normalize_species_from_text(message)))
    arguments["species"] = species

    if tool == "protein_search":
        raw_identifier = str(arguments.get("query") or payload.get("query") or message).strip()
        arguments["query"] = _hermes_identifier_from_text(raw_identifier)
    elif tool == "ptm_search":
        arguments["expression"] = str(arguments.get("expression") or payload.get("expression") or payload.get("query") or message).strip()
    elif tool == "blast_search":
        raw_sequence = str(arguments.get("sequence") or payload.get("sequence") or payload.get("query") or message).strip()
        arguments["sequence"] = _hermes_sequence_from_text(raw_sequence) or raw_sequence
    else:
        arguments["question"] = str(arguments.get("question") or message).strip()
    return {"tool": tool, "arguments": arguments, "router": "ollama"}


def _hermes_route_with_rules(payload: dict[str, Any]) -> dict[str, Any]:
    message = _hermes_payload_text(payload, "message", "query", "text", "identifier", "gene_name", "expression", "sequence")
    tool = _hermes_detect_tool(payload)
    species = _hermes_payload_species(payload)
    if not payload.get("species"):
        species = _hermes_normalize_species_from_text(message)
    if tool == "none":
        return {"tool": tool, "arguments": {"question": message, "species": species}, "router": "rules"}
    if tool == "protein_search":
        return {"tool": tool, "arguments": {"query": _hermes_identifier_from_text(message), "species": species}, "router": "rules"}
    if tool == "ptm_search":
        return {"tool": tool, "arguments": {"expression": message, "species": species}, "router": "rules"}
    return {"tool": tool, "arguments": {"sequence": _hermes_sequence_from_text(message) or message, "species": species}, "router": "rules"}


def _hermes_payload_text(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _hermes_payload_limit(payload: dict[str, Any], default: int = HERMES_TOOL_RECORD_LIMIT_DEFAULT) -> int:
    try:
        raw_value = int(payload.get("limit", default))
    except (TypeError, ValueError):
        raw_value = default
    return _clamp_int(raw_value, 1, HERMES_TOOL_RECORD_LIMIT_MAX)


def _hermes_payload_species(payload: dict[str, Any]) -> str:
    return normalize_species_key(str(payload.get("species") or DEFAULT_SPECIES))


def _hermes_species_label(species: str) -> str:
    return str(get_species_option(species).get("display", species))


def _hermes_round(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, digits)
    return value


def _hermes_site_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "position": row.get("Position"),
        "amino_acid": row.get("Amino acid", ""),
        "ptm_types": row.get("PTM types", ""),
        "subcellular_localization": row.get("Subcellular localization", ""),
        "w4_mean_linear": _hermes_round(row.get("W4 mean linear")),
        "w12_mean_linear": _hermes_round(row.get("W12 mean linear")),
        "w12_w4_ratio": _hermes_round(row.get("W12/W4 ratio")),
        "w12_w4_p_value": _hermes_round(row.get("W12/W4 P value")),
        "w12_w4_type": row.get("W12/W4 Type", ""),
    }


def _hermes_protein_service(payload: dict[str, Any]) -> dict[str, Any]:
    query = _hermes_payload_text(payload, "query", "identifier", "gene_name")
    if not query:
        raise ValueError("Missing query.")

    species = _hermes_payload_species(payload)
    limit = _hermes_payload_limit(payload)
    site_limit = _hermes_payload_limit({"limit": payload.get("site_limit", limit)}, default=limit)
    tokens = split_identifier_query(query) or [query]
    if len(tokens) > 1 and not bool(payload.get("_allow_multiple_identifiers")):
        raise ValueError(MULTI_IDENTIFIER_ADMIN_ONLY_MESSAGE)
    summary_rows = build_protein_summary_rows(tokens[:limit], species)
    records: list[dict[str, Any]] = []

    for row in summary_rows[:limit]:
        select_key = str(row.get("select_key") or row.get("gene_name") or row.get("protein_accession") or row.get("query") or "")
        records.append(
            {
                "query": row.get("query", ""),
                "display_id": row.get("display_id", ""),
                "gene_name": row.get("gene_name", ""),
                "protein_accession": row.get("protein_accession", ""),
                "organism": row.get("organism", ""),
                "protein_description": row.get("protein_description", ""),
                "transcript_id": row.get("transcript_id", ""),
                "gene_names": row.get("gene_names", ""),
                "modification_type_count": row.get("modification_type_count", 0),
                "total_sites": row.get("total_sites", 0),
                "ptm_summary": row.get("ptm_summary", ""),
                "status": row.get("status", ""),
                "has_result": bool(row.get("has_result")),
                "detail_url": (
                    "/search/protein?"
                    + urllib.parse.urlencode(
                        {
                            "tab": "identifier",
                            "view": "detail",
                            "species": species,
                            "gene_name": select_key,
                        }
                    )
                    if select_key
                    else ""
                ),
            }
        )

    detail: dict[str, Any] = {}
    if len(tokens) == 1:
        matched_rows = keep_primary_target_rows(fetch_sites_for_identifier(tokens[0], species))
        result_rows, result_meta = build_result_rows_and_meta(matched_rows)
        if result_rows:
            detail = {
                "meta": result_meta,
                "sites": [_hermes_site_record(row) for row in result_rows[:site_limit]],
                "site_count": len(result_rows),
                "sites_truncated": len(result_rows) > site_limit,
            }

    matched_count = sum(1 for row in records if row.get("has_result"))
    return {
        "ok": True,
        "tool": "protein_search",
        "query": query,
        "species": species,
        "species_label": _hermes_species_label(species),
        "summary": {
            "submitted_identifiers": len(tokens),
            "matched_records": matched_count,
            "returned_records": len(records),
        },
        "message": (
            f"Found {matched_count} matched protein record(s) for {query}."
            if matched_count
            else f"No protein/PTM record found for {query} in {_hermes_species_label(species)}."
        ),
        "records": records,
        "detail": detail,
    }


def _hermes_ptm_service(payload: dict[str, Any]) -> dict[str, Any]:
    expression = _hermes_payload_text(payload, "expression", "query")
    if not expression:
        raise ValueError("Missing expression.")

    species = _hermes_payload_species(payload)
    limit = _hermes_payload_limit(payload)
    sequence_length = _clamp_int(int(payload.get("sequence_length", 10) or 10), 3, 30)
    representative_only = bool(payload.get("representative_only", True))
    peptides_unique = bool(payload.get("peptides_unique", False))
    parsed, parse_error = parse_ptm_search_expression(expression)
    if parse_error or not parsed:
        return {
            "ok": False,
            "tool": "ptm_search",
            "query": expression,
            "species": species,
            "message": parse_error or "Unable to parse PTM search expression.",
            "records": [],
        }

    raw_matches, summary = run_ptm_expression_search(
        parsed,
        sequence_length=sequence_length,
        representative_only=representative_only,
        peptides_unique=peptides_unique,
        max_results=min(PTM_SEARCH_MAX_RESULTS, max(limit, 1)),
        species=species,
    )
    site_rows = build_ptm_site_rows(raw_matches)
    records = [
        {
            "gene_name": row.get("gene_name", ""),
            "protein_accession": row.get("protein_accession", ""),
            "protein_description": row.get("protein_description", ""),
            "organism": row.get("organism", ""),
            "ptm_position": row.get("ptm_position"),
            "hit_aa": row.get("hit_aa", ""),
            "hit_label": row.get("hit_label", ""),
            "left_context": row.get("left_context", ""),
            "right_context": row.get("right_context", ""),
            "motif_start": row.get("motif_start"),
            "motif_end": row.get("motif_end"),
        }
        for row in site_rows[:limit]
    ]
    return {
        "ok": True,
        "tool": "ptm_search",
        "query": expression,
        "species": species,
        "species_label": _hermes_species_label(species),
        "summary": {
            **summary,
            "returned_records": len(records),
            "total_site_rows": len(site_rows),
            "records_truncated": len(site_rows) > limit,
        },
        "message": (
            f"Found {summary.get('matched_sites', 0)} matched PTM site(s) across "
            f"{summary.get('matched_proteins', 0)} protein(s)."
            if site_rows
            else f'No PTM records matched "{expression}" in {_hermes_species_label(species)}.'
        ),
        "records": records,
    }


def _hermes_blast_service(payload: dict[str, Any]) -> dict[str, Any]:
    sequence = _hermes_payload_text(payload, "sequence", "query")
    normalized_sequence = normalize_sequence_input(sequence)
    if not normalized_sequence:
        raise ValueError("Missing sequence.")
    if len(normalized_sequence) < 10:
        raise ValueError("Sequence is too short. Please input at least 10 amino acids.")
    if len(normalized_sequence) > HERMES_BLAST_SEQUENCE_MAX:
        raise ValueError(f"Sequence is too long for the chat API. Limit is {HERMES_BLAST_SEQUENCE_MAX} amino acids.")

    species = _hermes_payload_species(payload)
    limit = _hermes_payload_limit({"limit": payload.get("max_hits", payload.get("limit", BLAST_DEFAULT_MAX_HITS))}, default=BLAST_DEFAULT_MAX_HITS)
    identity_min = _clamp_float(float(payload.get("identity_min", BLAST_DEFAULT_IDENTITY_MIN) or BLAST_DEFAULT_IDENTITY_MIN), 0, 100)
    e_value_max = _clamp_float(float(payload.get("e_value_max", BLAST_DEFAULT_E_VALUE_MAX) or BLAST_DEFAULT_E_VALUE_MAX), 0, 1000)
    query_cover_min = _clamp_float(float(payload.get("query_cover_min", BLAST_DEFAULT_QUERY_COVER_MIN) or BLAST_DEFAULT_QUERY_COVER_MIN), 0, 100)
    blast_rows, blast_summary = build_blast_summary_rows(
        normalized_sequence,
        species=species,
        max_hits=limit,
        identity_min=identity_min,
        e_value_max=e_value_max,
        query_cover_min=query_cover_min,
    )
    records = [
        {
            "display_id": row.get("display_id", ""),
            "gene_name": row.get("gene_name", ""),
            "protein_accession": row.get("protein_accession", ""),
            "organism": row.get("organism", ""),
            "protein_description": row.get("protein_description", ""),
            "total_sites": row.get("total_sites", "0"),
            "ptm_types": row.get("ptm_types", ""),
            "identity_display": row.get("identity_display", ""),
            "query_cover_display": row.get("query_cover_display", ""),
            "e_value_display": row.get("e_value_display", ""),
            "bit_score_display": row.get("bit_score_display", ""),
            "alignment_length": row.get("alignment_length", ""),
            "detail_url": (
                "/search/blast/detail?"
                + urllib.parse.urlencode(
                    {
                        "species": species,
                        "identifier": row.get("select_key") or row.get("gene_name") or row.get("protein_accession") or "",
                        "sequence": normalized_sequence,
                        "max_hits": str(limit),
                        "identity_min": str(identity_min),
                        "e_value_max": str(e_value_max),
                        "query_cover_min": str(query_cover_min),
                    }
                )
            ),
        }
        for row in blast_rows
    ]
    return {
        "ok": True,
        "tool": "blast_search",
        "species": species,
        "species_label": _hermes_species_label(species),
        "summary": blast_summary,
        "message": (
            f"Found {len(records)} BLAST hit(s) in {_hermes_species_label(species)}."
            if records
            else f"No BLAST hits passed the selected thresholds in {_hermes_species_label(species)}."
        ),
        "records": records,
    }


def _hermes_detect_tool(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("tool") or payload.get("intent") or "").strip().lower()
    aliases = {
        "protein": "protein_search",
        "protein_search": "protein_search",
        "gene": "protein_search",
        "gene_search": "protein_search",
        "ptm": "ptm_search",
        "ptm_search": "ptm_search",
        "motif": "ptm_search",
        "blast": "blast_search",
        "blast_search": "blast_search",
        "sequence": "blast_search",
        "none": "none",
        "general": "none",
        "chat": "none",
        "help": "none",
    }
    if explicit in aliases:
        return aliases[explicit]

    query = _hermes_payload_text(payload, "message", "query", "text", "expression", "sequence")
    if _hermes_is_general_message(query):
        return "none"
    lowered = query.lower()
    if "blast" in lowered or _hermes_looks_like_sequence(query):
        return "blast_search"
    if _hermes_looks_like_ptm_query(query):
        return "ptm_search"
    if _hermes_looks_like_identifier(query):
        return "protein_search"
    return "none"


def _hermes_query_payload(payload: dict[str, Any]) -> dict[str, Any]:
    message = _hermes_payload_text(payload, "message", "query", "text", "identifier", "gene_name", "expression", "sequence")
    if payload.get("tool") or payload.get("intent"):
        route = _hermes_route_with_rules(payload)
    elif _hermes_is_general_message(message):
        route = _hermes_route_with_rules(payload)
    else:
        try:
            route = _hermes_route_with_ollama(message, payload)
        except Exception:
            route = _hermes_route_with_rules(payload)

    tool = str(route.get("tool") or "protein_search")
    arguments = route.get("arguments") if isinstance(route.get("arguments"), dict) else {}
    routed_payload = {**payload, **arguments}
    routed_payload.setdefault("limit", payload.get("limit", HERMES_TOOL_RECORD_LIMIT_DEFAULT))
    routed_payload.setdefault("site_limit", payload.get("site_limit", HERMES_TOOL_RECORD_LIMIT_DEFAULT))

    if tool == "none":
        return _hermes_general_answer(message)
    if tool == "protein_search":
        routed_payload.setdefault("query", message)
        result = _hermes_protein_service(routed_payload)
        result["router"] = route.get("router", "rules")
        return result
    if tool == "ptm_search":
        routed_payload.setdefault("expression", message)
        result = _hermes_ptm_service(routed_payload)
        result["router"] = route.get("router", "rules")
        return result
    routed_payload.setdefault("sequence", message)
    result = _hermes_blast_service(routed_payload)
    result["router"] = route.get("router", "rules")
    return result


def _hermes_general_answer(message: str) -> dict[str, Any]:
    fallback = _hermes_general_fallback_answer(message)
    answer = fallback
    page_help_markers = [
        "website", "webpage", "page", "function", "feature", "how to use",
        "\u7f51\u9875", "\u9875\u9762", "\u529f\u80fd", "\u600e\u4e48\u7528",
        "\u5e72\u4ec0\u4e48", "\u505a\u4ec0\u4e48", "\u5982\u4f55\u67e5\u8be2", "\u600e\u4e48\u67e5",
    ]
    simple_general = message.strip().lower() in {
        "hi", "hello", "hey", "\u4f60\u597d", "\u60a8\u597d", "\u55e8",
        "\u65e9\u4e0a\u597d", "\u4e0b\u5348\u597d", "\u665a\u4e0a\u597d",
    } or _hermes_wants_navigation_recommendation(message) or any(
        marker in message.strip().lower() or marker in message for marker in page_help_markers
    )
    if HERMES_CHAT_ENABLED and message and not simple_general:
        try:
            answer = _hermes_call_ollama(
                [
                    {
                        "role": "system",
                        "content": (
                            f"{_hermes_agent_text()}\n\n"
                            "Answer in the user's language. Keep it short. "
                            "Do not claim database results unless a result context is provided."
                        ),
                    },
                    {"role": "user", "content": message},
                ],
                temperature=0.2,
                max_tokens=260,
                timeout=HERMES_OLLAMA_SUMMARY_TIMEOUT,
            )
        except Exception:
            answer = fallback
    return {
        "ok": True,
        "tool": "none",
        "query": message,
        "summary": {},
        "message": answer,
        "answer": answer,
        "records": [],
    }


def _hermes_compact_answer(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return str(result.get("message") or "No result.")

    tool = str(result.get("tool") or "")
    records = result.get("records") if isinstance(result.get("records"), list) else []
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}

    if tool == "protein_search":
        if not records:
            return str(result.get("message") or "No matched protein record was found.")
        first = next((record for record in records if record.get("has_result")), records[0])
        name = str(first.get("display_id") or first.get("gene_name") or first.get("protein_accession") or result.get("query") or "").strip()
        accession = str(first.get("protein_accession") or "").strip()
        total_sites = first.get("total_sites", 0)
        parts = [f"Found {name}"]
        if accession and accession != name:
            parts.append(f"accession {accession}")
        if total_sites not in {"", None}:
            parts.append(f"{total_sites} PTM site(s)")
        return ". ".join(parts) + "."

    if tool == "ptm_search":
        matched_sites = summary.get("matched_sites", 0)
        matched_proteins = summary.get("matched_proteins", 0)
        if not records:
            return str(result.get("message") or "No matching PTM site was found.")
        first = records[0]
        first_hit = str(first.get("gene_name") or first.get("protein_accession") or "").strip()
        site = first.get("ptm_position")
        label = str(first.get("hit_label") or "").strip()
        return (
            f"Found {matched_sites} matched PTM site(s) across {matched_proteins} protein(s). "
            f"First hit: {first_hit} at position {site} {label}."
        )

    if tool == "blast_search":
        matched_hits = summary.get("matched_hits", len(records))
        if not records:
            return str(result.get("message") or "No BLAST hit passed the selected thresholds.")
        first = records[0]
        name = str(first.get("display_id") or first.get("gene_name") or first.get("protein_accession") or "top hit").strip()
        identity = str(first.get("identity_display") or "").strip()
        e_value = str(first.get("e_value_display") or "").strip()
        sites = str(first.get("total_sites") or "").strip()
        parts = [f"Found {matched_hits} BLAST hit(s). Top hit: {name}"]
        if identity:
            parts.append(f"identity {identity}")
        if e_value:
            parts.append(f"E-value {e_value}")
        if sites:
            parts.append(f"{sites} PTM site(s)")
        return ". ".join(parts) + "."

    return str(result.get("message") or "Done.")


def _hermes_answer_context(result: dict[str, Any]) -> dict[str, Any]:
    context = {
        "ok": result.get("ok"),
        "message": result.get("message"),
        "tool": result.get("tool"),
        "query": result.get("query"),
        "species_label": result.get("species_label"),
        "summary": result.get("summary", {}),
        "records": [],
        "detail": {},
    }
    records = result.get("records") if isinstance(result.get("records"), list) else []
    context["records"] = records[:3]
    detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}
    if detail:
        context["detail"] = {
            "meta": detail.get("meta", {}),
            "site_count": detail.get("site_count", 0),
            "sites": (detail.get("sites") or [])[:5],
        }
    return context


def _hermes_summarized_answer(user_message: str, result: dict[str, Any]) -> str:
    fallback = _hermes_compact_answer(result)
    if not HERMES_CHAT_ENABLED or not result.get("ok"):
        return fallback
    try:
        return _hermes_call_ollama(
            [
                {
                    "role": "system",
                    "content": (
                        f"{_hermes_agent_text()}\n\n"
                        "Answer the user's question using only the provided query result JSON. "
                        "Do not expose internal tool names, routing, JSON, or species selectors. "
                        "Keep the answer concise: 1-3 short sentences. "
                        "If the result contains no records, say that no matching record was found and suggest a more specific identifier or motif. "
                        "Use the user's language."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User question:\n{user_message}\n\n"
                        f"Query result JSON:\n{json.dumps(_hermes_answer_context(result), ensure_ascii=False)}"
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=320,
            timeout=HERMES_OLLAMA_SUMMARY_TIMEOUT,
        )
    except Exception:
        return fallback


__all__ = [name for name in globals() if not name.startswith("__")]
