(() => {
    const storageKey = 'acadex-theme';
    const savedTheme = window.localStorage.getItem(storageKey);
    const defaultTheme = document.body.classList.contains('dashboard-page') ? 'light' : 'dark';
    const initialTheme = savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : defaultTheme;
    const button = document.createElement('button');

    button.className = 'theme-toggle';
    button.type = 'button';
    button.setAttribute('aria-pressed', 'false');

    const applyTheme = (theme) => {
        document.documentElement.dataset.theme = theme;
        button.textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
        button.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
        button.setAttribute('aria-pressed', String(theme === 'dark'));
    };

    applyTheme(initialTheme);
    button.addEventListener('click', () => {
        const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        window.localStorage.setItem(storageKey, nextTheme);
        applyTheme(nextTheme);
    });

    document.body.append(button);
})();