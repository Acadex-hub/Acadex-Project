document.addEventListener('DOMContentLoaded', () => {
    const conversations = {
        amara: {
            kind: 'private', name: 'Amara Pillay', status: 'Private conversation · Online', initial: 'A', avatar: 'violet',
            messages: [
                { from: 'them', text: 'Hey Sam, I found a helpful guide for our database revision.', time: '10:38' },
                { from: 'them', text: 'This explanation was useful: https://www.example.com/database-notes', time: '10:42' },
            ],
        },
        katlego: {
            kind: 'private', name: 'Katlego Maseko', status: 'Private conversation · Last active yesterday', initial: 'K', avatar: 'orange',
            messages: [
                { from: 'them', text: 'I finished the networking practice questions.', time: 'Yesterday' },
                { from: 'me', text: 'Nice, how was the subnetting section?', time: 'Yesterday' },
                { from: 'them', text: 'Thanks, that helps!', time: 'Yesterday' },
            ],
        },
        lwazi: {
            kind: 'private', name: 'Lwazi Dlamini', status: 'Private conversation · Last active Monday', initial: 'L', avatar: 'blue',
            messages: [
                { from: 'them', text: 'Can you send the notes from the machine learning session?', time: 'Monday' },
            ],
        },
    };

    const list = document.getElementById('message-list');
    const thread = document.querySelector('.conversation-thread');
    const conversationList = document.getElementById('conversation-list');
    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');
    const attachmentPreview = document.getElementById('attachment-preview');
    const imageInput = document.getElementById('image-attachment');
    const pdfInput = document.getElementById('pdf-attachment');
    let activeConversation = 'amara';
    let stagedAttachment = null;

    const createLinkedText = (container, text) => {
        const linkPattern = /https?:\/\/[^\s<]+/gi;
        let cursor = 0;
        let match;

        while ((match = linkPattern.exec(text)) !== null) {
            const rawUrl = match[0];
            const url = rawUrl.replace(/[.,!?;:)]+$/, '');
            const punctuation = rawUrl.slice(url.length);
            container.append(document.createTextNode(text.slice(cursor, match.index)));

            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.target = '_blank';
            anchor.rel = 'noopener noreferrer';
            anchor.textContent = url;
            container.append(anchor, document.createTextNode(punctuation));
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

    const renderMessages = () => {
        list.replaceChildren();
        conversations[activeConversation].messages.forEach((message) => {
            const row = document.createElement('article');
            row.className = `message-row ${message.from === 'me' ? 'outgoing' : 'incoming'}`;
            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';

            if (conversations[activeConversation].kind === 'group' && message.sender) {
                const sender = document.createElement('strong');
                sender.className = 'message-sender';
                sender.textContent = message.sender;
                bubble.append(sender);
            }

            if (message.text) {
                const text = document.createElement('p');
                createLinkedText(text, message.text);
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

    const selectConversation = (contactId) => {
        const conversation = conversations[contactId];
        if (!conversation) return;
        activeConversation = contactId;
        conversationList.querySelectorAll('.conversation-item').forEach((item) => {
            const selected = item.dataset.contact === contactId;
            item.classList.toggle('active', selected);
            item.setAttribute('aria-current', selected ? 'true' : 'false');
        });

        const avatar = thread.querySelector('.conversation-header .conversation-avatar');
        avatar.className = `conversation-avatar ${conversation.avatar}`;
        avatar.replaceChildren(document.createTextNode(conversation.initial));
        if (conversation.kind !== 'group' && conversation.status.includes('Online')) {
            const presence = document.createElement('i');
            presence.className = 'presence-dot';
            avatar.append(presence);
        }
        document.getElementById('conversation-name').textContent = conversation.name;
        document.getElementById('conversation-status').textContent = conversation.status;
        thread.classList.toggle('is-group-conversation', conversation.kind === 'group');
        thread.setAttribute('aria-label', conversation.kind === 'group'
            ? `Group conversation: ${conversation.name}`
            : `Private conversation with ${conversation.name}`);
        renderMessages();
    };

    window.openMessageConversation = (contactId, newConversation = null) => {
        if (!conversations[contactId] && newConversation) {
            conversations[contactId] = {
                kind: 'group',
                name: newConversation.name,
                status: newConversation.status,
                initial: newConversation.initial,
                avatar: newConversation.avatar,
                messages: [{
                    from: 'them',
                    sender: newConversation.sender || 'Community guide',
                    text: newConversation.preview || `Welcome to ${newConversation.name}. Start the conversation here.`,
                    time: new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).format(new Date()),
                }],
            };
            const item = document.createElement('button');
            item.className = 'conversation-item';
            item.type = 'button';
            item.dataset.contact = contactId;
            const avatar = document.createElement('span');
            avatar.className = `conversation-avatar ${newConversation.avatar}`;
            avatar.textContent = newConversation.initial;
            const preview = document.createElement('span');
            preview.className = 'conversation-preview';
            const name = document.createElement('strong');
            name.textContent = newConversation.name;
            const lastMessage = document.createElement('small');
            lastMessage.textContent = newConversation.preview || 'Group conversation';
            preview.append(name, lastMessage);
            const time = document.createElement('time');
            time.textContent = 'Now';
            item.append(avatar, preview, time);
            conversationList.append(item);
            document.querySelector('.conversation-sidebar-heading > span').textContent = conversationList.querySelectorAll('.conversation-item').length;
        }

        if (!conversations[contactId]) return;
        window.showDashboardTab('friends');
        window.showFriendsView('messages');
        selectConversation(contactId);
        document.querySelector('.messages-section-rule').scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    document.querySelector('.friend-list').addEventListener('click', (event) => {
        const friend = event.target.closest('[data-message-contact]');
        if (friend) window.openMessageConversation(friend.dataset.messageContact);
    });

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
            const thumbnail = document.createElement('img');
            thumbnail.src = stagedAttachment.url;
            thumbnail.alt = `Preview of ${file.name}`;
            attachmentPreview.append(thumbnail);
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
        const button = event.target.closest('.conversation-item');
        if (button) selectConversation(button.dataset.contact);
    });

    document.getElementById('conversation-search').addEventListener('input', (event) => {
        const query = event.target.value.trim().toLowerCase();
        conversationList.querySelectorAll('.conversation-item').forEach((item) => {
            item.hidden = !item.textContent.toLowerCase().includes(query);
        });
    });

    document.getElementById('attach-image-button').addEventListener('click', () => imageInput.click());
    document.getElementById('attach-pdf-button').addEventListener('click', () => pdfInput.click());
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
        const text = messageInput.value.trim();
        if (!text && !stagedAttachment) return;

        const message = {
            from: 'me',
            text,
            attachment: stagedAttachment ? { ...stagedAttachment } : null,
            time: new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).format(new Date()),
        };
        conversations[activeConversation].messages.push(message);
        const conversationItem = conversationList.querySelector(`[data-contact="${activeConversation}"]`);
        const preview = conversationItem.querySelector('.conversation-preview small');
        preview.textContent = message.text || message.attachment.name;
        conversationItem.querySelector('time').textContent = message.time;
        stagedAttachment = null;
        attachmentPreview.replaceChildren();
        attachmentPreview.hidden = true;
        imageInput.value = '';
        pdfInput.value = '';
        messageInput.value = '';
        renderMessages();
    });

    selectConversation(activeConversation);
});
