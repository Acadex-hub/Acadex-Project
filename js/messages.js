document.addEventListener('DOMContentLoaded', () => {
    const secureCrypto = window.SecureMessagingCrypto;
    const list = document.getElementById('message-list');
    const thread = document.querySelector('.conversation-thread');
    const conversationList = document.getElementById('conversation-list');
    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');
    const attachmentInput = document.getElementById('private-attachment-input');
    const attachmentButton = document.getElementById('choose-private-attachment');
    const attachmentPreview = document.getElementById('private-attachment-preview');
    const attachmentName = document.getElementById('private-attachment-name');
    const removeAttachmentButton = document.getElementById('remove-private-attachment');
    const messageError = document.getElementById('message-error');
    const emptyConversations = document.getElementById('empty-conversations');
    const verifyKeyButton = document.getElementById('verify-encryption-key');
    const friends = new Map();
    const peerIdentities = new Map();
    const attachmentsById = new Map();
    let activeConversation = null;
    let signedInUserId = null;
    let identity = null;
    let databasePromise;
    let messageRefreshInProgress = false;
    let messageSendInProgress = false;
    let activeConversationVerified = false;

    const requestJson = async (url, options = {}) => {
        const response = await fetch(url, {
            credentials: 'same-origin',
            cache: 'no-store',
            headers: { Accept: 'application/json', ...(options.headers || {}) },
            ...options,
        });
        const result = await response.json();
        if (!response.ok) {
            const error = new Error(result.message || 'The request could not be completed.');
            error.status = response.status;
            throw error;
        }
        return result;
    };

    const openKeyDatabase = () => {
        if (!databasePromise) {
            databasePromise = new Promise((resolve, reject) => {
                const request = indexedDB.open('acadex-secure-messaging', 1);
                request.onupgradeneeded = () => {
                    const database = request.result;
                    if (!database.objectStoreNames.contains('identities')) {
                        database.createObjectStore('identities', { keyPath: 'userId' });
                    }
                    if (!database.objectStoreNames.contains('peerPins')) {
                        database.createObjectStore('peerPins', { keyPath: 'id' });
                    }
                };
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error || new Error('Could not open secure key storage.'));
            });
        }
        return databasePromise;
    };

    const storeValue = async (storeName, mode, action) => {
        const database = await openKeyDatabase();
        return new Promise((resolve, reject) => {
            const transaction = database.transaction(storeName, mode);
            const request = action(transaction.objectStore(storeName));
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error('Could not access secure key storage.'));
            transaction.onerror = () => reject(transaction.error || new Error('Secure key storage failed.'));
        });
    };

    const getIdentity = async () => {
        if (!window.isSecureContext || !window.crypto?.subtle || !window.indexedDB) {
            throw new Error('Secure messaging requires a modern browser on HTTPS or localhost.');
        }
        if (identity) return identity;

        const registered = await requestJson('/api/encryption-key');
        const saved = await storeValue('identities', 'readonly', (store) => store.get(signedInUserId));
        if (saved) {
            if (registered.public_key && registered.public_key !== saved.publicBundle) {
                throw new Error('Your encryption key does not match this browser. Messaging is paused to protect your conversations.');
            }
            if (!registered.public_key) {
                await requestJson('/api/encryption-key', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ public_key: saved.publicBundle }),
                });
            }
            identity = saved;
            return identity;
        }
        if (registered.public_key) {
            throw new Error('This account has an encryption key in another browser. This browser cannot recover it; use the original browser to read its messages.');
        }

        const keyMaterial = await secureCrypto.createIdentity();
        const record = { userId: signedInUserId, ...keyMaterial };
        await storeValue('identities', 'readwrite', (store) => store.put(record));
        try {
            await requestJson('/api/encryption-key', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ public_key: record.publicBundle }),
            });
        } catch (error) {
            if (error.status === 409) {
                await storeValue('identities', 'readwrite', (store) => store.delete(signedInUserId));
            }
            throw error;
        }
        identity = record;
        return identity;
    };

    const getPeerIdentity = async (friendId) => {
        const result = await requestJson(`/api/friends/${encodeURIComponent(friendId)}/encryption-key`);
        if (!result.public_key) {
            throw new Error('This friend needs to open the dashboard in their browser to enable secure messaging.');
        }
        const pinId = `${signedInUserId}:${friendId}`;
        const savedPin = await storeValue('peerPins', 'readonly', (store) => store.get(pinId));
        if (savedPin && savedPin.publicBundle !== result.public_key) {
            throw new Error('This friend’s encryption key changed. Messaging is paused; compare fingerprints with them before continuing.');
        }

        const cached = peerIdentities.get(String(friendId));
        if (cached?.publicBundle === result.public_key) {
            cached.verified = savedPin?.verified === true;
            return cached;
        }

        const peer = await secureCrypto.importPublicBundle(result.public_key);
        peer.verified = savedPin?.verified === true;
        if (!savedPin) {
            await storeValue('peerPins', 'readwrite', (store) => store.put({
                id: pinId,
                publicBundle: result.public_key,
                verified: false,
            }));
        }
        peerIdentities.set(String(friendId), peer);
        return peer;
    };

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

    const formatFileSize = (size) => {
        if (size < 1024) return `${size} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    };

    const setComposerEnabled = (enabled) => {
        const composerEnabled = enabled && !messageSendInProgress;
        messageInput.disabled = !composerEnabled;
        attachmentInput.disabled = !composerEnabled;
        attachmentButton.disabled = !composerEnabled;
        removeAttachmentButton.disabled = messageSendInProgress;
        messageForm.querySelector('[type="submit"]').disabled = !composerEnabled;
    };

    const clearStagedAttachment = () => {
        attachmentInput.value = '';
        attachmentPreview.hidden = true;
        attachmentName.textContent = '';
    };

    const renderMessages = (messages) => {
        list.replaceChildren();
        attachmentsById.clear();
        if (!messages.length) {
            const empty = document.createElement('p');
            empty.className = 'empty-state';
            empty.textContent = 'No messages yet. Send a message to get started.';
            list.append(empty);
        }
        messages.forEach((message) => {
            const row = document.createElement('article');
            row.className = `message-row ${Number(message.sender_id) === Number(signedInUserId) ? 'outgoing' : 'incoming'}`;
            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';
            if (message.body.text) {
                const text = document.createElement('p');
                text.style.whiteSpace = 'pre-wrap';
                createLinkedText(text, message.body.text);
                bubble.append(text);
            }
            if (message.body.attachment) {
                const attachment = message.body.attachment;
                attachmentsById.set(attachment.id, {
                    attachment,
                    senderId: message.sender_id,
                    recipientId: message.recipient_id,
                });
                const download = document.createElement('button');
                download.className = 'message-attachment-card pdf-message-attachment';
                download.type = 'button';
                download.dataset.attachmentId = attachment.id;
                download.setAttribute('aria-label', `Decrypt and download ${attachment.name}`);
                const icon = document.createElement('span');
                icon.className = 'pdf-attachment-icon';
                icon.textContent = 'FILE';
                const details = document.createElement('span');
                details.className = 'pdf-attachment-details';
                const name = document.createElement('strong');
                name.textContent = attachment.name;
                const size = document.createElement('small');
                size.textContent = `Encrypted · ${formatFileSize(attachment.size)}`;
                details.append(name, size);
                download.append(icon, details);
                bubble.append(download);
            }
            const time = document.createElement('time');
            const sentAt = new Date(message.created_at);
            time.textContent = Number.isNaN(sentAt.getTime())
                ? ''
                : new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).format(sentAt);
            bubble.append(time);
            row.append(bubble);
            list.append(row);
        });
        list.scrollTop = list.scrollHeight;
    };

    const renderConversationList = () => {
        conversationList.replaceChildren();
        const sortedFriends = [...friends.values()].sort((left, right) => left.username.localeCompare(right.username));
        sortedFriends.forEach((friend) => {
            const item = document.createElement('button');
            item.className = 'conversation-item';
            item.type = 'button';
            item.dataset.contact = friend.user_id;
            item.setAttribute('aria-current', 'false');
            const avatar = document.createElement('span');
            avatar.className = 'conversation-avatar violet';
            avatar.textContent = friend.username.trim().charAt(0).toUpperCase() || '?';
            const preview = document.createElement('span');
            preview.className = 'conversation-preview';
            const name = document.createElement('strong');
            name.textContent = friend.username;
            const hint = document.createElement('small');
            hint.textContent = 'End-to-end encrypted';
            preview.append(name, hint);
            item.append(avatar, preview);
            conversationList.append(item);
        });
        document.querySelector('.conversation-sidebar-heading > span').textContent = sortedFriends.length;
        document.querySelectorAll('.private-message-count').forEach((counter) => {
            counter.textContent = sortedFriends.length;
        });
        emptyConversations.hidden = sortedFriends.length > 0;
        if (activeConversation && !friends.has(String(activeConversation))) {
            activeConversation = null;
            setComposerEnabled(false);
            document.getElementById('conversation-name').textContent = 'Select a friend';
            document.getElementById('conversation-status').textContent = 'Choose an accepted friend to start messaging.';
            list.replaceChildren();
        }
    };

    const loadFriends = async () => {
        try {
            const [friendResult, userResult] = await Promise.all([
                requestJson('/api/friends'),
                requestJson('/api/me'),
            ]);
            friends.clear();
            friendResult.friends.forEach((friend) => friends.set(String(friend.user_id), friend));
            signedInUserId = userResult.user_id;
            renderConversationList();
            if (activeConversation && friends.has(String(activeConversation))) {
                await selectConversation(String(activeConversation));
            }
        } catch (error) {
            emptyConversations.textContent = error.message;
            emptyConversations.hidden = false;
        }
    };

    const loadMessages = async (friendId) => {
        const ownIdentity = await getIdentity();
        const peer = await getPeerIdentity(friendId);
        const fingerprint = await secureCrypto.fingerprintFor(peer.publicBundle);
        if (!peer.verified) {
            activeConversationVerified = false;
            document.getElementById('conversation-status').textContent =
                `Fingerprint not verified: ${fingerprint}`;
            document.getElementById('conversation-status').title =
                'Compare this fingerprint with your friend through a separate trusted channel before verifying.';
            verifyKeyButton.hidden = false;
            setComposerEnabled(false);
            list.replaceChildren();
            const verificationNotice = document.createElement('p');
            verificationNotice.className = 'empty-state';
            verificationNotice.textContent = 'Compare this fingerprint with your friend through a trusted channel, then verify it to unlock messages.';
            list.append(verificationNotice);
            return false;
        }
        verifyKeyButton.hidden = true;
        const result = await requestJson(`/api/friends/${encodeURIComponent(friendId)}/messages`);
        if (String(activeConversation) !== String(friendId)) return;
        const messages = await Promise.all(result.messages.map(async (message) => ({
            ...message,
            body: await secureCrypto.decryptMessage(message, signedInUserId, friendId, ownIdentity, peer),
        })));
        if (String(activeConversation) !== String(friendId)) return;
        renderMessages(messages);
        const item = [...conversationList.querySelectorAll('.conversation-item')]
            .find((conversationItem) => conversationItem.dataset.contact === String(friendId));
        if (item) {
            const preview = item.querySelector('.conversation-preview small');
            const latest = messages[messages.length - 1]?.body;
            preview.textContent = latest
                ? (latest.text || latest.attachment?.name || 'File attachment')
                : 'End-to-end encrypted';
        }
        document.getElementById('conversation-status').textContent =
            `End-to-end encrypted · Fingerprint: ${fingerprint}`;
        document.getElementById('conversation-status').title =
            'Compare this fingerprint with your friend through a separate trusted channel.';
        activeConversationVerified = true;
        return true;
    };

    const selectConversation = async (friendId) => {
        const friend = friends.get(String(friendId));
        if (!friend) return;
        activeConversation = String(friendId);
        activeConversationVerified = false;
        conversationList.querySelectorAll('.conversation-item').forEach((item) => {
            const selected = item.dataset.contact === activeConversation;
            item.classList.toggle('active', selected);
            item.setAttribute('aria-current', String(selected));
        });
        const initial = friend.username.trim().charAt(0).toUpperCase() || '?';
        const avatar = thread.querySelector('.conversation-header .conversation-avatar');
        avatar.className = 'conversation-avatar violet';
        avatar.textContent = initial;
        document.getElementById('conversation-name').textContent = friend.username;
        document.getElementById('conversation-status').textContent = 'Checking secure keys…';
        thread.setAttribute('aria-label', `End-to-end encrypted conversation with ${friend.username}`);
        verifyKeyButton.hidden = true;
        setComposerEnabled(false);
        messageError.hidden = true;
        list.replaceChildren();
        try {
            const verified = await loadMessages(activeConversation);
            if (verified) {
                setComposerEnabled(true);
            }
        } catch (error) {
            document.getElementById('conversation-status').textContent = 'Secure messaging unavailable';
            messageError.textContent = error.message;
            messageError.hidden = false;
        }
    };

    window.refreshMessageFriends = loadFriends;
    window.openMessageConversation = (contactId) => {
        if (!friends.has(String(contactId))) {
            loadFriends().then(() => {
                if (friends.has(String(contactId))) window.openMessageConversation(contactId);
            });
            return;
        }
        window.showDashboardTab('friends');
        window.showFriendsView('messages');
        selectConversation(String(contactId));
        document.querySelector('.messages-section-rule').scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    conversationList.addEventListener('click', (event) => {
        const button = event.target.closest('.conversation-item');
        if (button) selectConversation(button.dataset.contact);
    });

    attachmentButton.addEventListener('click', () => attachmentInput.click());

    attachmentInput.addEventListener('change', () => {
        const file = attachmentInput.files[0];
        if (!file) {
            clearStagedAttachment();
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            clearStagedAttachment();
            messageError.textContent = 'Choose a file that is 10 MB or smaller.';
            messageError.hidden = false;
            return;
        }
        messageError.hidden = true;
        attachmentName.textContent = `${file.name} · ${formatFileSize(file.size)}`;
        attachmentPreview.hidden = false;
    });

    removeAttachmentButton.addEventListener('click', () => {
        clearStagedAttachment();
        messageError.hidden = true;
    });

    list.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-attachment-id]');
        if (!button || !activeConversation) return;
        const friendId = activeConversation;
        const record = attachmentsById.get(button.dataset.attachmentId);
        if (!record) return;
        button.disabled = true;
        messageError.hidden = true;
        try {
            const response = await fetch(
                `/api/friends/${encodeURIComponent(friendId)}/attachments/${encodeURIComponent(record.attachment.id)}`,
                {
                    credentials: 'same-origin',
                    cache: 'no-store',
                    headers: { Accept: 'application/octet-stream' },
                },
            );
            if (!response.ok) {
                const errorText = await response.text();
                let message = 'Could not download the encrypted file.';
                try {
                    message = JSON.parse(errorText).message || message;
                } catch {
                    if (errorText) message = errorText;
                }
                throw new Error(message);
            }
            const encryptedBytes = await response.arrayBuffer();
            const ownIdentity = await getIdentity();
            const plaintext = await secureCrypto.decryptAttachment(
                record.attachment,
                encryptedBytes,
                record.senderId,
                record.recipientId,
                signedInUserId,
                friendId,
                ownIdentity,
            );
            const blobUrl = URL.createObjectURL(new Blob([plaintext], {
                type: 'application/octet-stream',
            }));
            const anchor = document.createElement('a');
            anchor.href = blobUrl;
            anchor.download = record.attachment.name.replace(/[\\/\u0000-\u001f]/g, '_') || 'shared-file';
            document.body.append(anchor);
            anchor.click();
            anchor.remove();
            window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
        } catch (error) {
            messageError.textContent = error.message;
            messageError.hidden = false;
        } finally {
            button.disabled = false;
        }
    });

    verifyKeyButton.addEventListener('click', async () => {
        if (!activeConversation) return;
        verifyKeyButton.disabled = true;
        try {
            const peer = await getPeerIdentity(activeConversation);
            const pinId = `${signedInUserId}:${activeConversation}`;
            await storeValue('peerPins', 'readwrite', (store) => store.put({
                id: pinId,
                publicBundle: peer.publicBundle,
                verified: true,
            }));
            peer.verified = true;
            const ready = await loadMessages(activeConversation);
            if (ready) setComposerEnabled(true);
        } catch (error) {
            messageError.textContent = error.message;
            messageError.hidden = false;
        } finally {
            verifyKeyButton.disabled = false;
        }
    });

    document.getElementById('conversation-search').addEventListener('input', (event) => {
        const query = event.target.value.trim().toLowerCase();
        conversationList.querySelectorAll('.conversation-item').forEach((item) => {
            item.hidden = !item.textContent.toLowerCase().includes(query);
        });
    });

    document.querySelector('.friend-list').addEventListener('click', (event) => {
        const friend = event.target.closest('[data-message-contact]');
        if (friend) window.openMessageConversation(friend.dataset.messageContact);
    });

    messageInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            messageForm.requestSubmit();
        }
    });

    messageForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const body = messageInput.value.trim();
        const file = attachmentInput.files[0];
        if ((!body && !file) || !activeConversation) return;
        if (body.length > 2000) return;
        const friendId = activeConversation;
        messageSendInProgress = true;
        setComposerEnabled(false);
        messageError.hidden = true;
        let uploadedAttachmentId = null;
        let messageSaved = false;
        try {
            const ownIdentity = await getIdentity();
            const peer = await getPeerIdentity(friendId);
            let attachment = null;
            if (file) {
                if (file.size > 10 * 1024 * 1024) {
                    throw new Error('Choose a file that is 10 MB or smaller.');
                }
                const encryptedFile = await secureCrypto.encryptAttachment(
                    file,
                    signedInUserId,
                    friendId,
                    ownIdentity,
                    peer,
                );
                const uploaded = await requestJson(
                    `/api/friends/${encodeURIComponent(friendId)}/attachments`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/octet-stream' },
                        body: encryptedFile.ciphertext,
                    },
                );
                uploadedAttachmentId = uploaded.attachment_id;
                attachment = { ...encryptedFile.metadata, id: uploadedAttachmentId };
            }
            const encryptedPayload = await secureCrypto.encryptMessage(
                body,
                signedInUserId,
                friendId,
                ownIdentity,
                peer,
                attachment,
            );
            await requestJson(`/api/friends/${encodeURIComponent(friendId)}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    encrypted_payload: encryptedPayload,
                    ...(uploadedAttachmentId ? { attachment_id: uploadedAttachmentId } : {}),
                }),
            });
            messageSaved = true;
            messageInput.value = '';
            clearStagedAttachment();
            await loadMessages(friendId);
        } catch (error) {
            if (uploadedAttachmentId && !messageSaved) {
                try {
                    await requestJson(
                        `/api/friends/${encodeURIComponent(friendId)}/attachments/${encodeURIComponent(uploadedAttachmentId)}`,
                        { method: 'DELETE' },
                    );
                } catch (cleanupError) {
                    if (cleanupError.status !== 404) {
                        error.message = `${error.message} The uploaded encrypted file could not be cleaned up.`;
                    }
                }
            }
            if (String(activeConversation) === String(friendId)) {
                messageError.textContent = messageSaved
                    ? `Message sent, but the conversation could not refresh: ${error.message}`
                    : error.message;
                messageError.hidden = false;
            }
        } finally {
            messageSendInProgress = false;
            setComposerEnabled(
                activeConversationVerified
                && friends.has(String(activeConversation)),
            );
        }
    });

    window.setInterval(() => {
        if (activeConversation && !document.hidden && !messageRefreshInProgress) {
            messageRefreshInProgress = true;
            loadMessages(activeConversation)
                .catch((error) => {
                    messageError.textContent = error.message;
                    messageError.hidden = false;
                })
                .finally(() => { messageRefreshInProgress = false; });
        }
    }, 8000);

    window.setInterval(() => {
        if (!document.hidden) loadFriends();
    }, 30000);

    loadFriends();
});
