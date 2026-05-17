(function () {
    var KEY = 'sysdolphin-docs-theme';
    var stored = localStorage.getItem(KEY);
    if (stored === 'light') {
        document.documentElement.setAttribute('data-theme', 'light');
    }
    document.addEventListener('DOMContentLoaded', function () {
        var btn = document.querySelector('.theme-toggle');
        if (!btn) return;
        btn.addEventListener('click', function () {
            var current = document.documentElement.getAttribute('data-theme');
            if (current === 'light') {
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem(KEY, 'dark');
            } else {
                document.documentElement.setAttribute('data-theme', 'light');
                localStorage.setItem(KEY, 'light');
            }
        });
    });
})();
