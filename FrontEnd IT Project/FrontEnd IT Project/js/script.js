document.addEventListener('DOMContentLoaded', () => {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const authForms = document.getElementById('auth-forms');
    const authFormElements = authForms.querySelectorAll('.auth-form');
    const passwordReset = document.getElementById('password-reset');
    const requestedTab = new URLSearchParams(window.location.search).get('tab');
    const initialTab = requestedTab === 'signup' ? 'signup' : 'login';
    const loginForm = document.getElementById('loginForm');
    const signupForm = document.getElementById('signupForm');
    const loginError = document.getElementById('login-error');
    const signupError = document.getElementById('signup-error');

    const activateTab = (target) => {
        tabButtons.forEach((button) => button.classList.toggle('active', button.dataset.tab === target));
        authFormElements.forEach((form) => {
            form.classList.toggle('active', form.id === `${target}Form`);
        });
    };

    const setMessage = (element, text, isError = true) => {
        element.textContent = text;
        element.classList.toggle('success-message', !isError);
    };

    const postJson = async (url, data) => {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || 'The request could not be completed.');
        return result;
    };

    activateTab(initialTab);

    tabButtons.forEach((button) => {
        button.addEventListener('click', () => {
            passwordReset.hidden = true;
            authForms.hidden = false;
            activateTab(button.dataset.tab);
        });
    });

    loginForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        setMessage(loginError, '');
        try {
            const result = await postJson('/api/login', {
                email: document.getElementById('login-email').value,
                password: document.getElementById('login-password').value,
                admin: document.getElementById('login-admin').checked,
            });
            window.location.assign(result.role === 'admin' ? '/AdminPage.html' : '/dashboard.html');
        } catch (error) {
            setMessage(loginError, error.message);
        }
    });

    signupForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        setMessage(signupError, '');
        const password = document.getElementById('signup-password').value;
        if (password !== document.getElementById('signup-confirm').value) {
            setMessage(signupError, 'The passwords do not match.');
            return;
        }

        try {
            const result = await postJson('/api/signup', {
                full_name: document.getElementById('signup-username').value,
                email: document.getElementById('signup-email').value,
                password,
            });
            activateTab('login');
            document.getElementById('login-email').value = document.getElementById('signup-email').value.trim();
            document.getElementById('login-password').value = '';
            setMessage(loginError, result.message, false);
            signupForm.reset();
        } catch (error) {
            setMessage(signupError, error.message);
        }
    });

    const requestResetForm = document.getElementById('request-reset-form');
    const verifyResetForm = document.getElementById('verify-reset-form');
    const completeResetForm = document.getElementById('complete-reset-form');
    const resetMessage = document.getElementById('reset-message');
    let resetEmail = '';

    document.getElementById('forgot-password-button').addEventListener('click', () => {
        authForms.hidden = true;
        passwordReset.hidden = false;
        requestResetForm.hidden = false;
        verifyResetForm.hidden = true;
        completeResetForm.hidden = true;
        document.getElementById('reset-email').value = document.getElementById('login-email').value;
        setMessage(resetMessage, '');
    });

    document.getElementById('back-to-login').addEventListener('click', () => {
        passwordReset.hidden = true;
        authForms.hidden = false;
        activateTab('login');
    });

    requestResetForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        resetEmail = document.getElementById('reset-email').value.trim().toLowerCase();
        setMessage(resetMessage, '');
        try {
            const result = await postJson('/api/forgot-password', { email: resetEmail });
            requestResetForm.hidden = true;
            verifyResetForm.hidden = false;
            setMessage(resetMessage, result.message + ' Enter the code if you receive it.', false);
            document.getElementById('reset-otp').focus();
        } catch (error) {
            setMessage(resetMessage, error.message);
        }
    });

    verifyResetForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        setMessage(resetMessage, '');
        try {
            const result = await postJson('/api/verify-reset-otp', {
                email: resetEmail,
                otp: document.getElementById('reset-otp').value,
            });
            verifyResetForm.hidden = true;
            completeResetForm.hidden = false;
            setMessage(resetMessage, result.message, false);
            document.getElementById('reset-password').focus();
        } catch (error) {
            setMessage(resetMessage, error.message);
        }
    });

    completeResetForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        setMessage(resetMessage, '');
        const password = document.getElementById('reset-password').value;
        if (password !== document.getElementById('reset-confirm').value) {
            setMessage(resetMessage, 'The passwords do not match.');
            return;
        }

        try {
            const result = await postJson('/api/reset-password', {
                email: resetEmail,
                password,
            });
            passwordReset.hidden = true;
            authForms.hidden = false;
            activateTab('login');
            document.getElementById('login-email').value = resetEmail;
            document.getElementById('login-password').value = '';
            setMessage(loginError, result.message, false);
            completeResetForm.reset();
        } catch (error) {
            setMessage(resetMessage, error.message);
        }
    });
});
