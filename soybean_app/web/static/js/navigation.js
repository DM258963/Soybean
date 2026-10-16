const menuToggle = document.getElementById("menuToggle");
const topNav = document.getElementById("topNav");
const dropdownParents = document.querySelectorAll(".has-dropdown");

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

document.querySelectorAll("[data-auto-submit]").forEach((field) => {
    field.addEventListener("change", () => {
        if (field.form) {
            field.form.submit();
        }
    });
});
