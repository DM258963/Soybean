(function () {
    const STORAGE_KEY = "soybean.hermes.chat.history.v1";
    const OPEN_KEY = "soybean.hermes.chat.open.v1";
    const WELCOME_MESSAGE = "Hi, I can answer questions and look up Soybean PTM data when needed.";
    const MAX_HISTORY_ITEMS = 80;

    const root = document.createElement("section");
    root.className = "hermes-chat";
    root.setAttribute("aria-label", "Soybean Assistant");

    root.innerHTML = [
        '<button class="hermes-chat__button" type="button" aria-label="Open Soybean Assistant" aria-expanded="false">',
        '  <svg class="hermes-chat__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '    <path fill="currentColor" d="M4 5.5C4 3.57 5.57 2 7.5 2h9C18.43 2 20 3.57 20 5.5v7c0 1.93-1.57 3.5-3.5 3.5H12l-4.8 4.1A.75.75 0 0 1 6 19.53V16.9A3.5 3.5 0 0 1 4 13.74V5.5Zm3.5-2A2 2 0 0 0 5.5 5.5v8c0 1.1.9 2 2 2h.25v2.4l3.7-3.15h5.05a2 2 0 0 0 2-2V5.5a2 2 0 0 0-2-2h-9Z"/>',
        '  </svg>',
        "</button>",
        '<div class="hermes-chat__panel" role="dialog" aria-modal="false" aria-label="Soybean Assistant">',
        '  <div class="hermes-chat__header">',
        '    <h2 class="hermes-chat__title">Soybean Assistant</h2>',
        '    <button class="hermes-chat__close" type="button" aria-label="Close Soybean Assistant">&times;</button>',
        "  </div>",
        '  <div class="hermes-chat__body" aria-live="polite"></div>',
        '  <form class="hermes-chat__form">',
        '    <input class="hermes-chat__input" type="text" autocomplete="off" placeholder="Ask a question, gene, motif, or sequence" aria-label="Message">',
        '    <button class="hermes-chat__send" type="submit" aria-label="Send">',
        '      <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '        <path fill="currentColor" d="M3.4 20.4 21.2 12 3.4 3.6l.1 6.5L14.8 12 3.5 13.9l-.1 6.5Z"/>',
        "      </svg>",
        "    </button>",
        "  </form>",
        "</div>",
    ].join("");

    document.body.appendChild(root);

    const openButton = root.querySelector(".hermes-chat__button");
    const closeButton = root.querySelector(".hermes-chat__close");
    const body = root.querySelector(".hermes-chat__body");
    const form = root.querySelector(".hermes-chat__form");
    const input = root.querySelector(".hermes-chat__input");
    const sendButton = root.querySelector(".hermes-chat__send");

    function loadHistory() {
        try {
            const parsed = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "[]");
            return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
            return [];
        }
    }

    function saveHistory(history) {
        try {
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-MAX_HISTORY_ITEMS)));
        } catch (error) {
            // Ignore storage quota or private-mode failures; chat still works for the current page.
        }
    }

    function pushHistory(entry) {
        const history = loadHistory();
        history.push({
            role: entry.role,
            text: entry.text || "",
            detailUrl: entry.detailUrl || "",
        });
        saveHistory(history);
    }

    function setOpen(open) {
        root.classList.toggle("is-open", open);
        openButton.setAttribute("aria-expanded", open ? "true" : "false");
        try {
            sessionStorage.setItem(OPEN_KEY, open ? "1" : "0");
        } catch (error) {
            // Non-critical UI state.
        }
        if (open) {
            input.focus();
        }
    }

    function appendMessage(role, text, options = {}) {
        const message = document.createElement("div");
        message.className = `hermes-chat__message hermes-chat__message--${role}`;
        message.textContent = text;
        body.appendChild(message);
        body.scrollTop = body.scrollHeight;
        if (options.save !== false) {
            pushHistory({ role, text, detailUrl: options.detailUrl || "" });
        }
        return message;
    }

    function appendMeta(container, text) {
        if (!text) {
            return;
        }
        const meta = document.createElement("div");
        meta.className = "hermes-chat__meta";
        meta.textContent = text;
        container.appendChild(meta);
    }

    function recordTitle(record) {
        return (
            record.display_id ||
            record.gene_name ||
            record.protein_accession ||
            record.ptm_types ||
            "Record"
        );
    }

    function recordText(record) {
        const parts = [];
        if (record.protein_accession) parts.push(record.protein_accession);
        if (record.total_sites !== undefined && record.total_sites !== "") parts.push(`${record.total_sites} PTM sites`);
        if (record.ptm_summary) parts.push(record.ptm_summary);
        if (record.identity_display) parts.push(`Identity ${record.identity_display}`);
        if (record.query_cover_display) parts.push(`Cover ${record.query_cover_display}`);
        if (record.e_value_display) parts.push(`E ${record.e_value_display}`);
        if (record.hit_label) parts.push(record.hit_label);
        if (record.ptm_position) parts.push(`Position ${record.ptm_position}`);
        if (record.protein_description) parts.push(record.protein_description);
        return parts.join(" | ");
    }

    function appendRecords(container, records) {
        if (!Array.isArray(records) || records.length === 0) {
            return;
        }
        const list = document.createElement("div");
        list.className = "hermes-chat__records";
        records.slice(0, 5).forEach((record) => {
            const item = document.createElement("article");
            item.className = "hermes-chat__record";

            const title = document.createElement("p");
            title.className = "hermes-chat__record-title";
            title.textContent = recordTitle(record);
            item.appendChild(title);

            const text = document.createElement("p");
            text.className = "hermes-chat__record-text";
            text.textContent = recordText(record) || "Matched record";
            item.appendChild(text);

            if (record.detail_url) {
                const link = document.createElement("a");
                link.className = "hermes-chat__link";
                link.href = record.detail_url;
                link.textContent = "Open detail";
                item.appendChild(link);
            }

            list.appendChild(item);
        });
        container.appendChild(list);
    }

    function firstDetailUrl(result) {
        const records = Array.isArray(result.records) ? result.records : [];
        const matched = records.find((record) => record.detail_url);
        return matched ? matched.detail_url : "";
    }

    function prefetchDetail(url) {
        const existing = Array.from(document.querySelectorAll("link[data-hermes-prefetch]"))
            .some((link) => link.dataset.hermesPrefetch === url);
        if (!url || existing) {
            return;
        }
        const link = document.createElement("link");
        link.rel = "prefetch";
        link.href = url;
        link.dataset.hermesPrefetch = url;
        document.head.appendChild(link);
    }

    function appendDetailLink(message, detailUrl) {
        if (!detailUrl) {
            return;
        }
        prefetchDetail(detailUrl);
        const link = document.createElement("a");
        link.className = "hermes-chat__link";
        link.href = detailUrl;
        link.textContent = "Open detail";
        message.appendChild(link);
    }

    function appendAssistantResult(result) {
        const text = result.answer || result.message || "No response.";
        const detailUrl = firstDetailUrl(result);
        const message = appendMessage("assistant", text, { detailUrl });
        appendDetailLink(message, detailUrl);
        body.scrollTop = body.scrollHeight;
    }

    function restoreHistory() {
        const history = loadHistory();
        if (!history.length) {
            appendMessage("assistant", WELCOME_MESSAGE);
            return;
        }
        history.forEach((entry) => {
            if (!entry || !entry.role || !entry.text) {
                return;
            }
            const message = appendMessage(entry.role, entry.text, { save: false });
            if (entry.role === "assistant" && entry.detailUrl) {
                appendDetailLink(message, entry.detailUrl);
            }
        });
        body.scrollTop = body.scrollHeight;
    }

    function setLoading(loading) {
        input.disabled = loading;
        sendButton.disabled = loading;
    }

    openButton.addEventListener("click", () => {
        setOpen(!root.classList.contains("is-open"));
    });

    closeButton.addEventListener("click", () => setOpen(false));

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const query = input.value.trim();
        if (!query) {
            return;
        }

        appendMessage("user", query);
        input.value = "";
        setLoading(true);
        const pending = appendMessage("assistant", "Thinking...", { save: false });

        try {
            const response = await fetch("/api/hermes/query", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    query,
                    limit: 8,
                    site_limit: 8,
                }),
            });
            const result = await response.json();
            pending.remove();
            appendAssistantResult(result);
        } catch (error) {
            pending.remove();
            appendMessage("assistant", "I could not process that. Please try again.");
        } finally {
            setLoading(false);
            input.focus();
        }
    });

    restoreHistory();
    try {
        setOpen(sessionStorage.getItem(OPEN_KEY) === "1");
    } catch (error) {
        // Leave closed when sessionStorage is unavailable.
    }
})();
