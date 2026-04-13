// Function to apply saved preferences immediately
function applySavedPreferences() {
    const theme = localStorage.getItem('admin-theme');
    const fontSize = localStorage.getItem('admin-font-size');

    if (theme === 'dark') {
        document.body.classList.add('dark-theme');
    }

    if (fontSize) {
        document.documentElement.style.setProperty('--base-font-size', fontSize + 'px');
    }
}

// Execute immediately without waiting for DOMContentLoaded 
// to prevent the white-screen flash
applySavedPreferences();