(() => {
    const numberFormatter = new Intl.NumberFormat();
    const elements = {
        resources: document.getElementById("landing-resource-count"),
        courses: document.getElementById("landing-course-count"),
        notes: document.getElementById("landing-notes-count"),
        pastPapers: document.getElementById("landing-past-paper-count"),
        itMaterials: document.getElementById("landing-it-material-count"),
        baMaterials: document.getElementById("landing-ba-material-count"),
        loginNotes: document.getElementById("login-notes-count"),
        loginResources: document.getElementById("login-resource-count"),
    };

    if (!Object.values(elements).some(Boolean)) {
        return;
    }

    let refreshPending = false;

    function renderUnavailable() {
        Object.entries(elements).forEach(([key, element]) => {
            if (element) {
                element.textContent = key === "notes" || key === "pastPapers"
                    ? "Unavailable resources"
                    : "Unavailable";
            }
        });
    }

    async function refreshStats() {
        if (refreshPending) {
            return;
        }
        refreshPending = true;

        try {
            const response = await fetch("/api/resource-stats", {
                headers: { Accept: "application/json" },
                cache: "no-store",
                credentials: "same-origin",
            });
            const stats = await response.json();
            if (!response.ok) {
                throw new Error(stats.message || "Could not load resource statistics.");
            }

            if (elements.resources) {
                elements.resources.textContent = numberFormatter.format(stats.resource_count);
            }
            if (elements.courses) {
                elements.courses.textContent = numberFormatter.format(stats.course_count);
            }
            if (elements.notes) {
                elements.notes.textContent = `${numberFormatter.format(stats.notes_count)} resources`;
            }
            if (elements.pastPapers) {
                elements.pastPapers.textContent = `${numberFormatter.format(stats.past_paper_count)} resources`;
            }
            if (elements.itMaterials) {
                elements.itMaterials.textContent =
                    `${numberFormatter.format(stats.it_material_count)} approved materials available`;
            }
            if (elements.baMaterials) {
                elements.baMaterials.textContent =
                    `${numberFormatter.format(stats.ba_material_count)} approved materials available`;
            }
            if (elements.loginNotes) {
                elements.loginNotes.textContent = numberFormatter.format(stats.notes_count);
            }
            if (elements.loginResources) {
                elements.loginResources.textContent = numberFormatter.format(stats.resource_count);
            }
        } catch (error) {
            console.error("Could not load resource statistics.", error);
            renderUnavailable();
        } finally {
            refreshPending = false;
        }
    }

    if ("BroadcastChannel" in window) {
        const statsChannel = new BroadcastChannel("acadex-resource-stats");
        statsChannel.addEventListener("message", (event) => {
            if (
                event.data
                && ["resource-approved", "resource-library-changed"].includes(event.data.type)
            ) {
                refreshStats();
            }
        });
    }

    refreshStats();
    window.setInterval(refreshStats, 5000);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
            refreshStats();
        }
    });
})();
