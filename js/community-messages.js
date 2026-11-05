document.addEventListener('DOMContentLoaded', () => {
    const workspace = document.querySelector('[data-message-workspace="community"]');
    const list = workspace.querySelector('.message-list');
    const thread = workspace.querySelector('.conversation-thread');
    const conversationList = workspace.querySelector('.conversation-list');
    const messageForm = workspace.querySelector('.message-composer');
    const messageInput = workspace.querySelector('.message-input');
    const messageType = workspace.querySelector('.community-message-type');
    const sendButton = messageForm.querySelector('[type="submit"]');
    const nameHeading = workspace.querySelector('.conversation-name');
    const statusLine = workspace.querySelector('.conversation-status');
    const emptyState = workspace.querySelector('.community-inbox-empty');
    const errorMessage = workspace.querySelector('.community-message-error');
    const conversations = new Map();
    let activeConversation = null;
    let refreshInProgress = false;
    let sendInProgress = false;

    const requestJson = async (url, options = {}) => {
        const response = await fetch(url, {
            credentials: 'same-origin',
            cache: 'no-store',
            headers: { Accept: 'application/json', ...(options.headers || {}) },
            ...options,
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || 'The request could not be completed.');
        return result;
    };

    const showError = (error) => {
        errorMessage.textContent = error.message || 'Could not load community messages.';
        errorMessage.hidden = false;
    };

    const messageTime = (value) => {
        const date = new Date(value);
        return Number.isNaN(date.getTime())
            ? ''
            : new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).format(date);
    };

    const updateConversationPreview = (conversationId, messages) => {
        const item = conversationList.querySelector(`[data-contact="${CSS.escape(conversationId)}"]`);
        if (!item) return;
        const latest = messages.reduce((current, message) => (
            !current || Number(message.message_id) > Number(current.message_id) ? message : current
        ), null);
        item.querySelector('.conversation-preview small').textContent = latest
            ? `${latest.message_type === 'announcement' ? 'Announcement: ' : ''}${latest.content}`
            : 'Start the conversation';
        item.querySelector('time').textContent = latest ? messageTime(latest.created_at) : '';
    };

    const renderMessages = (messages) => {
        list.replaceChildren();
        messages.forEach((message) => {
            const row = document.createElement('article');
            row.className = `message-row ${message.is_mine ? 'outgoing' : 'incoming'} ${message.is_pinned ? 'is-pinned' : ''} ${message.is_highlighted ? 'is-highlighted' : ''} ${message.message_type === 'announcement' ? 'is-announcement' : ''}`;
            row.dataset.messageId = String(message.message_id);

            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';
            const sender = document.createElement('strong');
            sender.className = 'message-sender';
            sender.textContent = message.author_name;
            bubble.append(sender);

            const markers = document.createElement('div');
            markers.className = 'community-message-markers';
            if (message.message_type === 'announcement') {
                const announcement = document.createElement('span');
                announcement.textContent = 'Announcement';
                markers.append(announcement);
            }
            if (message.is_pinned) {
                const pinned = document.createElement('span');
                pinned.textContent = 'Pinned';
                markers.append(pinned);
            }
            if (message.is_highlighted) {
                const highlighted = document.createElement('span');
                highlighted.textContent = 'Important';
                markers.append(highlighted);
            }
            if (markers.childElementCount) bubble.append(markers);

            const content = document.createElement('p');
            content.textContent = message.content;
            bubble.append(content);

            const time = document.createElement('time');
            time.dateTime = message.created_at;
            time.textContent = messageTime(message.created_at);
            bubble.append(time);

            if (message.can_manage) {
                const actions = document.createElement('div');
                actions.className = 'community-message-actions';
                [
                    ['is_pinned', message.is_pinned ? 'Unpin' : 'Pin'],
                    ['is_highlighted', message.is_highlighted ? 'Remove highlight' : 'Highlight'],
                ].forEach(([field, label]) => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.dataset.messageAction = field;
                    button.textContent = label;
                    button.setAttribute('aria-label', `${label} message`);
                    actions.append(button);
                });
                bubble.append(actions);
            }
            row.append(bubble);
            list.append(row);
        });
        list.scrollTop = list.scrollHeight;
    };

    const loadMessages = async (conversationId) => {
        const conversation = conversations.get(conversationId);
        if (!conversation) return;
        const result = await requestJson(`/api/communities/${encodeURIComponent(conversationId)}/messages`);
        conversation.messages = result.messages;
        updateConversationPreview(conversationId, result.messages);
        if (activeConversation === conversationId) renderMessages(result.messages);
    };

    const selectConversation = async (conversationId) => {
        const conversation = conversations.get(conversationId);
        if (!conversation) return;
        activeConversation = conversationId;
        conversationList.querySelectorAll('.conversation-item').forEach((item) => {
            const selected = item.dataset.contact === conversationId;
            item.classList.toggle('active', selected);
            item.setAttribute('aria-current', String(selected));
        });
        nameHeading.textContent = conversation.name;
        statusLine.textContent = `Group conversation · ${conversation.memberCount} members`;
        thread.setAttribute('aria-label', `Group conversation: ${conversation.name}`);
        messageInput.disabled = false;
        messageType.disabled = false;
        sendButton.disabled = false;
        emptyState.hidden = true;
        errorMessage.hidden = true;
        list.replaceChildren();
        try {
            await loadMessages(conversationId);
        } catch (error) {
            showError(error);
        }
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
        lastMessage.textContent = 'Start the conversation';
        preview.append(name, lastMessage);
        const time = document.createElement('time');
        item.append(avatar, preview, time);
        conversationList.append(item);
    };

    const updateCommunityConversations = (communities) => {
        const joined = communities.filter((community) => community.is_member);
        const joinedIds = new Set(joined.map((community) => String(community.community_id)));
        conversationList.replaceChildren();
        joined.forEach((community) => {
            const id = String(community.community_id);
            const conversation = conversations.get(id) || { messages: [] };
            conversation.name = community.name;
            conversation.initial = community.name.split(/\s+/).map((word) => word[0]).slice(0, 2).join('').toUpperCase();
            conversation.memberCount = Number(community.member_count).toLocaleString();
            conversations.set(id, conversation);
            makeConversationItem(id, conversation);
            updateConversationPreview(id, conversation.messages);
        });
        workspace.querySelector('.community-conversation-total').textContent = String(joined.length);
        document.querySelector('.community-message-count').textContent = String(joined.length);
        emptyState.hidden = joined.length > 0;
        if (activeConversation && !joinedIds.has(activeConversation)) {
            activeConversation = null;
            nameHeading.textContent = 'Community conversations';
            statusLine.textContent = 'Choose a joined community';
            messageInput.disabled = true;
            messageType.disabled = true;
            sendButton.disabled = true;
            list.replaceChildren();
        }
        if (activeConversation) {
            const selected = conversations.get(activeConversation);
            if (selected) {
                nameHeading.textContent = selected.name;
                statusLine.textContent = `Group conversation · ${selected.memberCount} members`;
            }
        }
    };

    window.updateCommunityConversations = updateCommunityConversations;
    updateCommunityConversations(window.communityData || []);

    window.openCommunityConversation = (conversationId, details) => {
        const id = String(conversationId);
        if (!conversations.has(id) && details) {
            const conversation = {
                name: details.name,
                initial: details.initial,
                memberCount: String(details.memberCount || 0),
                messages: [],
            };
            conversations.set(id, conversation);
            makeConversationItem(id, conversation);
            workspace.querySelector('.community-conversation-total').textContent = String(conversations.size);
            document.querySelector('.community-message-count').textContent = String(conversations.size);
            emptyState.hidden = true;
        }
        if (!conversations.has(id)) return;
        window.showDashboardTab('communities');
        window.showCommunityView('messages');
        selectConversation(id);
        document.getElementById('community-messages-view').scrollIntoView({ behavior: 'smooth', block: 'start' });
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

    list.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-message-action]');
        if (!button || !activeConversation) return;
        const row = button.closest('[data-message-id]');
        const message = conversations.get(activeConversation)?.messages.find(
            (item) => String(item.message_id) === row.dataset.messageId,
        );
        if (!message) return;
        button.disabled = true;
        errorMessage.hidden = true;
        try {
            await requestJson(
                `/api/communities/${encodeURIComponent(activeConversation)}/messages/${encodeURIComponent(message.message_id)}`,
                {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ [button.dataset.messageAction]: !message[button.dataset.messageAction] }),
                },
            );
            await loadMessages(activeConversation);
        } catch (error) {
            showError(error);
            button.disabled = false;
        }
    });

    messageInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            messageForm.requestSubmit();
        }
    });

    messageForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!activeConversation || sendInProgress) return;
        const content = messageInput.value.trim();
        if (!content) return;
        sendInProgress = true;
        sendButton.disabled = true;
        errorMessage.hidden = true;
        try {
            await requestJson(`/api/communities/${encodeURIComponent(activeConversation)}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content, message_type: messageType.value }),
            });
            messageInput.value = '';
            await loadMessages(activeConversation);
        } catch (error) {
            showError(error);
        } finally {
            sendInProgress = false;
            sendButton.disabled = !activeConversation;
        }
    });

    window.setInterval(async () => {
        if (document.hidden || !activeConversation || refreshInProgress) return;
        refreshInProgress = true;
        try {
            await loadMessages(activeConversation);
        } catch (error) {
            showError(error);
        } finally {
            refreshInProgress = false;
        }
    }, 10000);

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && activeConversation) {
            loadMessages(activeConversation).catch(showError);
        }
    });
});
