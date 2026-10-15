(function () {
    const DEFAULT_SEARCH_MESSAGE = "Searching";
    const DEFAULT_DOWNLOAD_MESSAGE = "Preparing download";
    let hideTimer = 0;

    function feedbackNode() {
        let node = document.querySelector("[data-loading-feedback]");
        if (node) {
            return node;
        }

        node = document.createElement("div");
        node.className = "loading-feedback";
        node.dataset.loadingFeedback = "true";
        node.setAttribute("role", "status");
        node.setAttribute("aria-live", "polite");
        node.innerHTML = [
            '<span class="loading-feedback__spinner" aria-hidden="true"></span>',
            '<span class="loading-feedback__text"></span>',
        ].join("");
        document.body.appendChild(node);
        return node;
    }

    function showFeedback(message) {
        const node = feedbackNode();
        const text = node.querySelector(".loading-feedback__text");
        if (text) {
            text.textContent = message;
        }
        window.clearTimeout(hideTimer);
        node.classList.add("is-visible");
    }

    function hideFeedback(delay = 0) {
        window.clearTimeout(hideTimer);
        hideTimer = window.setTimeout(() => {
            const node = document.querySelector("[data-loading-feedback]");
            if (node) {
                node.classList.remove("is-visible");
            }
        }, delay);
    }

    function setControlLoading(control, loading, label) {
        if (!(control instanceof HTMLElement)) {
            return;
        }
        if (loading) {
            if (!control.dataset.loadingOriginalText) {
                control.dataset.loadingOriginalText = control.textContent || "";
            }
            control.classList.add("is-loading");
            control.setAttribute("aria-busy", "true");
            if (label) {
                control.textContent = label;
            }
            return;
        }

        control.classList.remove("is-loading");
        control.removeAttribute("aria-busy");
        if (control.dataset.loadingOriginalText !== undefined) {
            control.textContent = control.dataset.loadingOriginalText;
            delete control.dataset.loadingOriginalText;
        }
    }

    function filenameFromDisposition(disposition, fallback) {
        const header = String(disposition || "");
        const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
        if (utf8Match) {
            try {
                return decodeURIComponent(utf8Match[1].trim().replace(/^"|"$/g, ""));
            } catch (error) {
                return utf8Match[1].trim().replace(/^"|"$/g, "") || fallback;
            }
        }
        const plainMatch = header.match(/filename="?([^";]+)"?/i);
        return plainMatch ? plainMatch[1].trim() : fallback;
    }

    function downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename || "download.csv";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    function bindSearchForms() {
        const selector = "form.search-form, form.ptm-form, form.pager-controls, form.data-pager-form";
        document.querySelectorAll(selector).forEach((form) => {
            form.addEventListener("submit", (event) => {
                const submitter = event.submitter instanceof HTMLElement
                    ? event.submitter
                    : form.querySelector('button[type="submit"], input[type="submit"]');
                const message = form.dataset.loadingMessage || DEFAULT_SEARCH_MESSAGE;
                showFeedback(message);
                setControlLoading(submitter, true, submitter && submitter.classList.contains("pager-btn") ? "" : "Searching...");
            });
        });
    }

    function serverDownloadRequest(link) {
        const method = (link.dataset.downloadMethod || "GET").toUpperCase();
        const url = link.dataset.downloadUrl || link.href;
        const options = { credentials: "same-origin" };

        if (method === "POST") {
            const payload = {};
            if (link.dataset.downloadIdentifiers !== undefined) {
                payload.identifiers = link.dataset.downloadIdentifiers;
            }
            if (link.dataset.downloadSpecies !== undefined) {
                payload.species = link.dataset.downloadSpecies;
            }
            options.method = "POST";
            options.headers = { "Content-Type": "application/json" };
            options.body = JSON.stringify(payload);
        }

        return { url, options };
    }

    function bindServerDownloads() {
        document.querySelectorAll("a[data-server-download]").forEach((link) => {
            link.addEventListener("click", async (event) => {
                event.preventDefault();
                if (link.dataset.loadingActive === "true") {
                    return;
                }

                const message = link.dataset.loadingMessage || DEFAULT_DOWNLOAD_MESSAGE;
                const loadingLabel = link.dataset.loadingLabel || "Preparing...";
                link.dataset.loadingActive = "true";
                showFeedback(message);
                setControlLoading(link, true, loadingLabel);

                try {
                    const request = serverDownloadRequest(link);
                    const response = await fetch(request.url, request.options);
                    if (!response.ok) {
                        throw new Error(`Download failed with status ${response.status}`);
                    }
                    const blob = await response.blob();
                    const fallback = link.dataset.downloadFilename || "download.csv";
                    const filename = filenameFromDisposition(response.headers.get("Content-Disposition"), fallback);
                    downloadBlob(blob, filename);
                    showFeedback("Download is ready.");
                    hideFeedback(1400);
                } catch (error) {
                    console.error(error);
                    showFeedback("Download failed. Please try again.");
                    hideFeedback(3000);
                } finally {
                    delete link.dataset.loadingActive;
                    setControlLoading(link, false);
                }
            });
        });
    }

    bindSearchForms();
    bindServerDownloads();
})();
