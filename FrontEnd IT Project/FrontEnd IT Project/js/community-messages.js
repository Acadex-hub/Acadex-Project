document.addEventListener('DOMContentLoaded', () => {
    const workspace = document.querySelector('[data-message-workspace="community"]');
    const list = workspace.querySelector('.message-list');
    const thread = workspace.querySelector('.conversation-thread');
    const conversationList = workspace.querySelector('.conversation-list');
    const messageForm = workspace.querySelector('.message-composer');
    const messageInput = workspace.querySelector('.message-input');
    const attachmentPreview = workspace.querySelector('.attachment-preview');
    const imageInput = workspace.querySelector('.image-attachment');
    const pdfInput = workspace.querySelector('.pdf-attachment');
    const sendButton = messageForm.querySelector('[type="submit"]');
    const attachImageButton = workspace.querySelector('.attach-image-button');
    const attachPdfButton = workspace.querySelector('.attach-pdf-button');
    const headerAvatar = workspace.querySelector('.conversation-header-avatar');
    const nameHeading = workspace.querySelector('.conversation-name');
    const statusLine = workspace.querySelector('.conversation-status');
    const emptyState = workspace.querySelector('.community-inbox-empty');
    const conversations = {};
    let activeConversation = null;
    let stagedAttachment = null;

    const renderLinkedText = (container, text) => {
        const pattern = /https?:\/\/[^\s<]+/gi;
        let cursor = 0;
        let match;
        while ((match = pattern.exec(text)) !== null) {
            const rawUrl = match[0];
            const url = rawUrl.replace(/[.,!?;:)]+$/, '');
            container.append(document.createTextNode(text.slice(cursor, match.index)));
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.target = '_blank';
            anchor.rel = 'noopener noreferrer';
            anchor.textContent = url;
            container.append(anchor, document.createTextNode(rawUrl.slice(url.length)));
            cursor = match.index + rawUrl.length;
        }
        container.append(document.createTextNode(text.slice(cursor)));
    };

    const renderAttachment = (bubble, attachment) => {
        const card = document.createElement('a');
        card.className = `message-attachment-card ${attachment.type === 'image' ? 'image-message-attachment' : 'pdf-message-attachment'}`;
        card.href = attachment.url;
        card.target = '_blank';
        card.rel = 'noopener noreferrer';

        if (attachment.type === 'image') {
            const image = document.createElement('img');
            image.src = attachment.url;
            image.alt = attachment.name;
            image.loading = 'lazy';
            card.append(image);
        } else {
            const icon = document.createElement('span');
            icon.className = 'pdf-attachment-icon';
            icon.textContent = 'PDF';
            const details = document.createElement('span');
            details.className = 'pdf-attachment-details';
            const filename = document.createElement('strong');
            filename.textContent = attachment.name;
            const action = document.createElement('small');
            action.textContent = 'Open document';
            details.append(filename, action);
            card.append(icon, details);
            card.download = attachment.name;
        }
        bubble.append(card);
    };

    const updateConversationPreview = (conversationId, message) => {
        const item = conversationList.querySelector(`[data-contact="${conversationId}"]`);
        if (!item) return;
        item.querySelector('.conversation-preview small').textContent = message.text || message.attachment?.name || 'Attachment';
        item.querySelector('time').textContent = message.time;
    };

    const renderMessages = () => {
        list.replaceChildren();
        conversations[activeConversation].messages.forEach((message) => {
            const row = document.createElement('article');
            row.className = `message-row ${message.from === 'me' ? 'outgoing' : 'incoming'}`;
            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';
            if (message.sender) {
                const sender = document.createElement('strong');
                sender.className = 'message-sender';
                sender.textContent = message.sender;
                bubble.append(sender);
            }
            if (message.text) {
                const text = document.createElement('p');
                renderLinkedText(text, message.text);
                bubble.append(text);
            }
            if (message.attachment) renderAttachment(bubble, message.attachment);
            const time = document.createElement('time');
            time.textContent = message.time;
            bubble.append(time);
            row.append(bubble);
            list.append(row);
        });
        list.scrollTop = list.scrollHeight;
    };

    const selectConversation = (conversationId) => {
        const conversation = conversations[conversationId];
        if (!conversation) return;
        activeConversation = conversationId;
        conversationList.querySelectorAll('.conversation-item').forEach((item) => {
            const selected = item.dataset.contact === conversationId;
            item.classList.toggle('active', selected);
            item.setAttribute('aria-current', String(selected));
        });
        headerAvatar.className = `conversation-avatar group conversation-header-avatar`;
        headerAvatar.textContent = conversation.initial;
        nameHeading.textContent = conversation.name;
        statusLine.textContent = `Group conversation · ${conversation.memberCount}`;
        thread.setAttribute('aria-label', `Group conversation: ${conversation.name}`);
        messageInput.disabled = false;
        sendButton.disabled = false;
        attachImageButton.disabled = false;
        attachPdfButton.disabled = false;
        emptyState.hidden = true;
        renderMessages();
    };

    const makeConversationItem = (conversationId, conversation) => {
        const item = document.createElement('button');
        item.className = 'conversation-item';
        item.type = 'button';
        item.dataset.contact = conversationId;
        const avatar = document.createElement('span');
        avatar.className = 'conversation-avatar group';
        avatar.textContent = conversation.initial;
        const preview = document.createElement('span');
        preview.className = 'conversation-preview';
        const name = document.createElement('strong');
        name.textContent = conversation.name;
        const lastMessage = document.createElement('small');
        lastMessage.textContent = conversation.messages.at(-1)?.text || 'Group conversation';
        preview.append(name, lastMessage);
        const time = document.createElement('time');
        time.textContent = conversation.messages.at(-1)?.time || 'Now';
        item.append(avatar, preview, time);
        conversationList.append(item);
            const conversationCount = conversationList.querySelectorAll('.conversation-item').length;
            workspace.querySelector('.community-conversation-total').textContent = String(conversationCount);
            document.querySelector('.community-message-count').textContent = String(conversationCount);
    };

    window.openCommunityConversation = (conversationId, details) => {
        if (!conversations[conversationId] && details) {
            const now = new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).format(new Date());
            conversations[conversationId] = {
                name: details.name,
                initial: details.initial,
                memberCount: details.status.replace(/^Group conversation\s*·\s*/, ''),
                messages: [{
                    from: 'them',
                    sender: details.sender || 'Community guide',
                    text: details.preview || `Welcome to ${details.name}. Start the conversation here.`,
                    time: now,
                }],
            };
            makeConversationItem(conversationId, conversations[conversationId]);
        }
        if (!conversations[conversationId]) return;
        window.showDashboardTab('communities');
        window.showCommunityView('messages');
        selectConversation(conversationId);
        document.getElementById('community-messages-view').scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const clearStagedAttachment = () => {
        if (stagedAttachment?.url.startsWith('blob:')) URL.revokeObjectURL(stagedAttachment.url);
        stagedAttachment = null;
        attachmentPreview.replaceChildren();
        attachmentPreview.hidden = true;
        imageInput.value = '';
        pdfInput.value = '';
    };

    const stageFile = (file, type) => {
        if (!file) return;
        const allowed = type === 'image'
            ? file.type.startsWith('image/')
            : file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
        if (!allowed) {
            window.alert(type === 'image' ? 'Choose an image file.' : 'Choose a PDF document.');
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            window.alert('Files must be 10 MB or smaller.');
            return;
        }
        clearStagedAttachment();
        stagedAttachment = { type, name: file.name, url: URL.createObjectURL(file) };
        attachmentPreview.hidden = false;
        if (type === 'image') {
            const image = document.createElement('img');
            image.src = stagedAttachment.url;
            image.alt = `Preview of ${file.name}`;
            attachmentPreview.append(image);
        }
        const filename = document.createElement('span');
        filename.className = 'staged-attachment-name';
        filename.textContent = file.name;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'remove-attachment';
        remove.setAttribute('aria-label', `Remove ${file.name}`);
        remove.textContent = '×';
        remove.addEventListener('click', clearStagedAttachment);
        attachmentPreview.append(filename, remove);
    };

    conversationList.addEventListener('click', (event) => {
        const item = event.target.closest('.conversation-item');
        if (item) selectConversation(item.dataset.contact);
    });
    workspace.querySelector('.conversation-search-input').addEventListener('input', (event) => {
        const query = event.target.value.trim().toLowerCase();
        conversationList.querySelectorAll('.conversation-item').forEach((item) => {
            item.hidden = !item.textContent.toLowerCase().includes(query);
        });
    });
    attachImageButton.addEventListener('click', () => imageInput.click());
    attachPdfButton.addEventListener('click', () => pdfInput.click());
    imageInput.addEventListener('change', () => stageFile(imageInput.files[0], 'image'));
    pdfInput.addEventListener('change', () => stageFile(pdfInput.files[0], 'pdf'));
    messageInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            messageForm.requestSubmit();
        }
    });
    messageForm.addEventListener('submit', (event) => {
        event.preventDefault();
        if (!activeConversation) return;
        const text = messageInput.value.trim();
        if (!text && !stagedAttachment) return;
        const message = {
            from: 'me',
            sender: 'You',
            text,
            attachment: stagedAttachment ? { ...stagedAttachment } : null,
            time: new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).format(new Date()),
        };
        conversations[activeConversation].messages.push(message);
        updateConversationPreview(activeConversation, message);
        stagedAttachment = null;
        attachmentPreview.replaceChildren();
        attachmentPreview.hidden = true;
        imageInput.value = '';
        pdfInput.value = '';
        messageInput.value = '';
        renderMessages();
    });
});
