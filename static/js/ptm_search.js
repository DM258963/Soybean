(() => {
    function bindExpressionExample() {
        const input = document.getElementById("expression");
        const exampleText = document.querySelector("[data-expression-example]");
        if (!input || !exampleText) return;

        function syncExampleVisibility() {
            exampleText.hidden = input.value.trim().length > 0;
        }

        input.addEventListener("input", syncExampleVisibility);
        syncExampleVisibility();
    }

    function bindSegmentedControls() {
        document.querySelectorAll("[data-segmented-control]").forEach((control) => {
            const input = control.querySelector("input[type='hidden']");
            const buttons = Array.from(control.querySelectorAll(".segmented-option"));
            if (!(input instanceof HTMLInputElement) || !buttons.length) return;

            function setValue(value) {
                input.value = value;
                buttons.forEach((button) => {
                    const isActive = button.value === value;
                    button.classList.toggle("active", isActive);
                    button.setAttribute("aria-pressed", isActive ? "true" : "false");
                });
                input.dispatchEvent(new Event("change", { bubbles: true }));
            }

            buttons.forEach((button) => {
                button.addEventListener("click", () => setValue(button.value));
            });
        });
    }

    function safeFilename(value, fallback) {
        const cleaned = String(value || "")
            .trim()
            .replace(/[\\/:*?"<>|]+/g, "_")
            .replace(/\s+/g, "_");
        return cleaned || fallback;
    }

    function downloadBlob(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    function csvEscape(value) {
        const text = String(value ?? "");
        if (/[",\r\n]/.test(text)) {
            return `"${text.replace(/"/g, '""')}"`;
        }
        return text;
    }

    function tableToCsv(table) {
        const rows = Array.from(table.querySelectorAll("tr"));
        const pendingRowspans = [];
        return rows.map((row) => {
            const values = [];
            let colIndex = 0;
            while (pendingRowspans[colIndex] && pendingRowspans[colIndex].remaining > 0) {
                values.push(pendingRowspans[colIndex].text);
                pendingRowspans[colIndex].remaining -= 1;
                colIndex += 1;
            }

            Array.from(row.children).forEach((cell) => {
                if (cell.dataset.exportSkip === "true") return;
                while (pendingRowspans[colIndex] && pendingRowspans[colIndex].remaining > 0) {
                    values.push(pendingRowspans[colIndex].text);
                    pendingRowspans[colIndex].remaining -= 1;
                    colIndex += 1;
                }
                const text = cell.textContent.replace(/\s+/g, " ").trim();
                values.push(text);
                const rowspan = Number(cell.getAttribute("rowspan") || "1");
                if (rowspan > 1) {
                    pendingRowspans[colIndex] = { text, remaining: rowspan - 1 };
                }
                colIndex += Number(cell.getAttribute("colspan") || "1");
            });
            return values.map(csvEscape).join(",");
        }).join("\r\n");
    }

    bindSegmentedControls();
    bindExpressionExample();

    document.querySelectorAll("[data-download-table]").forEach((button) => {
        button.addEventListener("click", () => {
            const selector = button.dataset.downloadTable || "";
            const table = selector ? document.querySelector(selector) : null;
            if (!(table instanceof HTMLTableElement)) return;
            const filename = safeFilename(button.dataset.downloadFilename, "table.csv");
            downloadBlob(`\uFEFF${tableToCsv(table)}`, filename, "text/csv;charset=utf-8");
        });
    });
})();
