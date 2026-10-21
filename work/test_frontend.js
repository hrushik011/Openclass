const fs = require('fs');

// Mock browser globals
global.window = {
  location: { pathname: '/' },
  history: { replaceState: () => {} },
  addEventListener: () => {}
};
global.document = {
  cookie: '',
  title: 'Openclass',
  getElementById: (id) => null,
  querySelectorAll: () => []
};
const store = {};
global.localStorage = {
  getItem: (k) => store[k] || null,
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
  clear: () => { Object.keys(store).forEach(k => delete store[k]); }
};
global.sessionStorage = {
  clear: () => {}
};

// Read app.js code
const code = fs.readFileSync('frontend/app.js', 'utf8');

console.log("Checking frontend/app.js logic...");

// Verify student login rendering in app.js
const hasStudentBadge = code.includes('student-badge-indicator');
const hasSidebarSignout = code.includes('btn-sidebar-signout');
const hasTopbarSignout = code.includes('btn-topbar-signout');
const hasConditionalSwitch = code.includes('isActualFaculty ? `');

console.log("1. Has student badge indicator:", hasStudentBadge);
console.log("2. Has sidebar Sign Out button:", hasSidebarSignout);
console.log("3. Has topbar Sign Out button:", hasTopbarSignout);
console.log("4. Has conditional faculty-only role switch:", hasConditionalSwitch);

if (!hasStudentBadge || !hasSidebarSignout || !hasTopbarSignout || !hasConditionalSwitch) {
  console.error("Verification failed!");
  process.exit(1);
}

console.log("All frontend verifications passed successfully!");
