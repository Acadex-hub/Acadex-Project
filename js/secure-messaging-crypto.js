(() => {
    const encoder = new TextEncoder();
    const subtle = globalThis.crypto?.subtle;

    const toBase64 = (bytes) => {
        let binary = '';
        new Uint8Array(bytes).forEach((byte) => { binary += String.fromCharCode(byte); });
        return btoa(binary);
    };

    const fromBase64 = (value) => {
        const binary = atob(value);
        return Uint8Array.from(binary, (character) => character.charCodeAt(0));
    };

    const fingerprintFor = async (publicBundle) => {
        const digest = new Uint8Array(await subtle.digest('SHA-256', encoder.encode(publicBundle)));
        const hex = [...digest].map((byte) => byte.toString(16).padStart(2, '0')).join('').toUpperCase();
        return hex.match(/.{1,4}/g).join(' ');
    };

    const createIdentity = async () => {
        if (!subtle) throw new Error('This browser does not support secure messaging.');
        const [encryptionKeys, signingKeys] = await Promise.all([
            subtle.generateKey({
                name: 'RSA-OAEP',
                modulusLength: 2048,
                publicExponent: new Uint8Array([1, 0, 1]),
                hash: 'SHA-256',
            }, false, ['encrypt', 'decrypt']),
            subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign', 'verify']),
        ]);
        return {
            publicBundle: JSON.stringify({
                v: 1,
                encryption: toBase64(await subtle.exportKey('spki', encryptionKeys.publicKey)),
                signing: toBase64(await subtle.exportKey('spki', signingKeys.publicKey)),
            }),
            encryptionPrivateKey: encryptionKeys.privateKey,
            encryptionPublicKey: encryptionKeys.publicKey,
            signingPrivateKey: signingKeys.privateKey,
            signingPublicKey: signingKeys.publicKey,
        };
    };

    const importPublicBundle = async (publicBundle) => {
        let bundle;
        try {
            bundle = JSON.parse(publicBundle);
        } catch {
            throw new Error('This friend’s encryption key is invalid.');
        }
        if (
            !bundle
            || typeof bundle !== 'object'
            || Array.isArray(bundle)
            || bundle.v !== 1
            || typeof bundle.encryption !== 'string'
            || typeof bundle.signing !== 'string'
        ) {
            throw new Error('This friend’s encryption key is invalid.');
        }
        try {
            return {
                publicBundle,
                encryptionPublicKey: await subtle.importKey(
                    'spki',
                    fromBase64(bundle.encryption),
                    { name: 'RSA-OAEP', hash: 'SHA-256' },
                    true,
                    ['encrypt'],
                ),
                signingPublicKey: await subtle.importKey(
                    'spki',
                    fromBase64(bundle.signing),
                    { name: 'ECDSA', namedCurve: 'P-256' },
                    true,
                    ['verify'],
                ),
                fingerprint: await fingerprintFor(publicBundle),
            };
        } catch {
            throw new Error('This friend’s encryption key could not be imported.');
        }
    };

    const signatureInput = (payload) => [
        payload.v,
        payload.sender_id,
        payload.recipient_id,
        payload.iv,
        payload.ciphertext,
        payload.keys[String(payload.sender_id)],
        payload.keys[String(payload.recipient_id)],
    ].join('|');

    const encryptMessage = async (body, senderId, recipientId, identity, peer, attachment = null) => {
        const aad = encoder.encode(`acadex-message-v1:${senderId}:${recipientId}`);
        const aesKey = await subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt']);
        const iv = globalThis.crypto.getRandomValues(new Uint8Array(12));
        const ciphertext = await subtle.encrypt(
            { name: 'AES-GCM', iv, additionalData: aad, tagLength: 128 },
            aesKey,
            encoder.encode(JSON.stringify({ v: 1, text: body, attachment })),
        );
        const rawAesKey = await subtle.exportKey('raw', aesKey);
        const [senderWrappedKey, recipientWrappedKey] = await Promise.all([
            subtle.encrypt({ name: 'RSA-OAEP' }, identity.encryptionPublicKey, rawAesKey),
            subtle.encrypt({ name: 'RSA-OAEP' }, peer.encryptionPublicKey, rawAesKey),
        ]);
        const payload = {
            v: 1,
            sender_id: Number(senderId),
            recipient_id: Number(recipientId),
            iv: toBase64(iv),
            ciphertext: toBase64(ciphertext),
            keys: {
                [senderId]: toBase64(senderWrappedKey),
                [recipientId]: toBase64(recipientWrappedKey),
            },
        };
        payload.signature = toBase64(await subtle.sign(
            { name: 'ECDSA', hash: 'SHA-256' },
            identity.signingPrivateKey,
            encoder.encode(signatureInput(payload)),
        ));
        return payload;
    };

    const encryptAttachment = async (file, senderId, recipientId, identity, peer) => {
        if (!file || typeof file.arrayBuffer !== 'function' || file.size > 10 * 1024 * 1024) {
            throw new Error('Choose a file that is 10 MB or smaller.');
        }
        const sender = Number(senderId);
        const recipient = Number(recipientId);
        const rawFile = await file.arrayBuffer();
        const aesKey = await subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt']);
        const iv = globalThis.crypto.getRandomValues(new Uint8Array(12));
        const aad = encoder.encode(`acadex-file-v1:${sender}:${recipient}`);
        const ciphertext = await subtle.encrypt(
            { name: 'AES-GCM', iv, additionalData: aad, tagLength: 128 },
            aesKey,
            rawFile,
        );
        const rawAesKey = await subtle.exportKey('raw', aesKey);
        const [senderWrappedKey, recipientWrappedKey, digest] = await Promise.all([
            subtle.encrypt({ name: 'RSA-OAEP' }, identity.encryptionPublicKey, rawAesKey),
            subtle.encrypt({ name: 'RSA-OAEP' }, peer.encryptionPublicKey, rawAesKey),
            subtle.digest('SHA-256', ciphertext),
        ]);
        return {
            ciphertext,
            metadata: {
                sender_id: sender,
                recipient_id: recipient,
                name: (file.name || 'shared-file').slice(0, 255),
                mime_type: (file.type || 'application/octet-stream').slice(0, 127),
                size: file.size,
                iv: toBase64(iv),
                ciphertext_sha256: toBase64(digest),
                keys: {
                    [sender]: toBase64(senderWrappedKey),
                    [recipient]: toBase64(recipientWrappedKey),
                },
            },
        };
    };

    const isValidAttachment = (attachment, senderId, recipientId) => (
        attachment
        && typeof attachment === 'object'
        && !Array.isArray(attachment)
        && /^[a-f0-9]{32}$/.test(attachment.id)
        && attachment.sender_id === senderId
        && attachment.recipient_id === recipientId
        && typeof attachment.name === 'string'
        && attachment.name.length > 0
        && attachment.name.length <= 255
        && typeof attachment.mime_type === 'string'
        && attachment.mime_type.length <= 127
        && Number.isInteger(attachment.size)
        && attachment.size >= 0
        && attachment.size <= 10 * 1024 * 1024
        && typeof attachment.iv === 'string'
        && typeof attachment.ciphertext_sha256 === 'string'
        && attachment.keys
        && typeof attachment.keys === 'object'
        && typeof attachment.keys[String(senderId)] === 'string'
        && typeof attachment.keys[String(recipientId)] === 'string'
    );

    const decryptAttachment = async (
        attachment,
        encryptedBytes,
        messageSenderId,
        messageRecipientId,
        currentUserId,
        friendId,
        identity,
    ) => {
        const senderId = Number(messageSenderId);
        const recipientId = Number(messageRecipientId);
        if (
            !isValidAttachment(attachment, senderId, recipientId)
            || ![Number(currentUserId), Number(friendId)].includes(senderId)
            || ![Number(currentUserId), Number(friendId)].includes(recipientId)
        ) {
            throw new Error('This file attachment is invalid.');
        }
        try {
            const ciphertext = encryptedBytes instanceof ArrayBuffer
                ? new Uint8Array(encryptedBytes)
                : new Uint8Array(encryptedBytes);
            if (
                ciphertext.length !== attachment.size + 16
                || toBase64(await subtle.digest('SHA-256', ciphertext)) !== attachment.ciphertext_sha256
            ) {
                throw new Error('The encrypted file failed its integrity check.');
            }
            const rawAesKey = await subtle.decrypt(
                { name: 'RSA-OAEP' },
                identity.encryptionPrivateKey,
                fromBase64(attachment.keys[String(currentUserId)]),
            );
            const aesKey = await subtle.importKey('raw', rawAesKey, 'AES-GCM', false, ['decrypt']);
            return await subtle.decrypt(
                {
                    name: 'AES-GCM',
                    iv: fromBase64(attachment.iv),
                    additionalData: encoder.encode(`acadex-file-v1:${senderId}:${recipientId}`),
                    tagLength: 128,
                },
                aesKey,
                ciphertext,
            );
        } catch (error) {
            if (error instanceof Error && error.message.startsWith('The encrypted file failed')) {
                throw error;
            }
            throw new Error('This file could not be authenticated or decrypted.');
        }
    };

    const decryptMessage = async (message, currentUserId, friendId, identity, peer) => {
        let payload;
        try {
            payload = typeof message.encrypted_payload === 'string'
                ? JSON.parse(message.encrypted_payload)
                : message.encrypted_payload;
        } catch {
            throw new Error('Message integrity check failed.');
        }
        const senderId = Number(message.sender_id);
        const recipientId = Number(message.recipient_id);
        if (
            !payload
            || payload.v !== 1
            || payload.sender_id !== senderId
            || payload.recipient_id !== recipientId
            || ![Number(currentUserId), Number(friendId)].includes(senderId)
            || ![Number(currentUserId), Number(friendId)].includes(recipientId)
        ) {
            throw new Error('Message integrity check failed.');
        }
        try {
            const senderSigningKey = senderId === Number(currentUserId)
                ? identity.signingPublicKey
                : peer.signingPublicKey;
            const signatureValid = await subtle.verify(
                { name: 'ECDSA', hash: 'SHA-256' },
                senderSigningKey,
                fromBase64(payload.signature),
                encoder.encode(signatureInput(payload)),
            );
            if (!signatureValid) throw new Error('Message signature is invalid; its contents were not displayed.');

            const rawAesKey = await subtle.decrypt(
                { name: 'RSA-OAEP' },
                identity.encryptionPrivateKey,
                fromBase64(payload.keys[String(currentUserId)]),
            );
            const aesKey = await subtle.importKey('raw', rawAesKey, 'AES-GCM', false, ['decrypt']);
            const plaintext = await subtle.decrypt(
                {
                    name: 'AES-GCM',
                    iv: fromBase64(payload.iv),
                    additionalData: encoder.encode(`acadex-message-v1:${senderId}:${recipientId}`),
                    tagLength: 128,
                },
                aesKey,
                fromBase64(payload.ciphertext),
            );
            const decoded = new TextDecoder('utf-8', { fatal: true }).decode(plaintext);
            let content;
            try {
                content = JSON.parse(decoded);
            } catch {
                return { text: decoded, attachment: null };
            }
            if (
                !content
                || typeof content !== 'object'
                || Array.isArray(content)
                || content.v !== 1
                || !Object.hasOwn(content, 'text')
                || !Object.hasOwn(content, 'attachment')
            ) {
                return { text: decoded, attachment: null };
            }
            if (
                Object.keys(content).length !== 3
                || typeof content.text !== 'string'
                || content.text.length > 2000
                || (content.attachment !== null && !isValidAttachment(
                    content.attachment,
                    senderId,
                    recipientId,
                ))
            ) {
                throw new Error('Message contents are invalid.');
            }
            return content;
        } catch (error) {
            if (error instanceof Error && error.message.startsWith('Message signature is invalid')) {
                throw error;
            }
            throw new Error('This message could not be authenticated or decrypted.');
        }
    };

    const api = {
        createIdentity,
        importPublicBundle,
        fingerprintFor,
        encryptMessage,
        decryptMessage,
        encryptAttachment,
        decryptAttachment,
    };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    } else {
        window.SecureMessagingCrypto = api;
    }
})();
