(() => {
    const navbar = document.querySelector('.navbar');
    if (!navbar) return;

    let lastScrollY = Math.max(window.scrollY, 0);
    let ticking = false;

    const updateNavbar = () => {
        const currentScrollY = Math.max(window.scrollY, 0);
        const change = currentScrollY - lastScrollY;

        if (currentScrollY <= 10) {
            navbar.classList.remove('hidden');
        } else if (change > 4) {
            navbar.classList.add('hidden');
        } else if (change < -4) {
            navbar.classList.remove('hidden');
        }

        lastScrollY = currentScrollY;
        ticking = false;
    };

    window.addEventListener('scroll', () => {
        if (ticking) return;
        ticking = true;
        window.requestAnimationFrame(updateNavbar);
    }, { passive: true });
})();
