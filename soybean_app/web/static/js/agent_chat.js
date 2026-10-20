(function () {
    const STORAGE_KEY = "soybean.agent.chat.history.v1";
    const OPEN_KEY = "soybean.agent.chat.open.v1";
    const THREAD_KEY = "soybean.agent.thread.id.v1";
    const PENDING_INPUT_KEY = "soybean.agent.pending-input.v1";
    const WELCOME_MESSAGE = "Ask me to find soybean proteins, inspect PTM sites, compare records, or summarize the available evidence.";
    const MAX_HISTORY_ITEMS = 80;

    function createThreadId() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID();
        }
        const bytes = new Uint8Array(16);
        window.crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }

    function loadThreadId() {
        try {
            const existing = localStorage.getItem(THREAD_KEY);
            if (existing) return existing;
            const created = createThreadId();
            localStorage.setItem(THREAD_KEY, created);
            return created;
        } catch (error) {
            return createThreadId();
        }
    }

    let threadId = loadThreadId();
    let pendingInput = false;
    try {
        pendingInput = localStorage.getItem(PENDING_INPUT_KEY) === "1";
    } catch (error) {
        pendingInput = false;
    }

    function setPendingInput(required) {
        pendingInput = Boolean(required);
        try {
            localStorage.setItem(PENDING_INPUT_KEY, pendingInput ? "1" : "0");
        } catch (error) {
            // The current page can still resume even when storage is unavailable.
        }
    }

    const root = document.createElement("section");
    root.className = "agent-chat";
    root.setAttribute("aria-label", "Soybean Assistant");

    root.innerHTML = [
        '<button class="agent-chat__button" type="button" aria-label="Open Soybean Assistant" aria-expanded="false">',
        '  <svg class="agent-chat__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '    <path fill="currentColor" d="M4 5.5C4 3.57 5.57 2 7.5 2h9C18.43 2 20 3.57 20 5.5v7c0 1.93-1.57 3.5-3.5 3.5H12l-4.8 4.1A.75.75 0 0 1 6 19.53V16.9A3.5 3.5 0 0 1 4 13.74V5.5Zm3.5-2A2 2 0 0 0 5.5 5.5v8c0 1.1.9 2 2 2h.25v2.4l3.7-3.15h5.05a2 2 0 0 0 2-2V5.5a2 2 0 0 0-2-2h-9Z"/>',
        '  </svg>',
        "</button>",
        '<div class="agent-chat__panel" role="dialog" aria-modal="false" aria-label="Soybean Assistant">',
        '  <div class="agent-chat__header">',
        '    <div class="agent-chat__heading">',
        '      <h2 class="agent-chat__title">Soybean Assistant</h2>',
        '      <p class="agent-chat__status"><span class="agent-chat__status-dot" aria-hidden="true"></span>Agent Runtime online</p>',
        '    </div>',
        '    <div class="agent-chat__header-actions">',
        '      <button class="agent-chat__header-button agent-chat__clear" type="button" aria-label="Start a new conversation" title="New conversation">',
        '        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14M10 10v6m4-6v6"></path></svg>',
        '      </button>',
        '      <button class="agent-chat__header-button agent-chat__close" type="button" aria-label="Close Soybean Assistant" title="Close">',
        '        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"></path></svg>',
        '      </button>',
        '    </div>',
        "  </div>",
        '  <div class="agent-chat__body" aria-live="polite"></div>',
        '  <div class="agent-chat__form-wrap">',
        '    <form class="agent-chat__form">',
        '      <textarea class="agent-chat__input" rows="1" autocomplete="off" placeholder="Ask about a protein, PTM, motif, or sequence" aria-label="Message"></textarea>',
        '      <button class="agent-chat__send" type="submit" aria-label="Send">',
        '        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '          <path fill="currentColor" d="M3.4 20.4 21.2 12 3.4 3.6l.1 6.5L14.8 12 3.5 13.9l-.1 6.5Z"/>',
        "        </svg>",
        "      </button>",
        "    </form>",
        '    <p class="agent-chat__hint">Enter to send · Shift + Enter for a new line</p>',
        "  </div>",
        "</div>",
    ].join("");

    document.body.appendChild(root);

    const openButton = root.querySelector(".agent-chat__button");
    const closeButton = root.querySelector(".agent-chat__close");
    const clearButton = root.querySelector(".agent-chat__clear");
    const body = root.querySelector(".agent-chat__body");
    const form = root.querySelector(".agent-chat__form");
    const input = root.querySelector(".agent-chat__input");
    const sendButton = root.querySelector(".agent-chat__send");

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
            records: Array.isArray(entry.records) ? entry.records.slice(0, 5) : [],
        });
        saveHistory(history);
    }

    function setOpen(open) {
        root.classList.toggle("is-open", open);
        document.body.classList.toggle("agent-chat-open", open);
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

    function appendInlineMarkdown(container, value) {
        const text = String(value || "");
        const pattern = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
        let cursor = 0;
        let match;
        while ((match = pattern.exec(text)) !== null) {
            if (match.index > cursor) {
                container.appendChild(document.createTextNode(text.slice(cursor, match.index)));
            }
            const token = match[0];
            const element = document.createElement(token.startsWith("**") ? "strong" : "code");
            element.textContent = token.startsWith("**") ? token.slice(2, -2) : token.slice(1, -1);
            container.appendChild(element);
            cursor = match.index + token.length;
        }
        if (cursor < text.length) {
            container.appendChild(document.createTextNode(text.slice(cursor)));
        }
    }

    function tableCells(line) {
        return line
            .trim()
            .replace(/^\|/, "")
            .replace(/\|$/, "")
            .split("|")
            .map((cell) => cell.trim());
    }

    function isTableDivider(line) {
        const cells = tableCells(line);
        return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
    }

    function renderMarkdown(container, value) {
        const markdown = document.createElement("div");
        markdown.className = "agent-chat__markdown";
        const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
        let index = 0;

        while (index < lines.length) {
            const line = lines[index];
            if (!line.trim()) {
                index += 1;
                continue;
            }

            if (line.includes("|") && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
                const wrapper = document.createElement("div");
                wrapper.className = "agent-chat__table-wrap";
                const table = document.createElement("table");
                table.className = "agent-chat__table";
                const thead = document.createElement("thead");
                const headerRow = document.createElement("tr");
                tableCells(line).forEach((cell) => {
                    const th = document.createElement("th");
                    appendInlineMarkdown(th, cell);
                    headerRow.appendChild(th);
                });
                thead.appendChild(headerRow);
                table.appendChild(thead);

                const tbody = document.createElement("tbody");
                index += 2;
                while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
                    const row = document.createElement("tr");
                    tableCells(lines[index]).forEach((cell) => {
                        const td = document.createElement("td");
                        appendInlineMarkdown(td, cell);
                        row.appendChild(td);
                    });
                    tbody.appendChild(row);
                    index += 1;
                }
                table.appendChild(tbody);
                wrapper.appendChild(table);
                markdown.appendChild(wrapper);
                continue;
            }

            const headingMatch = line.match(/^#{1,3}\s+(.+)$/);
            if (headingMatch) {
                const level = Math.min(3, line.match(/^#+/)[0].length);
                const heading = document.createElement(`h${level}`);
                appendInlineMarkdown(heading, headingMatch[1]);
                markdown.appendChild(heading);
                index += 1;
                continue;
            }

            const unordered = /^[-*]\s+/.test(line);
            const ordered = /^\d+\.\s+/.test(line);
            if (unordered || ordered) {
                const list = document.createElement(ordered ? "ol" : "ul");
                const itemPattern = ordered ? /^\d+\.\s+(.+)$/ : /^[-*]\s+(.+)$/;
                while (index < lines.length) {
                    const itemMatch = lines[index].match(itemPattern);
                    if (!itemMatch) break;
                    const item = document.createElement("li");
                    appendInlineMarkdown(item, itemMatch[1]);
                    list.appendChild(item);
                    index += 1;
                }
                markdown.appendChild(list);
                continue;
            }

            const paragraphLines = [line.trim()];
            index += 1;
            while (
                index < lines.length &&
                lines[index].trim() &&
                !/^#{1,3}\s+/.test(lines[index]) &&
                !/^[-*]\s+/.test(lines[index]) &&
                !/^\d+\.\s+/.test(lines[index]) &&
                !(lines[index].includes("|") && index + 1 < lines.length && isTableDivider(lines[index + 1]))
            ) {
                paragraphLines.push(lines[index].trim());
                index += 1;
            }
            const paragraph = document.createElement("p");
            paragraphLines.forEach((paragraphLine, lineIndex) => {
                if (lineIndex) paragraph.appendChild(document.createElement("br"));
                appendInlineMarkdown(paragraph, paragraphLine);
            });
            markdown.appendChild(paragraph);
        }

        container.appendChild(markdown);
    }

    function appendMessage(role, text, options = {}) {
        const message = document.createElement("div");
        message.className = `agent-chat__message agent-chat__message--${role}`;
        if (role === "assistant") {
            renderMarkdown(message, text);
        } else {
            message.textContent = text;
        }
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
        meta.className = "agent-chat__meta";
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
        if (record.organism) parts.push(record.organism);
        if (record.gene_name && record.gene_name !== recordTitle(record)) parts.push(record.gene_name);
        if (record.identity_display) parts.push(`Identity ${record.identity_display}`);
        if (record.query_cover_display) parts.push(`Cover ${record.query_cover_display}`);
        if (record.e_value_display) parts.push(`E ${record.e_value_display}`);
        if (record.hit_label) parts.push(record.hit_label);
        if (record.ptm_position) parts.push(`Position ${record.ptm_position}`);
        return parts.join(" · ");
    }

    function appendRecords(container, records) {
        if (!Array.isArray(records) || records.length === 0) {
            return;
        }
        const list = document.createElement("div");
        list.className = "agent-chat__records";
        records.slice(0, 5).forEach((record) => {
            const item = document.createElement("article");
            item.className = "agent-chat__record";

            const head = document.createElement("div");
            head.className = "agent-chat__record-head";
            const identity = document.createElement("div");
            identity.className = "agent-chat__record-identity";
            const title = document.createElement("p");
            title.className = "agent-chat__record-title";
            title.textContent = recordTitle(record);
            identity.appendChild(title);

            if (record.download_url) {
                const download = document.createElement("a");
                download.className = "agent-chat__record-download";
                download.href = record.download_url;
                download.setAttribute("download", "");
                download.setAttribute("aria-label", `Download raw PTM data for ${recordTitle(record)}`);
                download.title = `Download ${recordTitle(record)} raw PTM data`;
                download.innerHTML = [
                    '<svg viewBox="0 0 24 24" aria-hidden="true">',
                    '<path d="M12 3v12m0 0 4-4m-4 4-4-4M5 18v2h14v-2"></path>',
                    "</svg>",
                    "<span>CSV</span>",
                ].join("");
                identity.appendChild(download);
            }
            head.appendChild(identity);

            if (record.total_sites !== undefined && record.total_sites !== "") {
                const badge = document.createElement("span");
                badge.className = "agent-chat__record-badge";
                badge.textContent = `${record.total_sites} PTM sites`;
                head.appendChild(badge);
            }
            item.appendChild(head);

            const text = document.createElement("p");
            text.className = "agent-chat__record-text";
            text.textContent = recordText(record) || "Matched record";
            item.appendChild(text);

            if (record.protein_description) {
                const description = document.createElement("p");
                description.className = "agent-chat__record-text";
                description.textContent = record.protein_description;
                item.appendChild(description);
            }

            if (record.ptm_summary) {
                const summary = document.createElement("p");
                summary.className = "agent-chat__record-summary";
                summary.textContent = record.ptm_summary;
                item.appendChild(summary);
            }

            if (record.detail_url) {
                const link = document.createElement("a");
                link.className = "agent-chat__link";
                link.href = record.detail_url;
                link.textContent = "View protein details";
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
        const existing = Array.from(document.querySelectorAll("link[data-agent-prefetch]"))
            .some((link) => link.dataset.agentPrefetch === url);
        if (!url || existing) {
            return;
        }
        const link = document.createElement("link");
        link.rel = "prefetch";
        link.href = url;
        link.dataset.agentPrefetch = url;
        document.head.appendChild(link);
    }

    function appendDetailLink(message, detailUrl) {
        if (!detailUrl) {
            return;
        }
        prefetchDetail(detailUrl);
        const link = document.createElement("a");
        link.className = "agent-chat__link";
        link.href = detailUrl;
        link.textContent = "View protein details";
        message.appendChild(link);
    }

    function appendAssistantResult(result) {
        const text = result.answer || result.message || "No response.";
        const detailUrl = firstDetailUrl(result);
        const records = Array.isArray(result.records) ? result.records : [];
        const message = appendMessage("assistant", text, { save: false });
        if (records.length) {
            appendRecords(message, records);
        } else {
            appendDetailLink(message, detailUrl);
        }
        const options = result.interrupt && Array.isArray(result.interrupt.options)
            ? result.interrupt.options
            : [];
        if (result.requires_input && options.length) {
            const choices = document.createElement("div");
            choices.className = "agent-chat__choices";
            options.forEach((option) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "agent-chat__choice";
                button.textContent = option;
                button.addEventListener("click", () => {
                    input.value = option;
                    input.focus();
                });
                choices.appendChild(button);
            });
            message.appendChild(choices);
        }
        pushHistory({ role: "assistant", text, detailUrl, records });
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
            if (entry.role === "assistant") {
                if (Array.isArray(entry.records) && entry.records.length) {
                    appendRecords(message, entry.records);
                } else if (entry.detailUrl) {
                    appendDetailLink(message, entry.detailUrl);
                }
            }
        });
        body.scrollTop = body.scrollHeight;
    }

    function appendWorkingMessage(text) {
        const message = document.createElement("div");
        message.className = "agent-chat__message agent-chat__message--status";
        const working = document.createElement("div");
        working.className = "agent-chat__working";
        const spinner = document.createElement("span");
        spinner.className = "agent-chat__spinner";
        spinner.setAttribute("aria-hidden", "true");
        const label = document.createElement("span");
        label.textContent = text;
        working.append(spinner, label);
        message.appendChild(working);
        body.appendChild(message);
        body.scrollTop = body.scrollHeight;
        return { message, label };
    }

    function resizeInput() {
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 124)}px`;
    }

    function startNewConversation() {
        try {
            sessionStorage.removeItem(STORAGE_KEY);
            localStorage.removeItem(THREAD_KEY);
            localStorage.removeItem(PENDING_INPUT_KEY);
        } catch (error) {
            // The visible conversation can still be reset without storage.
        }
        threadId = createThreadId();
        try {
            localStorage.setItem(THREAD_KEY, threadId);
        } catch (error) {
            // Continue with an in-memory thread id.
        }
        setPendingInput(false);
        body.replaceChildren();
        appendMessage("assistant", WELCOME_MESSAGE);
        input.value = "";
        resizeInput();
        input.focus();
    }

    function setLoading(loading) {
        input.disabled = loading;
        sendButton.disabled = loading;
    }

    async function postAgentStream(requestBody, onProgress) {
        const response = await fetch("/api/agent/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody),
        });
        if (!response.ok || !response.body) {
            throw new Error(`Agent stream failed with HTTP ${response.status}.`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        let finalResult = null;

        function consumeEvent(block) {
            if (!block || block.startsWith(":")) return;
            let eventName = "message";
            const dataLines = [];
            block.split(/\r?\n/).forEach((line) => {
                if (line.startsWith("event:")) {
                    eventName = line.slice(6).trim();
                } else if (line.startsWith("data:")) {
                    dataLines.push(line.slice(5).trimStart());
                }
            });
            if (!dataLines.length) return;
            const data = JSON.parse(dataLines.join("\n"));
            if (eventName === "progress" || eventName === "start") {
                onProgress(data.message || "Working");
            } else if (eventName === "result") {
                finalResult = data;
            } else if (eventName === "error") {
                const streamError = new Error(data.answer || data.message || "Agent request failed.");
                streamError.agentResult = data;
                throw streamError;
            }
        }

        while (true) {
            const { value, done } = await reader.read();
            buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
            const blocks = buffer.split(/\r?\n\r?\n/);
            buffer = blocks.pop() || "";
            blocks.forEach(consumeEvent);
            if (done) break;
        }
        if (buffer.trim()) consumeEvent(buffer.trim());
        if (!finalResult) throw new Error("Agent stream ended without a result.");
        return finalResult;
    }

    openButton.addEventListener("click", () => {
        setOpen(!root.classList.contains("is-open"));
    });

    closeButton.addEventListener("click", () => setOpen(false));
    clearButton.addEventListener("click", startNewConversation);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && root.classList.contains("is-open")) {
            setOpen(false);
        }
    });

    input.addEventListener("input", resizeInput);
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const query = input.value.trim();
        if (!query) {
            return;
        }

        appendMessage("user", query);
        input.value = "";
        resizeInput();
        setLoading(true);
        const pending = appendWorkingMessage("Starting agent workflow...");

        try {
            const requestBody = pendingInput
                ? { thread_id: threadId, resume: query }
                : { query, thread_id: threadId, limit: 8, site_limit: 8 };
            const result = await postAgentStream(requestBody, (message) => {
                pending.label.textContent = `${message}...`;
            });
            if (result.thread_id) {
                threadId = result.thread_id;
                try {
                    localStorage.setItem(THREAD_KEY, threadId);
                } catch (error) {
                    // The active page can continue even when storage is unavailable.
                }
            }
            setPendingInput(
                result.requires_input === true || (pendingInput && result.ok === false)
            );
            pending.message.remove();
            appendAssistantResult(result);
        } catch (error) {
            pending.message.remove();
            if (error.agentResult) {
                appendAssistantResult(error.agentResult);
            } else {
                appendMessage("assistant", "I could not process that. Please try again.");
            }
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
