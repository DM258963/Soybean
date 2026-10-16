(() => {
    function safeFilename(value, fallback) {
        const cleaned = String(value || "")
            .trim()
            .replace(/[\\/:*?"<>|]+/g, "_")
            .replace(/\s+/g, "_");
        return cleaned || fallback;
    }

    function downloadBlob(content, filename, mimeType) {
        const blob = content instanceof Blob ? content : new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    const pngCrcTable = (() => {
        const table = new Uint32Array(256);
        for (let index = 0; index < 256; index += 1) {
            let crc = index;
            for (let bit = 0; bit < 8; bit += 1) {
                crc = (crc & 1) ? (0xEDB88320 ^ (crc >>> 1)) : (crc >>> 1);
            }
            table[index] = crc >>> 0;
        }
        return table;
    })();

    function pngCrc32(bytes) {
        let crc = 0xFFFFFFFF;
        for (let index = 0; index < bytes.length; index += 1) {
            crc = pngCrcTable[(crc ^ bytes[index]) & 0xFF] ^ (crc >>> 8);
        }
        return (crc ^ 0xFFFFFFFF) >>> 0;
    }

    function writeUint32(bytes, offset, value) {
        bytes[offset] = (value >>> 24) & 0xFF;
        bytes[offset + 1] = (value >>> 16) & 0xFF;
        bytes[offset + 2] = (value >>> 8) & 0xFF;
        bytes[offset + 3] = value & 0xFF;
    }

    function buildPngChunk(type, data) {
        const typeBytes = new TextEncoder().encode(type);
        const chunk = new Uint8Array(12 + data.length);
        writeUint32(chunk, 0, data.length);
        chunk.set(typeBytes, 4);
        chunk.set(data, 8);
        const crc = pngCrc32(chunk.slice(4, 8 + data.length));
        writeUint32(chunk, 8 + data.length, crc);
        return chunk;
    }

    async function addPngDpiMetadata(blob, dpi) {
        const source = new Uint8Array(await blob.arrayBuffer());
        const pixelsPerMeter = Math.round(dpi / 0.0254);
        const physData = new Uint8Array(9);
        writeUint32(physData, 0, pixelsPerMeter);
        writeUint32(physData, 4, pixelsPerMeter);
        physData[8] = 1;
        const physChunk = buildPngChunk("pHYs", physData);
        const output = new Uint8Array(source.length + physChunk.length);
        const insertAt = 33;
        output.set(source.slice(0, insertAt), 0);
        output.set(physChunk, insertAt);
        output.set(source.slice(insertAt), insertAt + physChunk.length);
        return new Blob([output], { type: "image/png" });
    }

    function svgToPngBlob(svgText, width, height) {
        return new Promise((resolve, reject) => {
            const svgBlob = new Blob([svgText], { type: "image/svg+xml;charset=utf-8" });
            const url = URL.createObjectURL(svgBlob);
            const image = new Image();
            image.onload = () => {
                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;
                const context = canvas.getContext("2d");
                if (!context) {
                    URL.revokeObjectURL(url);
                    reject(new Error("Canvas is not available."));
                    return;
                }
                context.fillStyle = "#ffffff";
                context.fillRect(0, 0, width, height);
                context.drawImage(image, 0, 0, width, height);
                URL.revokeObjectURL(url);
                canvas.toBlob((blob) => {
                    if (blob) resolve(blob);
                    else reject(new Error("PNG export failed."));
                }, "image/png");
            };
            image.onerror = () => {
                URL.revokeObjectURL(url);
                reject(new Error("SVG render failed."));
            };
            image.src = url;
        });
    }

    function csvEscape(value) {
        const text = String(value ?? "");
        if (/[",\r\n]/.test(text)) {
            return `"${text.replace(/"/g, '""')}"`;
        }
        return text;
    }

    function wrapSequenceForCsvCell(sequence, lineWidth = 80) {
        const clean = String(sequence || "").replace(/\s+/g, "");
        if (!clean) return "";
        const chunks = [];
        for (let index = 0; index < clean.length; index += lineWidth) {
            chunks.push(clean.slice(index, index + lineWidth));
        }
        return chunks.join("\n");
    }

    function tableToCsv(table) {
        const rows = Array.from(table.querySelectorAll("tr")).filter((row) => !row.hidden && row.dataset.exportSkip !== "true");
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
                const exportCell = cell.cloneNode(true);
                exportCell.querySelectorAll(".sort-icon, .column-filter-btn, .column-filter-menu").forEach((node) => node.remove());
                const text = exportCell.textContent.replace(/\s+/g, " ").trim();
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

    function bindTableDownloads() {
        document.querySelectorAll("[data-download-table]").forEach((button) => {
            button.addEventListener("click", () => {
                const selector = button.dataset.downloadTable || "";
                const table = selector ? document.querySelector(selector) : null;
                if (!(table instanceof HTMLTableElement)) return;
                const filename = safeFilename(button.dataset.downloadFilename, "table.csv");
                const prefixRows = [];
                const proteinSequence = (button.dataset.proteinSequence || "").trim();
                if (proteinSequence) {
                    prefixRows.push(["Protein sequence", wrapSequenceForCsvCell(proteinSequence)].map(csvEscape).join(","));
                    prefixRows.push("");
                }
                const csvBody = tableToCsv(table);
                const csvText = prefixRows.length ? `${prefixRows.join("\r\n")}\r\n${csvBody}` : csvBody;
                downloadBlob(`\uFEFF${csvText}`, filename, "text/csv;charset=utf-8");
            });
        });
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

    function bindCollapsibleSearch() {
        document.querySelectorAll("[data-collapsible-search]").forEach((workspace) => {
            const toggle = workspace.querySelector("[data-search-toggle]");
            const panel = workspace.querySelector("[data-search-panel]");
            if (!(toggle instanceof HTMLButtonElement) || !(panel instanceof HTMLElement)) return;

            toggle.addEventListener("click", () => {
                const willExpand = panel.hidden;
                panel.hidden = !willExpand;
                toggle.setAttribute("aria-expanded", willExpand ? "true" : "false");
                toggle.textContent = willExpand
                    ? (toggle.dataset.collapseLabel || "Hide search")
                    : (toggle.dataset.expandLabel || "Modify search");
                if (willExpand) {
                    const field = panel.querySelector("textarea, input:not([type='hidden'])");
                    if (field instanceof HTMLElement) field.focus();
                }
            });
        });
    }

    function bindSortableTables() {
        document.querySelectorAll("table[data-sortable-table]").forEach((table) => {
            const tbody = table.querySelector("tbody");
            if (!tbody) return;

            Array.from(tbody.querySelectorAll("tr")).forEach((row, index) => {
                row.dataset.sortOriginalIndex = String(index);
            });

            const buttons = Array.from(table.querySelectorAll(".sort-header[data-sort-index]"));

            function getCellValue(row, index) {
                const cell = row.children[index];
                if (!cell) return "";
                return (cell.dataset.sortValue ?? cell.textContent ?? "").trim();
            }

            function updateSortIcons(activeButton, direction) {
                buttons.forEach((button) => {
                    const icon = button.querySelector(".sort-icon");
                    const th = button.closest("th");
                    if (button === activeButton) {
                        if (icon) icon.textContent = direction === "asc" ? "↑" : "↓";
                        if (th) th.setAttribute("aria-sort", direction === "asc" ? "ascending" : "descending");
                    } else {
                        if (icon) icon.textContent = "↕";
                        if (th) th.removeAttribute("aria-sort");
                    }
                });
            }

            buttons.forEach((button) => {
                button.addEventListener("click", () => {
                    const index = Number(button.dataset.sortIndex || "-1");
                    if (!Number.isInteger(index) || index < 0) return;

                    const previousIndex = table.dataset.sortIndex || "";
                    const nextDirection = previousIndex === String(index) && table.dataset.sortDirection === "asc" ? "desc" : "asc";
                    const sortType = button.dataset.sortType || "text";
                    const rows = Array.from(tbody.querySelectorAll("tr"));

                    rows.sort((left, right) => {
                        const leftRaw = getCellValue(left, index);
                        const rightRaw = getCellValue(right, index);
                        const leftMissing = leftRaw === "" || leftRaw === "-";
                        const rightMissing = rightRaw === "" || rightRaw === "-";

                        if (leftMissing && rightMissing) {
                            return Number(left.dataset.sortOriginalIndex || 0) - Number(right.dataset.sortOriginalIndex || 0);
                        }
                        if (leftMissing) return 1;
                        if (rightMissing) return -1;

                        let comparison = 0;
                        if (sortType === "number") {
                            const leftNumber = Number(leftRaw);
                            const rightNumber = Number(rightRaw);
                            comparison = leftNumber - rightNumber;
                        } else {
                            comparison = leftRaw.localeCompare(rightRaw, undefined, { numeric: true, sensitivity: "base" });
                        }

                        if (comparison === 0) {
                            comparison = Number(left.dataset.sortOriginalIndex || 0) - Number(right.dataset.sortOriginalIndex || 0);
                        }
                        return nextDirection === "asc" ? comparison : -comparison;
                    });

                    rows.forEach((row) => tbody.appendChild(row));
                    table.dataset.sortIndex = String(index);
                    table.dataset.sortDirection = nextDirection;
                    updateSortIcons(button, nextDirection);
                });
            });
        });
    }

    function bindTableFilters() {
        let menuId = 0;

        document.querySelectorAll("table[data-filterable-table]").forEach((table) => {
            const tbody = table.querySelector("tbody");
            if (!tbody) return;

            const rows = Array.from(tbody.querySelectorAll("tr"));
            const filterButtons = Array.from(table.querySelectorAll("[data-column-filter][data-filter-index]"));
            const activeFilters = new Map();
            const menus = [];
            const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

            const emptyRow = document.createElement("tr");
            emptyRow.className = "table-filter-empty";
            emptyRow.dataset.exportSkip = "true";
            emptyRow.hidden = true;
            const emptyCell = document.createElement("td");
            emptyCell.colSpan = table.querySelectorAll("thead th").length || 1;
            emptyCell.textContent = "No sites match the selected filters.";
            emptyRow.appendChild(emptyCell);
            tbody.appendChild(emptyRow);

            const status = document.createElement("div");
            status.className = "table-filter-status";
            status.hidden = true;
            status.setAttribute("aria-live", "polite");

            const statusText = document.createElement("span");
            const clearFiltersButton = document.createElement("button");
            clearFiltersButton.type = "button";
            clearFiltersButton.textContent = "Clear filters";
            status.append(statusText, clearFiltersButton);
            table.before(status);

            function getCellValue(row, index) {
                const cell = row.children[index];
                if (!cell) return "";
                return String(cell.dataset.filterValue ?? cell.textContent ?? "").trim();
            }

            function updateButtonStates() {
                filterButtons.forEach((button) => {
                    const index = Number(button.dataset.filterIndex || "-1");
                    const isActive = activeFilters.has(index);
                    button.classList.toggle("is-active", isActive);
                    button.setAttribute("aria-label", `${isActive ? "Change" : "Filter"} ${button.dataset.filterLabel || "column"}${isActive ? " (filter active)" : ""}`);
                });
            }

            function applyFilters() {
                let visibleCount = 0;
                rows.forEach((row) => {
                    const isVisible = Array.from(activeFilters.entries()).every(([index, selectedValues]) => (
                        selectedValues.has(getCellValue(row, index))
                    ));
                    row.hidden = !isVisible;
                    if (isVisible) visibleCount += 1;
                });

                updateButtonStates();
                status.hidden = activeFilters.size === 0;
                statusText.textContent = `Showing ${visibleCount} of ${rows.length} sites · ${activeFilters.size} active ${activeFilters.size === 1 ? "filter" : "filters"}`;
                emptyRow.hidden = visibleCount !== 0;
            }

            function pageZoom() {
                const zoom = Number.parseFloat(getComputedStyle(document.body).zoom || "1");
                return Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
            }

            function positionMenu(button, menu) {
                const zoom = pageZoom();
                const buttonRect = button.getBoundingClientRect();
                const menuRect = menu.getBoundingClientRect();
                const viewportWidth = document.documentElement.clientWidth;
                const viewportHeight = document.documentElement.clientHeight;
                const margin = 8;
                const gap = 6;

                let left = buttonRect.right - menuRect.width;
                left = Math.max(margin, Math.min(left, viewportWidth - menuRect.width - margin));

                let top = buttonRect.bottom + gap;
                if (top + menuRect.height > viewportHeight - margin && buttonRect.top - menuRect.height - gap >= margin) {
                    top = buttonRect.top - menuRect.height - gap;
                }

                menu.style.left = `${left / zoom}px`;
                menu.style.top = `${top / zoom}px`;
            }

            function closeMenus(exceptMenu = null) {
                menus.forEach(({ button, menu }) => {
                    if (menu === exceptMenu) return;
                    menu.hidden = true;
                    button.setAttribute("aria-expanded", "false");
                    button.closest("th")?.classList.remove("is-filter-open");
                });
            }

            filterButtons.forEach((button) => {
                const index = Number(button.dataset.filterIndex || "-1");
                if (!Number.isInteger(index) || index < 0) return;

                const values = Array.from(new Set(rows.map((row) => getCellValue(row, index)))).sort(collator.compare);
                const th = button.closest("th");
                if (!th) return;

                menuId += 1;
                const menu = document.createElement("div");
                menu.id = `column-filter-menu-${menuId}`;
                menu.className = "column-filter-menu";
                menu.hidden = true;
                menu.setAttribute("role", "dialog");
                menu.setAttribute("aria-label", `Filter ${button.dataset.filterLabel || "column"}`);
                button.setAttribute("aria-controls", menu.id);

                const title = document.createElement("div");
                title.className = "column-filter-title";
                title.textContent = `Filter ${button.dataset.filterLabel || "column"}`;

                const search = document.createElement("input");
                search.type = "search";
                search.className = "column-filter-search";
                search.placeholder = "Search values";
                search.setAttribute("aria-label", `Search ${button.dataset.filterLabel || "column"} values`);

                const bulkActions = document.createElement("div");
                bulkActions.className = "column-filter-bulk-actions";
                const selectAllButton = document.createElement("button");
                selectAllButton.type = "button";
                selectAllButton.textContent = "Select all";
                const clearButton = document.createElement("button");
                clearButton.type = "button";
                clearButton.textContent = "Clear";
                bulkActions.append(selectAllButton, clearButton);

                const optionList = document.createElement("div");
                optionList.className = "column-filter-options";
                const optionEntries = values.map((value) => {
                    const label = document.createElement("label");
                    label.className = "column-filter-option";
                    const checkbox = document.createElement("input");
                    checkbox.type = "checkbox";
                    checkbox.value = value;
                    const text = document.createElement("span");
                    text.textContent = value || "(Blank)";
                    label.append(checkbox, text);
                    optionList.appendChild(label);
                    return { value, label, checkbox };
                });

                const footer = document.createElement("div");
                footer.className = "column-filter-footer";
                const cancelButton = document.createElement("button");
                cancelButton.type = "button";
                cancelButton.className = "column-filter-cancel";
                cancelButton.textContent = "Cancel";
                const applyButton = document.createElement("button");
                applyButton.type = "button";
                applyButton.className = "column-filter-apply";
                applyButton.textContent = "Apply";
                footer.append(cancelButton, applyButton);

                menu.append(title, search, bulkActions, optionList, footer);
                document.body.appendChild(menu);
                menus.push({ button, menu });

                function syncMenuSelection() {
                    const selectedValues = activeFilters.get(index);
                    optionEntries.forEach(({ value, label, checkbox }) => {
                        checkbox.checked = selectedValues ? selectedValues.has(value) : true;
                        label.hidden = false;
                    });
                    search.value = "";
                }

                function visibleEntries() {
                    return optionEntries.filter(({ label }) => !label.hidden);
                }

                button.addEventListener("click", (event) => {
                    event.stopPropagation();
                    const willOpen = menu.hidden;
                    closeMenus(willOpen ? menu : null);
                    if (willOpen) {
                        syncMenuSelection();
                        menu.hidden = false;
                        positionMenu(button, menu);
                        button.setAttribute("aria-expanded", "true");
                        th.classList.add("is-filter-open");
                        search.focus();
                    } else {
                        menu.hidden = true;
                        button.setAttribute("aria-expanded", "false");
                        th.classList.remove("is-filter-open");
                    }
                });

                menu.addEventListener("click", (event) => event.stopPropagation());

                search.addEventListener("input", () => {
                    const query = search.value.trim().toLocaleLowerCase();
                    optionEntries.forEach(({ value, label }) => {
                        label.hidden = Boolean(query) && !value.toLocaleLowerCase().includes(query);
                    });
                });

                selectAllButton.addEventListener("click", () => {
                    visibleEntries().forEach(({ checkbox }) => {
                        checkbox.checked = true;
                    });
                });

                clearButton.addEventListener("click", () => {
                    visibleEntries().forEach(({ checkbox }) => {
                        checkbox.checked = false;
                    });
                });

                cancelButton.addEventListener("click", () => closeMenus());

                applyButton.addEventListener("click", () => {
                    const selectedValues = new Set(
                        optionEntries.filter(({ checkbox }) => checkbox.checked).map(({ value }) => value),
                    );
                    if (selectedValues.size === values.length) activeFilters.delete(index);
                    else activeFilters.set(index, selectedValues);
                    applyFilters();
                    closeMenus();
                });
            });

            clearFiltersButton.addEventListener("click", () => {
                activeFilters.clear();
                applyFilters();
                closeMenus();
            });

            document.addEventListener("click", () => closeMenus());
            document.addEventListener("keydown", (event) => {
                if (event.key === "Escape") closeMenus();
            });
            window.addEventListener("resize", () => closeMenus());
            window.addEventListener("scroll", () => closeMenus(), { passive: true });
            table.closest(".site-table-wrap")?.addEventListener("scroll", () => closeMenus(), { passive: true });
        });
    }

    function bindIdentifierExamples() {
        const speciesField = document.getElementById("species_identifier");
        const input = document.getElementById("gene_name");
        const exampleText = document.querySelector("[data-identifier-example]");
        if (!input || !exampleText) return;

        const placeholders = {
            glycine_max: "Example: GLYMA_10G142500",
            bradyrhizobium_diazoefficiens: "Example: rpoC or Q89J75",
        };

        function syncExampleVisibility() {
            exampleText.hidden = input.value.trim().length > 0;
        }

        function updateExamples() {
            const species = speciesField ? speciesField.value : "glycine_max";
            if (placeholders[species]) {
                exampleText.textContent = placeholders[species];
            }
            syncExampleVisibility();
        }

        input.addEventListener("input", syncExampleVisibility);

        if (speciesField) {
            speciesField.addEventListener("change", updateExamples);
        }
        updateExamples();
    }

    function bindProteinMapZoom() {
        const zoomLevels = [1, 1.5, 2, 2.5, 3, 4];

        document.querySelectorAll("[data-protein-map]").forEach((panel) => {
            const scroll = panel.querySelector("[data-map-scroll]");
            const svg = panel.querySelector("[data-map-svg]");
            const zoomOutButton = panel.querySelector("[data-map-zoom-out]");
            const zoomInButton = panel.querySelector("[data-map-zoom-in]");
            const fitButton = panel.querySelector("[data-map-zoom-fit]");
            const zoomValue = panel.querySelector("[data-map-zoom-value]");
            const background = svg?.querySelector("[data-map-background]");
            if (!(scroll instanceof HTMLElement) || !(svg instanceof SVGElement)) return;

            const originalViewWidth = Number(svg.dataset.mapViewWidth || "1000");
            const viewHeight = Number(svg.dataset.mapViewHeight || "0");
            const axisLeft = Number(svg.dataset.mapAxisLeft || "0");
            const axisRight = Number(svg.dataset.mapAxisRight || String(originalViewWidth));
            if (!Number.isFinite(originalViewWidth) || originalViewWidth <= 0 || !Number.isFinite(viewHeight) || viewHeight <= 0) return;

            const axisWidth = Math.max(axisRight - axisLeft, 0);
            const rightMargin = Math.max(originalViewWidth - axisRight, 0);
            const scalableElements = Array.from(svg.querySelectorAll("[data-map-scale-x]")).map((element) => {
                const attributes = ["x", "x1", "x2", "cx"]
                    .filter((name) => element.hasAttribute(name))
                    .map((name) => ({ name, value: Number(element.getAttribute(name)) }));
                return { element, attributes };
            });
            const scalableWidths = Array.from(svg.querySelectorAll("[data-map-scale-width]")).map((element) => ({
                element,
                width: Number(element.getAttribute("width")),
            }));
            let zoomIndex = 0;
            let resizeFrame = 0;

            function scaledX(value, zoom) {
                return axisLeft + ((value - axisLeft) * zoom);
            }

            function applyZoom(nextIndex, preserveCenter = true) {
                const oldSvgWidth = Math.max(svg.clientWidth, 1);
                const viewportCenterRatio = (scroll.scrollLeft + (scroll.clientWidth / 2)) / oldSvgWidth;
                zoomIndex = Math.max(0, Math.min(nextIndex, zoomLevels.length - 1));
                const zoom = zoomLevels[zoomIndex];
                const expandedViewWidth = axisLeft + (axisWidth * zoom) + rightMargin;

                scalableElements.forEach(({ element, attributes }) => {
                    attributes.forEach(({ name, value }) => {
                        if (Number.isFinite(value)) element.setAttribute(name, scaledX(value, zoom).toFixed(2));
                    });
                });
                scalableWidths.forEach(({ element, width }) => {
                    if (Number.isFinite(width)) element.setAttribute("width", (width * zoom).toFixed(2));
                });

                if (background instanceof SVGElement) {
                    background.setAttribute("width", expandedViewWidth.toFixed(2));
                }
                svg.setAttribute("viewBox", `0 0 ${expandedViewWidth.toFixed(2)} ${viewHeight}`);

                const fitWidth = Math.max(scroll.clientWidth, 1);
                svg.style.width = `${fitWidth * (expandedViewWidth / originalViewWidth)}px`;
                svg.style.height = `${fitWidth * (viewHeight / originalViewWidth)}px`;
                panel.classList.toggle("is-map-zoomed", zoomIndex > 0);

                if (zoomValue instanceof HTMLOutputElement) zoomValue.value = `${Math.round(zoom * 100)}%`;
                if (zoomOutButton instanceof HTMLButtonElement) zoomOutButton.disabled = zoomIndex === 0;
                if (zoomInButton instanceof HTMLButtonElement) zoomInButton.disabled = zoomIndex === zoomLevels.length - 1;

                window.requestAnimationFrame(() => {
                    if (zoomIndex === 0) {
                        scroll.scrollLeft = 0;
                    } else if (preserveCenter) {
                        const newSvgWidth = Math.max(svg.clientWidth, 1);
                        scroll.scrollLeft = Math.max(0, (viewportCenterRatio * newSvgWidth) - (scroll.clientWidth / 2));
                    }
                });
            }

            if (zoomOutButton instanceof HTMLButtonElement) {
                zoomOutButton.addEventListener("click", () => applyZoom(zoomIndex - 1));
            }
            if (zoomInButton instanceof HTMLButtonElement) {
                zoomInButton.addEventListener("click", () => applyZoom(zoomIndex + 1));
            }
            if (fitButton instanceof HTMLButtonElement) {
                fitButton.addEventListener("click", () => applyZoom(0, false));
            }

            applyZoom(0, false);
            window.addEventListener("resize", () => {
                window.cancelAnimationFrame(resizeFrame);
                resizeFrame = window.requestAnimationFrame(() => applyZoom(zoomIndex));
            });
        });
    }

    bindSegmentedControls();
    bindCollapsibleSearch();
    bindIdentifierExamples();
    bindTableDownloads();
    bindSortableTables();
    bindTableFilters();
    bindProteinMapZoom();

    function syncSiteTableHeight() {
        const side = document.querySelector(".result-side");
        const tableWrap = document.querySelector(".site-table-wrap");
        const sequenceFigure = document.querySelector(".sequence-figure");
        if (!(side instanceof HTMLElement) || !(tableWrap instanceof HTMLElement) || !(sequenceFigure instanceof HTMLElement)) return;

        if (window.matchMedia("(max-width: 1000px)").matches) {
            tableWrap.style.maxHeight = "";
            return;
        }

        tableWrap.style.maxHeight = "";
        const sideRect = side.getBoundingClientRect();
        const tableRect = tableWrap.getBoundingClientRect();
        const figureRect = sequenceFigure.getBoundingClientRect();
        const sideStyle = window.getComputedStyle(side);
        const sideBottomPadding = Number.parseFloat(sideStyle.paddingBottom || "0") || 0;
        const topOffset = tableRect.top - sideRect.top;
        const availableHeight = Math.floor(figureRect.height - topOffset - sideBottomPadding);
        if (availableHeight > 260) {
            tableWrap.style.maxHeight = `${availableHeight}px`;
        }
    }

    syncSiteTableHeight();
    window.addEventListener("resize", () => {
        window.requestAnimationFrame(syncSiteTableHeight);
    });

    const figure = document.querySelector(".sequence-figure");
    if (!figure) return;

    const legend = figure.querySelector(".ptm-legend");
    const chips = legend ? Array.from(legend.querySelectorAll(".legend-chip[data-ptm-code]")) : [];

    const chartPanel = document.getElementById("site-chart-panel");
    const chartDataScript = document.getElementById("site-chart-data");
    const siteRows = Array.from(document.querySelectorAll(".site-table tbody tr.site-row[data-site-id]"));
    const mapSites = Array.from(document.querySelectorAll(".protein-map-site[data-site-id]"));

    let selectedNode = null;
    let selectedKey = "";

    function clearSelection() {
        selectedKey = "";
        if (selectedNode) {
            selectedNode.classList.remove("is-selected");
            selectedNode = null;
        }
        mapSites.forEach((site) => site.classList.remove("is-selected"));
        if (legend) {
            legend.classList.remove("has-selection");
            chips.forEach((chip) => chip.classList.remove("is-active"));
        }
    }

    function normalizeCodes(rawCodes) {
        return Array.from(
            new Set(
                rawCodes
                    .split(",")
                    .map((code) => code.trim())
                    .filter((code) => code.length > 0)
            )
        );
    }

    function applySelection(node, force = false) {
        if (!legend) return;
        const codes = normalizeCodes(node.dataset.ptmCodes || "");
        if (!codes.length) {
            clearSelection();
            return;
        }

        const key = codes.slice().sort().join("|");
        if (!force && selectedNode === node && selectedKey === key) {
            clearSelection();
            return;
        }

        if (selectedNode) {
            selectedNode.classList.remove("is-selected");
        }

        selectedNode = node;
        selectedKey = key;
        selectedNode.classList.add("is-selected");
        legend.classList.add("has-selection");

        const selectedSet = new Set(codes);
        if (codes.length > 1) {
            selectedSet.add("__multiple__");
        }
        chips.forEach((chip) => {
            const code = (chip.dataset.ptmCode || "").trim();
            chip.classList.toggle("is-active", selectedSet.has(code));
        });
    }

    function formatValue(value) {
        if (typeof value !== "number" || !Number.isFinite(value)) return "-";
        if (Math.abs(value) >= 1000 || Math.abs(value) < 0.001) return value.toExponential(2);
        return value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
    }

    function formatAxisValue(value) {
        if (!Number.isFinite(value)) return "-";
        if (Math.abs(value) >= 1000 || (Math.abs(value) > 0 && Math.abs(value) < 0.001)) {
            return value.toExponential(1);
        }
        if (value >= 10) return value.toFixed(1).replace(/\.0$/, "");
        if (value >= 1) return value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
        return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
    }

    function niceStep(rawStep) {
        if (!Number.isFinite(rawStep) || rawStep <= 0) return 1;
        const exponent = Math.floor(Math.log10(rawStep));
        const fraction = rawStep / (10 ** exponent);
        let niceFraction = 1;
        if (fraction <= 1) niceFraction = 1;
        else if (fraction <= 2) niceFraction = 2;
        else if (fraction <= 5) niceFraction = 5;
        else niceFraction = 10;
        return niceFraction * (10 ** exponent);
    }

    function buildAxis(maxValue) {
        if (!Number.isFinite(maxValue) || maxValue <= 0) {
            return { axisMax: 0.1, step: 0.025 };
        }
        const padded = maxValue * 1.1;
        const step = niceStep(padded / 4);
        let axisMax = step * 4;
        if (axisMax <= maxValue) {
            axisMax += step;
        }
        return { axisMax, step: axisMax / 4 };
    }

    function parseChartData() {
        if (!chartDataScript) return [];
        try {
            const parsed = JSON.parse(chartDataScript.textContent || "[]");
            return Array.isArray(parsed) ? parsed : [];
        } catch (_) {
            return [];
        }
    }

    const chartData = parseChartData();
    const chartById = new Map(chartData.map((item) => [String(item.site_id || ""), item]));
    let activeChartPayload = null;

    function buildSiteChartSvg(payload) {
        const width = 760;
        const height = 470;
        const plotTop = 104;
        const plotBottom = 282;
        const axisLeft = 118;
        const axisRight = 690;
        const w4 = typeof payload.w4_mean_linear === "number" ? payload.w4_mean_linear : null;
        const w12 = typeof payload.w12_mean_linear === "number" ? payload.w12_mean_linear : null;
        const maxValue = Math.max(w4 || 0, w12 || 0, 0);
        const { axisMax, step } = buildAxis(maxValue);
        const barWidth = 72;
        const barBase = plotBottom;
        const w4Height = axisMax > 0 && w4 !== null ? Math.max((w4 / axisMax) * (plotBottom - plotTop), 3) : 3;
        const w12Height = axisMax > 0 && w12 !== null ? Math.max((w12 / axisMax) * (plotBottom - plotTop), 3) : 3;
        const pos = payload.position ?? "-";
        const aa = payload.amino_acid || "-";
        const ptm = payload.ptm_type || "-";
        const target = typeof pos === "number" && pos <= 0 ? `Protein-level | ${ptm}` : `Position ${pos} | ${aa} | ${ptm}`;
        const ratioText = formatValue(payload.ratio);
        const pText = formatValue(payload.p_value);
        const typeText = payload.ratio_type || "-";
        const locationText = payload.subcellular_localization || "-";
        const meta = `Ratio: ${ratioText} | Subcellular localization: ${locationText} | P-value: ${pText} | Type: ${typeText}`;
        const ticks = [0, 1, 2, 3, 4].map((idx) => {
            const value = step * idx;
            const y = plotBottom - ((plotBottom - plotTop) * idx / 4);
            return { value, y };
        });

        function esc(value) {
            return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                "\"": "&quot;",
                "'": "&#39;",
            }[ch]));
        }

        return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <rect width="${width}" height="${height}" fill="#ffffff"/>
  <text x="34" y="42" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="#2d4b1b">Site Quantification</text>
  <text x="34" y="70" font-family="Arial, sans-serif" font-size="15" fill="#4b5e38">${esc(target)}</text>
  <line x1="${axisLeft}" y1="${plotBottom}" x2="${axisRight}" y2="${plotBottom}" stroke="#b7c99a" stroke-width="2"/>
  ${ticks.map((tick) => `<line x1="${axisLeft}" y1="${tick.y.toFixed(2)}" x2="${axisRight}" y2="${tick.y.toFixed(2)}" stroke="#e2ecd4" stroke-width="1"/><text x="${axisLeft - 12}" y="${(tick.y + 4).toFixed(2)}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#5a6e45">${esc(formatAxisValue(tick.value))}</text>`).join("")}
  <rect x="298" y="${(barBase - w4Height).toFixed(2)}" width="${barWidth}" height="${w4Height.toFixed(2)}" fill="#4f772d" rx="3"/>
  <rect x="490" y="${(barBase - w12Height).toFixed(2)}" width="${barWidth}" height="${w12Height.toFixed(2)}" fill="#dda15e" rx="3"/>
  <text x="334" y="${(barBase - w4Height - 8).toFixed(2)}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#25371a">${esc(formatValue(w4))}</text>
  <text x="526" y="${(barBase - w12Height - 8).toFixed(2)}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#25371a">${esc(formatValue(w12))}</text>
  <text x="334" y="316" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" fill="#5a6e45">W4 Mean</text>
  <text x="526" y="316" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" fill="#5a6e45">W12 Mean</text>
  <text x="34" y="378" font-family="Arial, sans-serif" font-size="14" fill="#405233">${esc(meta)}</text>
  <text x="34" y="406" font-family="Arial, sans-serif" font-size="12" fill="#6a7b57">Bar values use anti-log2 means from the three replicates in each group.</text>
</svg>`;
    }

    function bindChartDownload() {
        const button = document.getElementById("download-site-chart");
        if (!button) return;
        button.addEventListener("click", async () => {
            if (!activeChartPayload) return;
            const filename = safeFilename(`site-quantification-${activeChartPayload.site_id || "chart"}.png`, "site-quantification.png");
            const svgText = buildSiteChartSvg(activeChartPayload);
            try {
                const pngBlob = await svgToPngBlob(svgText, 760, 470);
                const pngWithDpi = await addPngDpiMetadata(pngBlob, 1200);
                downloadBlob(pngWithDpi, filename, "image/png");
            } catch (error) {
                console.error(error);
            }
        });
    }

    function markSelectedSiteRow(siteId) {
        siteRows.forEach((row) => row.classList.toggle("is-selected", row.dataset.siteId === siteId));
        mapSites.forEach((site) => {
            const siteIds = normalizeCodes(site.dataset.siteIds || site.dataset.siteId || "");
            site.classList.toggle("is-selected", siteIds.includes(siteId));
        });
    }

    function updateSiteChart(siteId) {
        if (!chartPanel) return;

        const targetNode = document.getElementById("site-chart-target");
        const barW4 = document.getElementById("chart-bar-w4");
        const barW12 = document.getElementById("chart-bar-w12");
        const valueW4 = document.getElementById("chart-value-w4");
        const valueW12 = document.getElementById("chart-value-w12");
        const metaNode = document.getElementById("site-chart-meta");
        const tickMax = document.getElementById("chart-y-tick-max");
        const tick75 = document.getElementById("chart-y-tick-75");
        const tick50 = document.getElementById("chart-y-tick-50");
        const tick25 = document.getElementById("chart-y-tick-25");
        const tick0 = document.getElementById("chart-y-tick-0");

        if (!targetNode || !barW4 || !barW12 || !valueW4 || !valueW12 || !metaNode || !tickMax || !tick75 || !tick50 || !tick25 || !tick0) return;

        const payload = chartById.get(siteId);
        if (!payload) return;
        activeChartPayload = payload;

        markSelectedSiteRow(siteId);

        const w4 = typeof payload.w4_mean_linear === "number" ? payload.w4_mean_linear : null;
        const w12 = typeof payload.w12_mean_linear === "number" ? payload.w12_mean_linear : null;
        const hasQuantData = w4 !== null || w12 !== null;
        const maxValue = Math.max(w4 || 0, w12 || 0, 0);
        const { axisMax, step } = buildAxis(maxValue);

        const h4 = axisMax > 0 && w4 !== null ? Math.max((w4 / axisMax) * 100, 2) : 2;
        const h12 = axisMax > 0 && w12 !== null ? Math.max((w12 / axisMax) * 100, 2) : 2;

        barW4.style.height = `${h4}%`;
        barW12.style.height = `${h12}%`;
        valueW4.textContent = formatValue(w4);
        valueW12.textContent = formatValue(w12);

        tickMax.textContent = hasQuantData ? formatAxisValue(axisMax) : "-";
        tick75.textContent = hasQuantData ? formatAxisValue(step * 3) : "-";
        tick50.textContent = hasQuantData ? formatAxisValue(step * 2) : "-";
        tick25.textContent = hasQuantData ? formatAxisValue(step) : "-";
        tick0.textContent = "0";

        const pos = payload.position ?? "-";
        const aa = payload.amino_acid || "-";
        const ptm = payload.ptm_type || "-";
        if (typeof pos === "number" && pos <= 0) {
            targetNode.textContent = `Protein-level | ${ptm}`;
        } else {
            targetNode.textContent = `Position ${pos} | ${aa} | ${ptm}`;
        }

        const ratioText = formatValue(payload.ratio);
        const pText = formatValue(payload.p_value);
        const typeText = payload.ratio_type || "-";
        const locationText = payload.subcellular_localization || "-";
        const quantHint = hasQuantData ? "" : " | Quant: no data";
        metaNode.textContent = `Ratio: ${ratioText} | Subcellular localization: ${locationText} | P-value: ${pText} | Type: ${typeText}${quantHint}`;
    }

    function bindSiteRowInteraction() {
        if (!siteRows.length || !chartPanel) return;
        siteRows.forEach((row) => {
            row.addEventListener("click", () => {
                const siteId = row.dataset.siteId || "";
                if (siteId) updateSiteChart(siteId);
            });
            row.addEventListener("keydown", (event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                const siteId = row.dataset.siteId || "";
                if (siteId) updateSiteChart(siteId);
            });
        });
    }

    function bindProteinMapInteraction() {
        if (!mapSites.length) return;
        mapSites.forEach((site) => {
            function activateSite() {
                const siteId = site.dataset.siteId || "";
                applySelection(site, true);
                if (siteId && chartPanel) {
                    updateSiteChart(siteId);
                }
            }
            site.addEventListener("click", activateSite);
            site.addEventListener("keydown", (event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                activateSite();
            });
        });
    }

    figure.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;

        const mapSite = target.closest(".protein-map-site[data-site-id]");
        if (mapSite) return;

        const aa = target.closest(".aa.marked[data-ptm-codes]");
        if (!aa) return;
        applySelection(aa);

        const aaPosition = Number(aa.dataset.position || "");
        if (!Number.isFinite(aaPosition) || !siteRows.length || !chartPanel) return;
        const linkedRow = siteRows.find((row) => {
            return Number(row.dataset.position || "") === aaPosition;
        });
        if (linkedRow && linkedRow.dataset.siteId) {
            updateSiteChart(linkedRow.dataset.siteId);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            clearSelection();
        }
    });

    bindSiteRowInteraction();
    bindProteinMapInteraction();
    bindChartDownload();
    if (chartPanel && chartData.length > 0) {
        const preferred = chartPanel.dataset.defaultSiteId || (chartData[0].site_id || "");
        const fallback = preferred && chartById.has(preferred) ? preferred : (chartData[0].site_id || "");
        if (fallback) {
            updateSiteChart(fallback);
        }
    }
})();
