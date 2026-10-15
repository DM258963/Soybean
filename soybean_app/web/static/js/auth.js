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
        field.type = toggle.checked ? "text" : "password";
    }

    document.querySelectorAll("[data-password-toggle]").forEach((toggle) => {
        setPasswordVisibility(toggle);
        toggle.addEventListener("change", () => setPasswordVisibility(toggle));
    });
})();
