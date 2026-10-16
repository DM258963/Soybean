(function () {
    function setPasswordVisibility(toggle) {
        const target = toggle.getAttribute("data-password-target");
        if (!target) {
            return;
        }
        const field = Array.from(document.querySelectorAll("[data-password-field]")).find(
            (item) => item.getAttribute("data-password-field") === target
        );
        if (!field) {
            return;
        }
        const isVisible = toggle.getAttribute("aria-pressed") === "true";
        field.type = isVisible ? "text" : "password";
        toggle.setAttribute("aria-label", isVisible ? "Hide password" : "Show password");
        toggle.setAttribute("title", isVisible ? "Hide password" : "Show password");
    }

    document.querySelectorAll("[data-password-toggle]").forEach((toggle) => {
        setPasswordVisibility(toggle);
        toggle.addEventListener("click", () => {
            const isVisible = toggle.getAttribute("aria-pressed") === "true";
            toggle.setAttribute("aria-pressed", isVisible ? "false" : "true");
            setPasswordVisibility(toggle);
        });
    });

    const userSearch = document.querySelector("[data-user-search]");
    const userRows = Array.from(document.querySelectorAll("[data-user-row]"));
    const userCount = document.querySelector("[data-user-count]");
    const searchStatus = document.querySelector("[data-user-search-status]");
    const searchEmpty = document.querySelector("[data-user-search-empty]");
    const searchClear = document.querySelector("[data-user-search-clear]");
    const userTable = document.querySelector("[data-user-table]");

    function userCountLabel(count) {
        return `${count} ${count === 1 ? "user" : "users"}`;
    }

    function filterUsers() {
        if (!userSearch) {
            return;
        }

        const query = userSearch.value.trim().toLocaleLowerCase();
        let visibleCount = 0;

        userRows.forEach((row) => {
            const username = (row.getAttribute("data-username") || "").toLocaleLowerCase();
            const matches = !query || username.includes(query);
            row.hidden = !matches;
            if (matches) {
                visibleCount += 1;
            }
        });

        if (userCount) {
            userCount.textContent = query
                ? `${visibleCount} of ${userRows.length} users`
                : userCountLabel(userRows.length);
        }
        if (searchStatus) {
            searchStatus.textContent = query
                ? `${visibleCount} matching ${visibleCount === 1 ? "account" : "accounts"}`
                : "";
        }
        if (searchEmpty) {
            searchEmpty.hidden = visibleCount !== 0;
        }
        if (userTable) {
            userTable.hidden = visibleCount === 0;
        }
        if (searchClear) {
            searchClear.hidden = !query;
        }
    }

    if (userSearch) {
        userSearch.addEventListener("input", filterUsers);
        userSearch.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && userSearch.value) {
                userSearch.value = "";
                filterUsers();
            }
        });
    }

    if (searchClear && userSearch) {
        searchClear.addEventListener("click", () => {
            userSearch.value = "";
            filterUsers();
            userSearch.focus();
        });
    }

    document.querySelectorAll("[data-confirm-delete]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            const username = form.getAttribute("data-confirm-delete") || "this user";
            if (!window.confirm(`Delete user ${username}? This cannot be undone.`)) {
                event.preventDefault();
            }
        });
    });
})();
