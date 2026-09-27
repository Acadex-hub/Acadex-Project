document.addEventListener('DOMContentLoaded', () => {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const forms = document.querySelectorAll('.auth-form');

    tabButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const target = button.dataset.tab;

            tabButtons.forEach((btn) => btn.classList.toggle('active', btn === button));
            forms.forEach((form) => {
                form.classList.toggle('active', form.id === `${target}Form`);
            });
        });
    });

    const loginForm = document.getElementById('loginForm');
    const signupForm = document.getElementById('signupForm');

    if (loginForm) {
        loginForm.addEventListener('submit', (event) => {
            event.preventDefault();
            const error = document.getElementById('login-error');
            if (error) {
                error.textContent = 'Demo mode: login submitted successfully.';
            }
        });
    }

    if (signupForm) {
        signupForm.addEventListener('submit', (event) => {
            event.preventDefault();
            const error = document.getElementById('signup-error');
            if (error) {
                error.textContent = 'Demo mode: account created successfully.';
            }
        });
    }
});
