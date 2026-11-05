const assert = require('node:assert/strict');
const test = require('node:test');
const secureCrypto = require('../js/secure-messaging-crypto.js');

test('messages encrypt for both participants and authenticate the sender', async () => {
    const sender = await secureCrypto.createIdentity();
    const recipient = await secureCrypto.createIdentity();
    const senderPeer = await secureCrypto.importPublicBundle(recipient.publicBundle);
    const recipientPeer = await secureCrypto.importPublicBundle(sender.publicBundle);
    const body = 'Private study notes 🔐';
    const payload = await secureCrypto.encryptMessage(body, 17, 25, sender, senderPeer);

    assert.equal(JSON.stringify(payload).includes(body), false);
    assert.equal(
        (await secureCrypto.decryptMessage({
            sender_id: 17,
            recipient_id: 25,
            encrypted_payload: payload,
        }, 25, 17, recipient, recipientPeer)).text,
        body,
    );
    assert.equal(
        (await secureCrypto.decryptMessage({
            sender_id: 17,
            recipient_id: 25,
            encrypted_payload: payload,
        }, 17, 25, sender, senderPeer)).text,
        body,
    );
});

test('file attachments are encrypted for both participants and integrity checked', async () => {
    const sender = await secureCrypto.createIdentity();
    const recipient = await secureCrypto.createIdentity();
    const senderPeer = await secureCrypto.importPublicBundle(recipient.publicBundle);
    const recipientPeer = await secureCrypto.importPublicBundle(sender.publicBundle);
    const file = Object.assign(new Blob(['private file contents'], { type: 'text/plain' }), {
        name: 'study-notes.txt',
    });
    const encryptedFile = await secureCrypto.encryptAttachment(file, 17, 25, sender, senderPeer);
    const attachment = { ...encryptedFile.metadata, id: 'a'.repeat(32) };
    const message = await secureCrypto.encryptMessage(
        'Here are my notes',
        17,
        25,
        sender,
        senderPeer,
        attachment,
    );

    assert.equal(JSON.stringify(message).includes('study-notes.txt'), false);
    const decryptedMessage = await secureCrypto.decryptMessage({
        sender_id: 17,
        recipient_id: 25,
        encrypted_payload: message,
    }, 25, 17, recipient, recipientPeer);
    assert.equal(decryptedMessage.text, 'Here are my notes');
    assert.equal(decryptedMessage.attachment.name, 'study-notes.txt');

    const plaintext = await secureCrypto.decryptAttachment(
        decryptedMessage.attachment,
        encryptedFile.ciphertext,
        17,
        25,
        25,
        17,
        recipient,
    );
    assert.equal(new TextDecoder().decode(plaintext), 'private file contents');

    const tamperedFile = new Uint8Array(encryptedFile.ciphertext);
    tamperedFile[0] ^= 1;
    await assert.rejects(
        secureCrypto.decryptAttachment(
            decryptedMessage.attachment,
            tamperedFile,
            17,
            25,
            25,
            17,
            recipient,
        ),
        /integrity check/,
    );
});

test('modified encrypted content fails sender authentication', async () => {
    const sender = await secureCrypto.createIdentity();
    const recipient = await secureCrypto.createIdentity();
    const payload = await secureCrypto.encryptMessage(
        'Do not alter this message',
        17,
        25,
        sender,
        await secureCrypto.importPublicBundle(recipient.publicBundle),
    );
    payload.ciphertext = `${payload.ciphertext.slice(0, -4)}AAAA`;

    await assert.rejects(
        secureCrypto.decryptMessage({
            sender_id: 17,
            recipient_id: 25,
            encrypted_payload: payload,
        }, 25, 17, recipient, await secureCrypto.importPublicBundle(sender.publicBundle)),
        /signature is invalid/,
    );
});
