(() => {
    const byId = (id) => document.getElementById(id);
    const dateElement = byId("admin-current-date");
    const errorElement = byId("admin-dashboard-error");
    const numberFormatter = new Intl.NumberFormat();
    const relativeTimeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
    const studentActivityPanel = byId("student-accounts-panel");
    const studentActivityMonth = byId("student-activity-month");
    const studentActivitySelect = byId("student-activity-select");
    const studentActivityError = byId("student-activity-error");
    const studentActivityRows = byId("student-activity-rows");
    let studentActivityData = null;
    let studentActivityLoading = false;

    function updateDate() {
        const now = new Date();
        dateElement.textContent = new Intl.DateTimeFormat(undefined, {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric",
        }).format(now).toUpperCase();
        dateElement.dateTime = now.toISOString();
        byId("admin-footer-year").textContent = String(now.getFullYear());
    }

    function setUnavailable(message) {
        ["admin-student-count", "admin-resource-count", "admin-course-count", "admin-pending-count"]
            .forEach((id) => { byId(id).textContent = "Unavailable"; });
        byId("admin-nav-pending-count").textContent = "—";
        byId("admin-resource-queue-count").textContent = "Queue unavailable";
        byId("admin-student-summary").textContent = "Unavailable";
        byId("admin-course-summary").textContent = "Unavailable";
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 5;
        cell.textContent = "Could not load pending resources.";
        row.append(cell);
        byId("admin-resource-rows").replaceChildren(row);
        byId("admin-activity-list").replaceChildren();
        const item = document.createElement("li");
        item.textContent = "Could not load recent activity.";
        byId("admin-activity-list").append(item);
        errorElement.textContent = message;
        errorElement.hidden = false;
    }

    function relativeTime(value) {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return "Date unavailable";
        }

        const seconds = Math.round((date.getTime() - Date.now()) / 1000);
        const intervals = [
            ["year", 31536000],
            ["month", 2592000],
            ["week", 604800],
            ["day", 86400],
            ["hour", 3600],
            ["minute", 60],
        ];
        const interval = intervals.find(([, duration]) => Math.abs(seconds) >= duration);
        if (!interval) {
            return relativeTimeFormatter.format(seconds, "second");
        }
        return relativeTimeFormatter.format(Math.round(seconds / interval[1]), interval[0]);
    }

    async function readApiResponse(response, description) {
        try {
            return await response.json();
        } catch (_error) {
            throw new Error(
                `${description} The server returned a non-JSON response (HTTP ${response.status}). `
                + "Make sure Flask is running the latest app.py, restart it if needed, and reload this page.",
            );
        }
    }

    function notifyStudentLibraryChanged() {
        if ("BroadcastChannel" in window) {
            const resourceChannel = new BroadcastChannel("acadex-resource-stats");
            resourceChannel.postMessage({ type: "resource-library-changed" });
            resourceChannel.close();
        }
    }

    function renderResources(resources) {
        const rows = byId("admin-resource-rows");
        rows.replaceChildren();
        byId("admin-resource-queue-count").textContent =
            `${numberFormatter.format(resources.length)} shown`;

        if (!resources.length) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 5;
            cell.textContent = "No resources are awaiting review.";
            row.append(cell);
            rows.append(row);
            return;
        }

        resources.forEach((resource) => {
            const row = document.createElement("tr");
            const titleCell = document.createElement("td");
            const title = document.createElement("strong");
            const category = document.createElement("small");
            title.textContent = resource.title;
            category.textContent = `${resource.resource_category || "IT"}${resource.course_name ? ` · ${resource.course_name}` : ""}`;
            titleCell.append(title, category);
            if (resource.description) {
                const description = document.createElement("small");
                description.className = "admin-resource-description";
                description.textContent = resource.description;
                titleCell.append(description);
            }

            const uploaderCell = document.createElement("td");
            uploaderCell.textContent = resource.uploader_name;
            const typeCell = document.createElement("td");
            const resourceTypes = {
                notes: "Notes",
                article: "Articles",
                past_paper: "Past Papers & Memos",
            };
            typeCell.textContent = resourceTypes[resource.resource_type] || resource.resource_type.split("_").join(" ");
            const statusCell = document.createElement("td");
            const status = document.createElement("span");
            status.className = "status-pill pending";
            status.textContent = resource.status;
            statusCell.append(status);
            const reviewCell = document.createElement("td");
            reviewCell.className = "admin-resource-actions";
            if (resource.review_file_url) {
                const download = document.createElement("a");
                download.href = resource.review_file_url;
                download.textContent = "Download file";
                download.target = "_blank";
                download.rel = "noopener noreferrer";
                reviewCell.append(download);
            }
            ["approved", "rejected"].forEach((decision) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = `admin-review-button ${decision}`;
                button.textContent = decision === "approved" ? "Approve" : "Reject";
                button.addEventListener("click", () => reviewResource(resource.resource_id, decision, reviewCell));
                reviewCell.append(button);
            });
            row.append(titleCell, uploaderCell, typeCell, statusCell, reviewCell);
            rows.append(row);
        });
    }

    async function reviewResource(resourceId, decision, actionCell) {
        const buttons = actionCell.querySelectorAll("button");
        buttons.forEach((button) => { button.disabled = true; });
        errorElement.hidden = true;
        try {
            const response = await fetch(`/api/admin/resources/${encodeURIComponent(resourceId)}/review`, {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ status: decision }),
            });
            const result = await readApiResponse(response, "Could not review this resource.");
            if (!response.ok) {
                throw new Error(result.message || "Could not review this resource.");
            }
            if (decision === "approved") {
                notifyStudentLibraryChanged();
            }
            await loadDashboard();
        } catch (error) {
            errorElement.textContent = error.message || "Could not review this resource.";
            errorElement.hidden = false;
            buttons.forEach((button) => { button.disabled = false; });
        }
    }

    function renderActivity(entries) {
        const list = byId("admin-activity-list");
        list.replaceChildren();
        if (!entries.length) {
            const item = document.createElement("li");
            item.textContent = "No recent platform activity.";
            list.append(item);
            return;
        }

        const icons = {
            "new-user": ["＋", "new-user"],
            "new-resource": ["▤", "new-resource"],
            "course-update": ["⌂", "course-update"],
            "community-created": ["♧", "new-user"],
        };
        entries.forEach((entry) => {
            const item = document.createElement("li");
            const [symbol, markerClass] = icons[entry.activity_type] || ["•", "new-user"];
            const marker = document.createElement("span");
            marker.className = `activity-marker ${markerClass}`;
            marker.setAttribute("aria-hidden", "true");
            marker.textContent = symbol;

            const content = document.createElement("div");
            const heading = document.createElement("strong");
            heading.textContent = entry.heading;
            const detail = document.createElement("p");
            detail.textContent = entry.detail;
            const time = document.createElement("time");
            time.dateTime = new Date(entry.occurred_at).toISOString();
            time.title = new Date(entry.occurred_at).toLocaleString();
            time.textContent = relativeTime(entry.occurred_at);
            content.append(heading, detail, time);
            item.append(marker, content);
            list.append(item);
        });
    }

    function renderAuditLogs(entries) {
        const rows = byId("admin-audit-rows");
        rows.replaceChildren();
        byId("admin-audit-count").textContent = `${numberFormatter.format(entries.length)} shown`;
        if (!entries.length) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 5;
            cell.textContent = "No administrator actions have been recorded.";
            row.append(cell);
            rows.append(row);
            return;
        }

        entries.forEach((entry) => {
            const row = document.createElement("tr");
            const occurredAt = new Date(entry.created_at);
            const timeCell = document.createElement("td");
            if (Number.isNaN(occurredAt.getTime())) {
                timeCell.textContent = "Date unavailable";
            } else {
                const time = document.createElement("time");
                time.dateTime = occurredAt.toISOString();
                time.textContent = occurredAt.toLocaleString();
                timeCell.append(time);
            }

            const adminCell = document.createElement("td");
            adminCell.textContent = entry.admin_name;
            const actionCell = document.createElement("td");
            actionCell.textContent = entry.action.split(".").join(" ");
            const targetCell = document.createElement("td");
            targetCell.textContent = entry.target_id === null
                ? entry.target_type
                : `${entry.target_type} #${entry.target_id}`;
            const detailsCell = document.createElement("td");
            detailsCell.textContent = entry.details || "—";
            row.append(timeCell, adminCell, actionCell, targetCell, detailsCell);
            rows.append(row);
        });
    }

    async function loadAuditLogs() {
        const error = byId("admin-audit-error");
        try {
            const response = await fetch("/api/admin/audit-logs", {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });
            const data = await readApiResponse(response, "Could not load the administrator audit log.");
            if (!response.ok) {
                throw new Error(data.message || "Could not load the administrator audit log.");
            }
            renderAuditLogs(data.audit_logs);
            error.hidden = true;
        } catch (loadError) {
            error.textContent = loadError.message || "Could not load the administrator audit log.";
            error.hidden = false;
            byId("admin-audit-count").textContent = "Unavailable";
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 5;
            cell.textContent = "Could not load administrator actions.";
            row.append(cell);
            byId("admin-audit-rows").replaceChildren(row);
        }
    }

    let courseMaterials = [];
    let selectedCourseFolder = "IT";

    function renderCourseMaterials() {
        const folderGrid = byId("admin-course-folder-grid");
        folderGrid.replaceChildren();
        const selectedFolder = courseMaterials.find((folder) => folder.key === selectedCourseFolder);
        courseMaterials.forEach((folder) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `course-folder-card${folder.key === selectedCourseFolder ? " active" : ""}`;
            button.setAttribute("aria-pressed", String(folder.key === selectedCourseFolder));
            const name = document.createElement("strong");
            name.textContent = folder.name;
            const count = document.createElement("span");
            count.textContent = `${numberFormatter.format(folder.material_count)} materials`;
            button.append(name, count);
            button.addEventListener("click", () => {
                selectedCourseFolder = folder.key;
                byId("admin-material-category").value = folder.key;
                renderCourseMaterials();
            });
            folderGrid.append(button);
        });

        const rows = byId("admin-course-material-rows");
        rows.replaceChildren();
        if (!selectedFolder) {
            byId("admin-selected-course-heading").textContent = "Course materials unavailable";
            byId("admin-selected-course-count").textContent = "";
            return;
        }

        byId("admin-selected-course-heading").textContent = selectedFolder.name;
        byId("admin-selected-course-count").textContent =
            `${numberFormatter.format(selectedFolder.material_count)} available`;
        if (!selectedFolder.materials.length) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 5;
            cell.textContent = "No materials are currently available in this course folder.";
            row.append(cell);
            rows.append(row);
            return;
        }

        selectedFolder.materials.forEach((material) => {
            const row = document.createElement("tr");
            const titleCell = document.createElement("td");
            const title = document.createElement("strong");
            title.textContent = material.title;
            titleCell.append(title);
            if (material.description) {
                const description = document.createElement("small");
                description.textContent = material.description;
                titleCell.append(description);
            }
            const typeCell = document.createElement("td");
            const materialTypes = {
                notes: "Notes",
                article: "Articles",
                past_paper: "Past Papers & Memos",
            };
            typeCell.textContent = materialTypes[material.resource_type] || material.resource_type;
            const uploaderCell = document.createElement("td");
            uploaderCell.textContent = material.uploader_name;
            const fileCell = document.createElement("td");
            if (material.material_url) {
                try {
                    const url = new URL(material.material_url, window.location.origin);
                    if (url.protocol === "https:" || url.protocol === "http:") {
                        const link = document.createElement("a");
                        link.className = "course-material-file-link";
                        link.href = url.href;
                        link.target = "_blank";
                        link.rel = "noopener noreferrer";
                        link.textContent = "Open file";
                        fileCell.append(link);
                    } else {
                        fileCell.textContent = "Unavailable";
                    }
                } catch (_error) {
                    fileCell.textContent = "Unavailable";
                }
            } else {
                fileCell.textContent = "No file";
            }
            const actionCell = document.createElement("td");
            const archiveButton = document.createElement("button");
            archiveButton.type = "button";
            archiveButton.className = "student-account-deactivate";
            archiveButton.textContent = "Remove";
            archiveButton.addEventListener("click", (event) => {
                archiveCourseMaterial(material, event.currentTarget);
            });
            actionCell.append(archiveButton);
            row.append(titleCell, typeCell, uploaderCell, fileCell, actionCell);
            rows.append(row);
        });
    }

    async function loadCourseMaterials() {
        const error = byId("admin-course-material-error");
        try {
            const response = await fetch("/api/admin/course-materials", {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
                cache: "no-store",
            });
            const data = await readApiResponse(response, "Could not load course materials.");
            if (!response.ok) {
                throw new Error(data.message || "Could not load course materials.");
            }
            courseMaterials = data.categories;
            byId("admin-course-count").textContent = numberFormatter.format(data.course_count);
            byId("admin-course-summary").textContent =
                `${numberFormatter.format(data.course_count)} courses (IT and BA)`;
            byId("admin-course-folder-count").textContent =
                `${numberFormatter.format(data.course_count)} courses`;
            if (!courseMaterials.some((folder) => folder.key === selectedCourseFolder)) {
                selectedCourseFolder = courseMaterials.length ? courseMaterials[0].key : "";
            }
            byId("admin-material-category").value = selectedCourseFolder;
            renderCourseMaterials();
            error.hidden = true;
        } catch (loadError) {
            error.textContent = loadError.message || "Could not load course materials.";
            error.hidden = false;
            byId("admin-course-folder-count").textContent = "Unavailable";
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 5;
            cell.textContent = "Could not load course materials.";
            row.append(cell);
            byId("admin-course-material-rows").replaceChildren(row);
        }
    }

    async function archiveCourseMaterial(material, button) {
        if (!window.confirm(`Remove "${material.title}" from the student library? The file will be retained in the archive.`)) {
            return;
        }

        button.disabled = true;
        const error = byId("admin-course-material-error");
        error.hidden = true;
        try {
            const response = await fetch(
                `/api/admin/course-materials/${encodeURIComponent(material.resource_id)}/archive`,
                { method: "POST", headers: { Accept: "application/json" }, credentials: "same-origin" },
            );
            const result = await readApiResponse(response, "Could not remove the course material.");
            if (!response.ok) {
                throw new Error(result.message || "Could not remove the course material.");
            }
            await loadCourseMaterials();
            await loadAuditLogs();
            notifyStudentLibraryChanged();
        } catch (archiveError) {
            error.textContent = archiveError.message || "Could not remove the course material.";
            error.hidden = false;
            button.disabled = false;
        }
    }

    async function addCourseMaterial(event) {
        event.preventDefault();
        const form = byId("admin-add-course-material-form");
        const submitButton = form.querySelector('button[type="submit"]');
        const error = byId("admin-course-material-error");
        submitButton.disabled = true;
        error.hidden = true;
        try {
            const response = await fetch("/api/admin/course-materials", {
                method: "POST",
                headers: { Accept: "application/json" },
                credentials: "same-origin",
                body: new FormData(form),
            });
            const result = await readApiResponse(response, "Could not publish the course material.");
            if (!response.ok) {
                throw new Error(result.message || "Could not publish the course material.");
            }
            form.reset();
            byId("admin-material-category").value = selectedCourseFolder;
            await loadCourseMaterials();
            await loadAuditLogs();
            notifyStudentLibraryChanged();
        } catch (uploadError) {
            error.textContent = uploadError.message || "Could not publish the course material.";
            error.hidden = false;
        } finally {
            submitButton.disabled = false;
        }
    }

    function renderStudentActivityChart(student) {
        const chart = byId("student-activity-chart");
        chart.replaceChildren();
        const days = student.daily_hours;
        const width = 56 + days.length * 24;
        const height = 270;
        const plotTop = 18;
        const plotHeight = 210;
        const plotLeft = 42;
        const plotWidth = days.length * 24;
        const maxHours = Math.max(0, ...days.map((day) => day.hours || 0));
        const scaleMax = Math.max(1, Math.ceil(maxHours));
        chart.setAttribute("viewBox", `0 0 ${width} ${height}`);
        chart.setAttribute("width", String(width));
        chart.setAttribute("height", String(height));
        chart.setAttribute(
            "aria-label",
            `Daily login hours for ${student.full_name} in ${studentActivityData.month}`,
        );

        const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
        title.textContent = `Hours signed in per day — ${student.full_name}, ${studentActivityData.month}`;
        chart.append(title);

        [0, scaleMax / 2, scaleMax].forEach((value) => {
            const y = plotTop + plotHeight - (value / scaleMax) * plotHeight;
            const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
            line.setAttribute("x1", String(plotLeft));
            line.setAttribute("x2", String(plotLeft + plotWidth));
            line.setAttribute("y1", String(y));
            line.setAttribute("y2", String(y));
            line.setAttribute("class", "chart-gridline");
            chart.append(line);

            const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
            label.setAttribute("x", String(plotLeft - 7));
            label.setAttribute("y", String(y + 3));
            label.setAttribute("text-anchor", "end");
            label.setAttribute("class", "chart-axis-label");
            label.textContent = `${Number(value.toFixed(1))}h`;
            chart.append(label);
        });

        days.forEach((day, index) => {
            const centerX = plotLeft + index * 24 + 12;
            const barHeight = day.hours === null
                ? 1
                : Math.max(1, (day.hours / scaleMax) * plotHeight);
            const bar = document.createElementNS("http://www.w3.org/2000/svg", "rect");
            bar.setAttribute("x", String(centerX - 7));
            bar.setAttribute("y", String(plotTop + plotHeight - barHeight));
            bar.setAttribute("width", "14");
            bar.setAttribute("height", String(barHeight));
            bar.setAttribute("rx", "2");
            bar.setAttribute("class", day.hours === null ? "chart-no-data" : "chart-bar");
            const barTitle = document.createElementNS("http://www.w3.org/2000/svg", "title");
            barTitle.textContent = day.hours === null
                ? `${day.date}: no tracking data`
                : `${day.date}: ${day.hours.toFixed(2)} hours`;
            bar.append(barTitle);
            chart.append(bar);

            const dayLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
            dayLabel.setAttribute("x", String(centerX));
            dayLabel.setAttribute("y", String(plotTop + plotHeight + 20));
            dayLabel.setAttribute("text-anchor", "middle");
            dayLabel.setAttribute("class", "chart-axis-label");
            dayLabel.textContent = String(day.day);
            chart.append(dayLabel);
        });

        const hoursLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
        hoursLabel.setAttribute("x", "10");
        hoursLabel.setAttribute("y", "12");
        hoursLabel.setAttribute("class", "chart-axis-label");
        hoursLabel.textContent = "Hours";
        chart.append(hoursLabel);
    }

    function renderStudentActivity() {
        if (!studentActivityData) {
            return;
        }

        const selectedId = studentActivitySelect.value;
        const activeStudents = studentActivityData.students.filter(
            (student) => student.account_status === "active",
        );
        const selectedStudent = activeStudents.find(
            (student) => String(student.user_id) === selectedId,
        );
        studentActivityRows.replaceChildren();

        if (!studentActivityData.students.length) {
            studentActivitySelect.replaceChildren();
            studentActivitySelect.disabled = true;
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 4;
            cell.textContent = "There are no student accounts.";
            row.append(cell);
            studentActivityRows.append(row);
            byId("student-activity-total").textContent = "No student accounts";
            byId("student-activity-chart").replaceChildren();
            return;
        }

        studentActivityData.students.forEach((student) => {
            const row = document.createElement("tr");
            if (String(student.user_id) === selectedId) {
                row.className = "selected";
            }
            const nameCell = document.createElement("td");
            if (student.account_status === "active") {
                const selectButton = document.createElement("button");
                selectButton.type = "button";
                selectButton.className = "student-activity-student";
                selectButton.dataset.studentId = String(student.user_id);
                selectButton.setAttribute("aria-pressed", String(String(student.user_id) === selectedId));
                selectButton.textContent = student.full_name;
                nameCell.append(selectButton);
            } else {
                nameCell.textContent = student.full_name;
            }

            const emailCell = document.createElement("td");
            emailCell.textContent = student.email;
            const hoursCell = document.createElement("td");
            hoursCell.textContent = student.account_status === "active"
                ? `${student.total_hours.toFixed(2)} h`
                : "—";
            const accountCell = document.createElement("td");
            const statusButton = document.createElement("button");
            statusButton.type = "button";
            statusButton.className = student.account_status === "active"
                ? "student-account-deactivate"
                : "student-account-reactivate";
            statusButton.textContent = student.account_status === "active" ? "Deactivate" : "Reactivate";
            statusButton.addEventListener("click", (event) => {
                const nextStatus = student.account_status === "active" ? "suspended" : "active";
                updateStudentStatus(student, nextStatus, event.currentTarget);
            });
            accountCell.append(statusButton);
            row.append(nameCell, emailCell, hoursCell, accountCell);
            studentActivityRows.append(row);
        });

        if (!activeStudents.length) {
            studentActivitySelect.replaceChildren();
            studentActivitySelect.disabled = true;
            byId("student-activity-total").textContent = "No active student accounts";
            byId("student-activity-chart").replaceChildren();
            return;
        }

        if (!selectedStudent) {
            return;
        }
        byId("student-activity-total").textContent =
            `${selectedStudent.total_hours.toFixed(2)} hours this month`;
        renderStudentActivityChart(selectedStudent);
    }

    async function updateStudentStatus(student, accountStatus, button) {
        const reactivating = accountStatus === "active";
        const confirmation = reactivating
            ? `Reactivate ${student.full_name}'s account? They will be able to sign in again using their existing password.`
            : `Deactivate ${student.full_name}'s account? They will lose access, but their account data will be retained.`;
        if (!window.confirm(confirmation)) {
            return;
        }

        button.disabled = true;
        studentActivityError.hidden = true;
        try {
            const response = await fetch(`/api/admin/students/${encodeURIComponent(student.user_id)}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ account_status: accountStatus }),
            });
            const failureMessage = reactivating
                ? "Could not reactivate the student account."
                : "Could not deactivate the student account.";
            const result = await readApiResponse(response, failureMessage);
            if (!response.ok) {
                throw new Error(result.message || failureMessage);
            }
            await loadStudentActivity();
            await loadAuditLogs();
        } catch (error) {
            studentActivityError.textContent = error.message || "Could not update the student account.";
            studentActivityError.hidden = false;
        } finally {
            button.disabled = false;
        }
    }

    async function createStudent(event) {
        event.preventDefault();
        const form = byId("admin-add-student-form");
        const submitButton = form.querySelector('button[type="submit"]');
        submitButton.disabled = true;
        studentActivityError.hidden = true;
        try {
            const response = await fetch("/api/admin/students", {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({
                    full_name: byId("admin-new-student-name").value,
                    email: byId("admin-new-student-email").value,
                    password: byId("admin-new-student-password").value,
                }),
            });
            const result = await readApiResponse(response, "Could not create the student account.");
            if (!response.ok) {
                throw new Error(result.message || "Could not create the student account.");
            }
            form.reset();
            await loadStudentActivity();
            await loadAuditLogs();
        } catch (error) {
            studentActivityError.textContent = error.message || "Could not create the student account.";
            studentActivityError.hidden = false;
        } finally {
            submitButton.disabled = false;
        }
    }

    async function loadStudentActivity() {
        if (studentActivityLoading || !studentActivityMonth.value) {
            return;
        }
        studentActivityLoading = true;
        studentActivityError.hidden = true;
        studentActivitySelect.disabled = true;
        const month = studentActivityMonth.value;
        try {
            const response = await fetch(
                `/api/admin/student-activity?month=${encodeURIComponent(month)}`,
                { headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store" },
            );
            const data = await readApiResponse(response, "Could not load student login activity.");
            if (!response.ok) {
                throw new Error(data.message || "Could not load student login activity.");
            }

            studentActivityData = data;
            const previousStudent = studentActivitySelect.value;
            studentActivitySelect.replaceChildren();
            const activeStudents = data.students.filter(
                (student) => student.account_status === "active",
            );
            activeStudents.forEach((student) => {
                const option = document.createElement("option");
                option.value = String(student.user_id);
                option.textContent = student.full_name;
                studentActivitySelect.append(option);
            });
            if (activeStudents.some((student) => String(student.user_id) === previousStudent)) {
                studentActivitySelect.value = previousStudent;
            }
            studentActivitySelect.disabled = activeStudents.length === 0;
            const trackingDate = new Date(data.tracking_started_at);
            byId("student-activity-note").textContent =
                `Login time is tracked from ${trackingDate.toLocaleString()}. Earlier days show “No data”. ` +
                "Sessions without a heartbeat expire after 2 minutes.";
            renderStudentActivity();
        } catch (error) {
            studentActivityError.textContent = error.message || "Could not load student login activity.";
            studentActivityError.hidden = false;
        } finally {
            studentActivitySelect.disabled = !studentActivityData || !studentActivityData.students.some(
                (student) => student.account_status === "active",
            );
            studentActivityLoading = false;
        }
    }

    async function loadDashboard() {
        updateDate();
        try {
            const response = await fetch("/api/admin/dashboard", {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });
            const data = await readApiResponse(response, "Could not load admin dashboard data.");
            if (!response.ok) {
                throw new Error(data.message || "Could not load admin dashboard data.");
            }

            const stats = data.stats;
            byId("admin-account-name").textContent = data.admin_name;
            byId("admin-account-mark").textContent = data.admin_name.trim().charAt(0).toUpperCase() || "A";
            byId("admin-student-count").textContent = numberFormatter.format(stats.student_count);
            byId("admin-resource-count").textContent = numberFormatter.format(stats.resource_count);
            byId("admin-course-count").textContent = numberFormatter.format(stats.course_count);
            byId("admin-pending-count").textContent = numberFormatter.format(stats.pending_resource_count);
            byId("admin-nav-pending-count").textContent = numberFormatter.format(stats.pending_resource_count);
            byId("admin-student-summary").textContent =
                `${numberFormatter.format(stats.student_count)} active student accounts`;
            byId("admin-course-summary").textContent =
                `${numberFormatter.format(stats.course_count)} courses (IT and BA)`;
            renderResources(data.pending_resources);
            renderActivity(data.activity);
            errorElement.hidden = true;
            await loadAuditLogs();
            if (!byId("course-materials-panel").hidden) {
                await loadCourseMaterials();
            }
        } catch (error) {
            setUnavailable(error.message || "Could not load admin dashboard data.");
        }
    }

    byId("admin-signout").addEventListener("click", async (event) => {
        event.preventDefault();
        try {
            const response = await fetch("/api/logout", { method: "POST", credentials: "same-origin" });
            if (!response.ok) {
                throw new Error("Could not sign out. Please try again.");
            }
            window.location.assign("/indext.html?tab=login");
        } catch (error) {
            errorElement.textContent = error.message;
            errorElement.hidden = false;
        }
    });

    byId("students").addEventListener("click", (event) => {
        event.preventDefault();
        studentActivityPanel.hidden = false;
        studentActivityPanel.scrollIntoView({ behavior: "smooth", block: "start" });
        if (!studentActivityMonth.value) {
            const now = new Date();
            studentActivityMonth.value =
                `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
        }
        loadStudentActivity();
    });
    const courseMaterialsPanel = byId("course-materials-panel");
    const openCourseMaterials = (event) => {
        event.preventDefault();
        courseMaterialsPanel.hidden = false;
        courseMaterialsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
        loadCourseMaterials();
    };
    byId("admin-courses-link").addEventListener("click", openCourseMaterials);
    document.querySelector('.admin-nav-link[href="#course-materials-panel"]')
        .addEventListener("click", openCourseMaterials);
    byId("admin-add-course-material-form").addEventListener("submit", addCourseMaterial);
    byId("admin-add-student-form").addEventListener("submit", createStudent);
    document.querySelector('.admin-nav-link[href="#students"]').addEventListener("click", (event) => {
        event.preventDefault();
        byId("students").click();
    });
    studentActivityMonth.addEventListener("change", loadStudentActivity);
    studentActivitySelect.addEventListener("change", renderStudentActivity);
    studentActivityRows.addEventListener("click", (event) => {
        const button = event.target.closest("[data-student-id]");
        if (button) {
            studentActivitySelect.value = button.dataset.studentId;
            renderStudentActivity();
        }
    });
    window.setInterval(() => {
        if (!studentActivityPanel.hidden && !document.hidden) {
            loadStudentActivity();
        }
    }, 60_000);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && !studentActivityPanel.hidden) {
            loadStudentActivity();
        }
    });

    loadDashboard();
    window.setInterval(loadDashboard, 60000);
})();
