(function () {
    const form = document.querySelector("[data-agent-settings-form]");
    if (!form) return;

    const modeInputs = Array.from(form.querySelectorAll("[data-agent-mode]"));
    const providerField = form.querySelector("[data-api-provider-field]");
    const provider = form.querySelector("[data-agent-provider]");
    const baseUrl = form.querySelector("[data-agent-base-url]");
    const apiKeyField = form.querySelector("[data-api-key-field]");
    const apiKeyControls = apiKeyField
        ? Array.from(apiKeyField.querySelectorAll("input, button"))
        : [];
    const apiKey = form.querySelector("#agent_api_key");
    const apiKeyStatus = form.querySelector("[data-api-key-status]");
    const timeout = form.querySelector("#agent_timeout");
    const modelValue = form.querySelector("[data-agent-model-value]");
    const modelSelect = form.querySelector("[data-agent-model-select]");
    const manualModel = form.querySelector("[data-agent-model-manual]");
    const fetchModelsButton = form.querySelector("[data-fetch-models]");
    const discoveryStatus = form.querySelector("[data-model-discovery-status]");

    const providerUrls = {
        groq: "https://api.groq.com/openai/v1",
        openai: "https://api.openai.com/v1",
        openai_compatible: "",
    };

    function readProfile(rawValue, fallback) {
        try {
            const parsed = JSON.parse(rawValue || "{}");
            return { ...fallback, ...parsed };
        } catch (_) {
            return { ...fallback };
        }
    }

    const activeModeInput = modeInputs.find((input) => input.checked);
    let currentMode = activeModeInput ? activeModeInput.value : "api";
    const currentModel = modelValue ? modelValue.value : "";
    const profiles = {
        local: readProfile(form.dataset.localProfile, {
            provider: "openai_compatible",
            base_url: "http://127.0.0.1:11434/v1",
            model_name: currentMode === "local" ? currentModel : "",
            llm_timeout: timeout ? timeout.value : "30",
            api_key_configured: false,
        }),
        api: readProfile(form.dataset.apiProfile, {
            provider: provider ? provider.value : "groq",
            base_url: providerUrls[provider ? provider.value : "groq"] || "",
            model_name: currentMode === "api" ? currentModel : "",
            llm_timeout: timeout ? timeout.value : "30",
            api_key_configured: false,
        }),
    };
    profiles.local.model_options = profiles.local.model_name ? [profiles.local.model_name] : [];
    profiles.api.model_options = profiles.api.model_name ? [profiles.api.model_name] : [];

    function selectedMode() {
        const selected = modeInputs.find((input) => input.checked);
        return selected ? selected.value : currentMode;
    }

    function applyModelSelection(options = {}) {
        if (!modelSelect || !modelValue || !manualModel) return;
        const isManual = modelSelect.value === "__manual__";
        manualModel.hidden = !isManual;
        manualModel.required = isManual;
        modelValue.value = isManual ? manualModel.value.trim() : modelSelect.value;
        if (isManual && options.focus) manualModel.focus();
    }

    function renderModelOptions(profile) {
        if (!modelSelect || !modelValue || !manualModel) return;
        const models = Array.from(new Set([
            ...(profile.model_options || []),
            profile.model_name || "",
        ].filter(Boolean)));
        modelSelect.replaceChildren();
        if (!models.length) {
            const placeholder = document.createElement("option");
            placeholder.value = "";
            placeholder.textContent = "Get models or choose manual entry";
            placeholder.disabled = true;
            placeholder.selected = true;
            modelSelect.appendChild(placeholder);
        }
        models.forEach((modelId) => {
            const option = document.createElement("option");
            option.value = modelId;
            option.textContent = modelId;
            modelSelect.appendChild(option);
        });
        const manualOption = document.createElement("option");
        manualOption.value = "__manual__";
        manualOption.textContent = "Enter a model ID manually…";
        modelSelect.appendChild(manualOption);
        modelSelect.value = profile.model_name || "";
        manualModel.value = "";
        applyModelSelection();
    }

    function captureProfile(mode) {
        if (!profiles[mode]) return;
        applyModelSelection();
        profiles[mode] = {
            ...profiles[mode],
            provider: mode === "local" ? "openai_compatible" : (provider ? provider.value : "groq"),
            base_url: baseUrl ? baseUrl.value : "",
            model_name: modelValue ? modelValue.value : "",
            llm_timeout: timeout ? timeout.value : "30",
            model_options: modelSelect
                ? Array.from(modelSelect.options)
                    .map((option) => option.value)
                    .filter((value) => value && value !== "__manual__")
                : [],
        };
    }

    function updateApiKeyCopy() {
        const configured = Boolean(profiles.api.api_key_configured);
        if (apiKey) {
            apiKey.placeholder = configured
                ? "Leave blank to keep the current key"
                : "Enter API key";
        }
        if (apiKeyStatus) {
            apiKeyStatus.textContent = configured
                ? "A key is currently available. Leave this field blank to keep it, or enter a new key to replace it. Its value is never displayed."
                : "No API key is currently available for your API profile.";
        }
    }

    function setDiscoveryState(message, state) {
        if (discoveryStatus) {
            discoveryStatus.textContent = message;
            discoveryStatus.dataset.state = state || "";
        }
        if (fetchModelsButton) {
            fetchModelsButton.disabled = state === "loading";
            fetchModelsButton.classList.toggle("is-loading", state === "loading");
            const label = fetchModelsButton.querySelector("span");
            if (label) label.textContent = state === "loading" ? "Loading..." : "Get models";
        }
    }

    function restoreProfile(mode) {
        const profile = profiles[mode];
        if (!profile) return;
        if (provider) provider.value = mode === "local" ? "openai_compatible" : profile.provider;
        if (baseUrl) baseUrl.value = profile.base_url || "";
        if (timeout) timeout.value = profile.llm_timeout || "30";
        renderModelOptions(profile);
        updateApiKeyCopy();
        setDiscoveryState(
            mode === "local"
                ? "Get the models installed on your local model service."
                : "Get the models available to your API account.",
            "",
        );
    }

    function applyModeVisibility() {
        const isLocal = currentMode === "local";
        if (providerField) providerField.hidden = isLocal;
        if (provider) provider.disabled = isLocal;
        if (apiKeyField) apiKeyField.hidden = isLocal;
        apiKeyControls.forEach((control) => {
            control.disabled = isLocal;
        });
        form.classList.toggle("is-local-mode", isLocal);
    }

    modeInputs.forEach((input) => {
        input.addEventListener("change", () => {
            const nextMode = selectedMode();
            if (nextMode === currentMode) return;
            captureProfile(currentMode);
            currentMode = nextMode;
            restoreProfile(currentMode);
            applyModeVisibility();
        });
    });

    if (provider) {
        provider.addEventListener("change", () => {
            if (!baseUrl || currentMode !== "api") return;
            const suggested = providerUrls[provider.value] || "";
            if (suggested) baseUrl.value = suggested;
        });
    }

    async function fetchAvailableModels() {
        const endpoint = form.dataset.modelDiscoveryUrl;
        if (!endpoint || !baseUrl || !modelSelect) return;
        if (!baseUrl.reportValidity()) return;

        setDiscoveryState("Contacting the configured model service...", "loading");
        try {
            const response = await fetch(endpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json", "Accept": "application/json" },
                body: JSON.stringify({
                    csrf_token: (form.querySelector('[name="csrf_token"]') || {}).value || "",
                    mode: currentMode,
                    provider: provider ? provider.value : "openai_compatible",
                    base_url: baseUrl.value,
                    api_key: apiKey ? apiKey.value : "",
                    llm_timeout: timeout ? timeout.value : "30",
                }),
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(result.detail || "Unable to retrieve the model list.");
            }

            const previousModel = modelValue ? modelValue.value : "";
            profiles[currentMode].model_options = result.models;
            profiles[currentMode].model_name = result.models.includes(previousModel)
                ? previousModel
                : result.models[0];
            renderModelOptions(profiles[currentMode]);
            captureProfile(currentMode);
            setDiscoveryState(`${result.count} available model${result.count === 1 ? "" : "s"} retrieved. Open the dropdown to choose one.`, "success");
            modelSelect.focus();
        } catch (error) {
            setDiscoveryState(error.message || "Unable to retrieve the model list.", "error");
        }
    }

    if (fetchModelsButton) {
        fetchModelsButton.addEventListener("click", fetchAvailableModels);
    }
    if (modelSelect) {
        modelSelect.addEventListener("change", () => applyModelSelection({ focus: true }));
    }
    if (manualModel) {
        manualModel.addEventListener("input", applyModelSelection);
    }
    form.addEventListener("submit", (event) => {
        captureProfile(currentMode);
        if (modelSelect && modelSelect.value === "__manual__" && manualModel && !manualModel.reportValidity()) {
            event.preventDefault();
        }
    });

    restoreProfile(currentMode);
    applyModeVisibility();
})();
