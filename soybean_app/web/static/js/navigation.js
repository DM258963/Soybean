const menuToggle = document.getElementById("menuToggle");
const topNav = document.getElementById("topNav");
const dropdownParents = document.querySelectorAll(".has-dropdown");
const accountMenus = document.querySelectorAll("[data-account-menu]");

if (menuToggle && topNav) {
    menuToggle.addEventListener("click", () => {
        topNav.classList.toggle("open");
    });
}

dropdownParents.forEach((item) => {
    item.addEventListener("click", (event) => {
        if (window.innerWidth > 980) {
            return;
        }

        const trigger = event.target.closest(".nav-parent-btn");
        if (!trigger) {
            return;
        }

        const hasSubmenu = item.querySelector(".dropdown-menu");
        if (!hasSubmenu) {
            return;
        }

        event.preventDefault();
        item.classList.toggle("open");
        trigger.setAttribute("aria-expanded", item.classList.contains("open") ? "true" : "false");
    });
});

accountMenus.forEach((menu) => {
    const toggle = menu.querySelector("[data-account-menu-toggle]");
    const panel = menu.querySelector("[data-account-menu-panel]");
    if (!(toggle instanceof HTMLButtonElement) || !(panel instanceof HTMLElement)) return;

    function setOpen(isOpen, restoreFocus = false) {
        panel.hidden = !isOpen;
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        menu.classList.toggle("is-open", isOpen);
        if (!isOpen && restoreFocus) toggle.focus();
    }

    toggle.addEventListener("click", (event) => {
        event.stopPropagation();
        const willOpen = panel.hidden;
        accountMenus.forEach((otherMenu) => {
            if (otherMenu === menu) return;
            const otherToggle = otherMenu.querySelector("[data-account-menu-toggle]");
            const otherPanel = otherMenu.querySelector("[data-account-menu-panel]");
            if (otherToggle instanceof HTMLElement) otherToggle.setAttribute("aria-expanded", "false");
            if (otherPanel instanceof HTMLElement) otherPanel.hidden = true;
            otherMenu.classList.remove("is-open");
        });
        setOpen(willOpen);
    });

    panel.addEventListener("click", (event) => event.stopPropagation());

    toggle.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowDown") return;
        event.preventDefault();
        setOpen(true);
        const firstAction = panel.querySelector("[role='menuitem']");
        if (firstAction instanceof HTMLElement) firstAction.focus();
    });

    menu.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !panel.hidden) {
            event.preventDefault();
            setOpen(false, true);
        }
    });

    document.addEventListener("click", () => setOpen(false));
});

document.querySelectorAll("[data-auto-submit]").forEach((field) => {
    field.addEventListener("change", () => {
        if (field.form) {
            field.form.submit();
        }
    });
});
