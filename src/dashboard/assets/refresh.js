// Debug script for RoboCriptoCL Dashboard
console.log("Debug script loaded");

// Helper function to report callback firing
function logCallback(id) {
    console.log(`Callback firing for: ${id}`);
}

// Monitor interval
window.onload = function() {
    console.log("Dashboard loaded. Setting up debug listeners...");
    
    // Watch for interval events
    setInterval(function() {
        console.log("Checking for interval component...");
        const interval = document.getElementById('update-interval');
        if (interval) {
            console.log("Interval component found");
            
            // Check for status content
            const status = document.getElementById('bot-status-content');
            if (status) {
                console.log(`Status content: ${status.innerHTML.length > 0 ? 'Has content' : 'Empty'}`);
            } else {
                console.log("Status content not found");
            }
            
            // Check for performance content
            const perf = document.getElementById('performance-content');
            if (perf) {
                console.log(`Performance content: ${perf.innerHTML.length > 0 ? 'Has content' : 'Empty'}`);
            } else {
                console.log("Performance content not found");
            }
        } else {
            console.log("Interval component not found, callbacks may not fire");
        }
    }, 5000);
    
    // Report page loads
    console.log("Page loaded and ready");
};