// Function to apply saved preferences immediately
function applySavedPreferences() {
    const fontSize = localStorage.getItem('admin-font-size');

    localStorage.removeItem('admin-theme');

    if (fontSize) {
        document.documentElement.style.setProperty('--base-font-size', fontSize + 'px');
    }
}

// Execute immediately without waiting for DOMContentLoaded 
// to prevent the white-screen flash
applySavedPreferences();
