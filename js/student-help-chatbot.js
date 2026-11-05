(() => {
    const panel = document.getElementById("student-help-panel");
    const toggle = document.getElementById("student-help-toggle");
    const messages = document.getElementById("student-help-messages");
    const form = document.getElementById("student-help-form");
    const input = document.getElementById("student-help-input");
    if (!panel || !toggle || !messages || !form || !input) {
        return;
    }

    const guides = [
        {
            keywords: ["library", "resource", "material", "notes", "past paper", "article", "find", "search", "course"],
            reply: "Open Library in the left-hand menu to browse approved materials. Choose the IT or Business Administration (BA) folder, then filter by type or course. Use the search box to find a title.",
            action: { label: "Open Library", tab: "library" },
        },
        {
            keywords: ["upload", "share", "submit"],
            reply: "In Library, select Upload resource. Add a title, choose the IT or BA folder and material type, then attach a PDF, DOC, or DOCX file up to 10 MB. Student uploads appear after an administrator approves them.",
            action: { label: "Open Library", tab: "library", upload: true },
        },
        {
            keywords: ["friend", "discover", "request", "invite", "message", "chat", "conversation", "encrypt"],
            reply: "Open Friends. Discover lets you search for students and send friend requests. Once a request is accepted, open Conversations to message that friend. Messaging requires verifying your friend's displayed security fingerprint first.",
            action: { label: "Open Friends", tab: "friends" },
            secondaryAction: { label: "Open Conversations", tab: "friends", friendsView: "messages" },
        },
        {
            keywords: ["community", "communities", "join", "group"],
            reply: "Open Communities to browse IT or BA study groups, filter by topic, and join a community. Use Create community if you want to start a new group.",
            action: { label: "Open Communities", tab: "communities" },
        },
        {
            keywords: ["profile", "name", "institution", "year", "bio", "photo", "picture"],
            reply: "Choose Profile in the left-hand menu. Select Edit profile to update your name, institution, course, year, bio, or profile picture, then save your changes.",
            action: { label: "Open Profile", tab: "profile" },
        },
        {
            keywords: ["password", "login", "sign in", "log in", "reset"],
            reply: "To change a forgotten password, sign out and choose the password-recovery option on the login page. Follow the emailed verification-code steps to set a new password.",
        },
        {
            keywords: ["approved", "pending", "not showing", "missing", "invisible"],
            reply: "Only approved resources appear in the student library. A newly uploaded student resource stays pending until an administrator reviews it. Admin-published course materials appear immediately.",
            action: { label: "Open Library", tab: "library" },
        },
        {
            keywords: ["help", "navigate", "dashboard", "menu", "tab", "where"],
            reply: "Use the left-hand menu to move between Library, Friends, Communities, and Profile. Tell me what you want to do, or use one of the suggested questions below.",
        },
    ];

    function setOpen(open) {
        panel.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
        if (open) {
            input.focus();
            if (!messages.childElementCount) {
                addMessage(
                    "bot",
                    "Hi! I can help you navigate the student dashboard. Ask about finding materials, uploading resources, friends and messages, communities, or your profile.",
                );
            }
        }
    }

    function addMessage(sender, text, actions = []) {
        const message = document.createElement("article");
        message.className = `student-help-message ${sender}`;
        const label = document.createElement("strong");
        label.textContent = sender === "bot" ? "Acadex help" : "You";
        const body = document.createElement("p");
        body.textContent = text;
        message.append(label, body);

        if (actions.length) {
            const actionList = document.createElement("div");
            actionList.className = "student-help-actions";
            actions.forEach(({ label: actionLabel, action }) => {
                const button = document.createElement("button");
                button.type = "button";
                button.textContent = actionLabel;
                button.addEventListener("click", () => navigate(action));
                actionList.append(button);
            });
            message.append(actionList);
        }

        messages.append(message);
        messages.scrollTop = messages.scrollHeight;
    }

    function navigate(action) {
        setOpen(false);
        const tabButton = document.querySelector(`.dashboard-nav-item[data-tab="${action.tab}"]`);
        if (tabButton) {
            tabButton.click();
        }
        if (action.friendsView === "messages") {
            document.querySelector('[data-friends-view="messages"]')?.click();
        }
        if (action.upload) {
            window.openUploadModal();
        }
    }

    function answerQuestion(question) {
        const normalized = question.toLowerCase();
        addMessage("user", question);
        const prioritizedGuide = ["upload", "share", "submit"].some((keyword) =>
            normalized.includes(keyword),
        );
        const guide = guides.find(({ keywords }) =>
            prioritizedGuide && keywords.includes("upload"),
        ) || guides.find(({ keywords }) =>
            keywords.some((keyword) => normalized.includes(keyword)),
        );
        if (!guide) {
            addMessage(
                "bot",
                "I can help with Library materials and uploads, Friends and messaging, Communities, Profile, and login or resource-approval questions. Try asking about one of those.",
                [{ label: "Open Library", action: { tab: "library" } }],
            );
            return;
        }

        const actions = [];
        if (guide.action) {
            actions.push({ label: guide.action.label, action: guide.action });
        }
        if (guide.secondaryAction) {
            actions.push({ label: guide.secondaryAction.label, action: guide.secondaryAction });
        }
        addMessage("bot", guide.reply, actions);
    }

    toggle.addEventListener("click", () => setOpen(panel.hidden));
    document.getElementById("student-help-close").addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !panel.hidden) {
            setOpen(false);
            toggle.focus();
        }
    });
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        const question = input.value.trim();
        if (!question) {
            return;
        }
        input.value = "";
        answerQuestion(question);
    });
    document.querySelectorAll("[data-help-question]").forEach((button) => {
        button.addEventListener("click", () => answerQuestion(button.dataset.helpQuestion));
    });
})();
