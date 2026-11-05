(() => {
    let heartbeatInProgress = false;

    async function sendHeartbeat() {
        if (heartbeatInProgress || document.hidden) {
            return;
        }
        heartbeatInProgress = true;
        try {
            const response = await fetch("/api/student/session-heartbeat", {
                method: "POST",
                headers: { Accept: "application/json" },
                credentials: "same-origin",
                cache: "no-store",
            });
            if (!response.ok) {
                const result = await response.json();
                throw new Error(result.message || "Could not record login activity.");
            }
        } catch (error) {
            console.error("Could not record login activity.", error);
        } finally {
            heartbeatInProgress = false;
        }
    }

    sendHeartbeat();
    window.setInterval(sendHeartbeat, 60_000);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
            sendHeartbeat();
        }
    });
})();
