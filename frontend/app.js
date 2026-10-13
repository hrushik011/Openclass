/**
 * OpenClass — Interactive Backend-to-Frontend Binding
 * Single-Page Reactive Client with Live API Integration
 */

(function () {
  "use strict";

  // --- State Architecture ---
  const state = {
    token: localStorage.getItem("openclass_token") || null,
    user: JSON.parse(localStorage.getItem("openclass_user") || "null"),
    currentTab: "Dashboard",
    role: "student", // "faculty" | "student"
    classes: [],
    assignments: [],
    batches: [],
    people: [],
    submissions: [],
    activeModal: null, // "assignment_create" | "assignment_edit" | "assignment_submit" | "submissions_view" | "sudden_class" | "upload_timetable" | "manage_batches" | "thread"
    modalData: null,
    toast: null,
    toastTimer: null,
    loading: false,
    loginTab: "STUDENT", // "STUDENT" | "FACULTY"
    loginEmail: "",
    loginPassword: "",
    loginError: "",
    filterSearch: "",
    notificationOpen: false,
    threads: [
      { title: "What is the intuition behind Dijkstra?", by: "Arjun Rao", count: 8 },
      { title: "Office hours before Assignment 3", by: "Meera Shah", count: 4 },
      { title: "Cycle detection using Disjoint Set Union", by: "Karan Verma", count: 3 }
    ]
  };

  if (state.user && state.user.role) {
    const roleUpper = state.user.role.toUpperCase();
    state.role = roleUpper === "FACULTY" ? "faculty" : "student";
  }

  // --- Microsoft OIDC JWT Handoff ---
  // After a real Azure AD callback, the backend sets a 30-second cookie `ms_jwt_handoff`.
  // We read it here, store it as our auth token, then delete the cookie.
  (function handleMsHandoff() {
    const cookieVal = document.cookie
      .split(";")
      .map((c) => c.trim())
      .find((c) => c.startsWith("ms_jwt_handoff="));

    if (cookieVal) {
      const token = cookieVal.split("=").slice(1).join("=");
      if (token) {
        // Decode JWT payload to get user info (no crypto verification needed — backend already signed it)
        try {
          const parts = token.split(".");
          const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
          state.token = token;
          state.user = {
            id: payload.user_id,
            email: payload.email,
            name: payload.name,
            role: payload.role,
            batch_id: payload.batch_id || null,
          };
          const roleUpper = (payload.role || "STUDENT").toUpperCase();
          state.role = roleUpper === "FACULTY" ? "faculty" : "student";
          localStorage.setItem("openclass_token", token);
          localStorage.setItem("openclass_user", JSON.stringify(state.user));
        } catch (e) {
          console.error("MS JWT handoff decode error", e);
        }
      }
      // Expire the handoff cookie immediately
      document.cookie = "ms_jwt_handoff=;expires=" + new Date(0).toUTCString() + ";path=/";
    }

    // Read ms_error from URL query params (set by backend on OAuth failure)
    const urlParams = new URLSearchParams(window.location.search);
    const msError = urlParams.get("ms_error");
    if (msError && !state.token) {
      state.loginError = "Microsoft SSO failed: " + decodeURIComponent(msError);
      // Clean the URL
      window.history.replaceState({}, document.title, window.location.pathname);
    }
    // Clean ms_sso=1 from URL if login succeeded
    if (urlParams.get("ms_sso") && state.token) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  })();

  // --- SVG Icons ---
  function getIcon(name, size = 16, className = "") {
    const s = size;
    const icons = {
      dashboard: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>`,
      calendar: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`,
      assignment: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect><path d="M9 14l2 2 4-4"></path></svg>`,
      threads: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`,
      hub: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`,
      people: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>`,
      video: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>`,
      search: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>`,
      bell: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>`,
      plus: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>`,
      close: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`,
      check: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
      upload: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>`,
      edit: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>`,
      trash: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>`,
      clock: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`,
      sparkles: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"></path></svg>`,
      logout: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>`,
      arrowRight: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>`,
      download: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`,
      shield: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>`,
      fileText: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`
    };
    return icons[name] || "";
  }

  // --- API Client Layer ---
  const api = {
    headers() {
      const h = { "Content-Type": "application/json" };
      if (state.token) {
        h["Authorization"] = `Bearer ${state.token}`;
      }
      return h;
    },

    async login(email, password, role) {
      state.loading = true;
      state.loginError = "";
      render();
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, role })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "Authentication failed");
        }
        state.token = data.access_token;
        state.user = data.user;
        state.role = data.user.role.toLowerCase();
        localStorage.setItem("openclass_token", state.token);
        localStorage.setItem("openclass_user", JSON.stringify(state.user));
        showToast(`Welcome back, ${state.user.name}! (${state.user.role})`);
        await api.loadDashboardData();
      } catch (err) {
        state.loginError = err.message;
      } finally {
        state.loading = false;
        render();
      }
    },

    async microsoftSso(role) {
      // Check if real Azure AD credentials are configured on the backend
      state.loading = true;
      state.loginError = "";
      render();
      try {
        const statusRes = await fetch("/api/auth/ms-status");
        const statusData = await statusRes.json();

        if (statusData.configured) {
          // Real Azure AD OIDC — redirect browser to backend start URL
          showToast("Redirecting to Microsoft login…");
          window.location.href = `/auth/microsoft/start?role=${encodeURIComponent(role)}`;
          return; // page will redirect
        }

        // --- Demo fallback: provision with known test account ---
        const isFaculty = role === "FACULTY";
        const email = isFaculty ? "priya.menon@college.edu" : "arjun.rao@college.edu";
        const name = isFaculty ? "Priya Menon" : "Arjun Rao";
        const batch_id = isFaculty ? null : "CS-2A";

        const res = await fetch("/api/auth/microsoft", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, name, role, batch_id })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "Microsoft SSO authentication failed");
        }
        state.token = data.access_token;
        state.user = data.user;
        state.role = data.user.role.toLowerCase() === "faculty" ? "faculty" : "student";
        localStorage.setItem("openclass_token", state.token);
        localStorage.setItem("openclass_user", JSON.stringify(state.user));
        showToast(`Demo MS 365 identity: ${state.user.email} (Azure AD not configured yet)`);
        await api.loadDashboardData();
      } catch (err) {
        state.loginError = err.message;
      } finally {
        state.loading = false;
        render();
      }
    },

    logout() {
      state.token = null;
      state.user = null;
      state.classes = [];
      state.assignments = [];
      state.batches = [];
      state.people = [];
      state.submissions = [];
      state.activeModal = null;
      state.modalData = null;
      state.loginError = "";
      state.filterSearch = "";
      state.notificationOpen = false;

      // Clear all local and session storage
      try {
        localStorage.removeItem("openclass_token");
        localStorage.removeItem("openclass_user");
        localStorage.clear();
        sessionStorage.clear();
      } catch (e) {
        console.error("Storage clear error", e);
      }

      // Expire session cookies
      try {
        document.cookie.split(";").forEach((c) => {
          document.cookie = c
            .replace(/^ +/, "")
            .replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/");
        });
      } catch {}

      // Reset URL to clean base path
      try {
        window.history.replaceState({}, document.title, window.location.pathname);
      } catch {}

      showToast("Signed out successfully from OpenClass.");
      render();
    },

    async loadDashboardData() {
      if (!state.token) return;
      try {
        const [clsRes, assignRes, batchRes, peopleRes] = await Promise.all([
          fetch("/api/classes", { headers: api.headers() }),
          fetch("/api/assignments", { headers: api.headers() }),
          fetch("/api/batches", { headers: api.headers() }),
          fetch("/api/people", { headers: api.headers() })
        ]);
        if (clsRes.ok) state.classes = await clsRes.json();
        if (assignRes.ok) state.assignments = await assignRes.json();
        if (batchRes.ok) state.batches = await batchRes.json();
        if (peopleRes.ok) state.people = await peopleRes.json();
      } catch (e) {
        console.error("Data fetch error", e);
      }
    },

    async createAssignment(payload) {
      state.loading = true;
      render();
      try {
        const res = await fetch("/api/assignments", {
          method: "POST",
          headers: api.headers(),
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to create assignment");
        showToast(`Assignment "${data.title}" posted · Email blast dispatched to ${data.batch_id}!`);
        state.activeModal = null;
        await api.loadDashboardData();
      } catch (e) {
        showToast(`Error: ${e.message}`);
      } finally {
        state.loading = false;
        render();
      }
    },

    async updateAssignment(id, payload) {
      state.loading = true;
      render();
      try {
        const res = await fetch(`/api/assignments/${id}`, {
          method: "PUT",
          headers: api.headers(),
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to update assignment");
        showToast(`Assignment portal updated · Deadline extended!`);
        state.activeModal = null;
        await api.loadDashboardData();
      } catch (e) {
        showToast(`Error: ${e.message}`);
      } finally {
        state.loading = false;
        render();
      }
    },

    async deleteAssignment(id) {
      if (!confirm("Are you sure you want to delete this assignment portal?")) return;
      try {
        const res = await fetch(`/api/assignments/${id}`, {
          method: "DELETE",
          headers: api.headers()
        });
        if (!res.ok) throw new Error("Delete failed");
        showToast("Assignment portal removed.");
        await api.loadDashboardData();
        render();
      } catch (e) {
        showToast(`Error: ${e.message}`);
      }
    },

    async submitAssignment(assignmentId, file) {
      state.loading = true;
      render();
      try {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("student_id", String(state.user.id));

        const res = await fetch(`/api/assignments/${assignmentId}/submit`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${state.token}`
          },
          body: formData
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Submission upload failed");
        showToast(`Submission uploaded successfully: ${file.name}`);
        state.activeModal = null;
        await api.loadDashboardData();
      } catch (e) {
        showToast(`Error: ${e.message}`);
      } finally {
        state.loading = false;
        render();
      }
    },

    async viewSubmissions(assignmentId) {
      try {
        const res = await fetch(`/api/assignments/${assignmentId}/submissions`, {
          headers: api.headers()
        });
        if (!res.ok) throw new Error("Could not load submissions");
        state.submissions = await res.json();
        state.activeModal = "submissions_view";
        render();
      } catch (e) {
        showToast(`Error: ${e.message}`);
      }
    },

    async scheduleSuddenClass(payload) {
      state.loading = true;
      render();
      try {
        const res = await fetch("/api/classes/sudden", {
          method: "POST",
          headers: api.headers(),
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Scheduling failed");
        showToast(`Sudden lecture scheduled · Google Meet space active · Enrolled batch notified!`);
        state.activeModal = null;
        await api.loadDashboardData();
      } catch (e) {
        showToast(`Error: ${e.message}`);
      } finally {
        state.loading = false;
        render();
      }
    },

    async uploadTimetable(file) {
      state.loading = true;
      render();
      try {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("schedule_type", "weekly");
        const res = await fetch("/api/timetables/upload", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${state.token}`
          },
          body: formData
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Upload failed");
        showToast(`Timetable processed: ${data.classes_detected} sessions mapped with Google Meet!`);
        state.activeModal = null;
        await api.loadDashboardData();
      } catch (e) {
        showToast(`Error: ${e.message}`);
      } finally {
        state.loading = false;
        render();
      }
    },

    async triggerReminders() {
      state.loading = true;
      render();
      try {
        const res = await fetch("/api/reminders/trigger", {
          method: "POST",
          headers: api.headers()
        });
        const data = await res.json();
        showToast(`Deadline reminders dispatched to pending batch students! (${data.reminders_dispatched} sent)`);
      } catch (e) {
        showToast(`Reminder trigger failed: ${e.message}`);
      } finally {
        state.loading = false;
        render();
      }
    },

    async launchMeet(sessionId) {
      try {
        const res = await fetch(`/api/classes/${sessionId}/meet-link`, {
          headers: api.headers()
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Could not retrieve Meet link");
        window.open(data.launch_url, "_blank");
        showToast(`Launching Google Meet (${data.role_badge}) · ${data.controls_notice}`);
      } catch (e) {
        showToast(`Meet Error: ${e.message}`);
      }
    }
  };

  function showToast(msg) {
    if (state.toastTimer) clearTimeout(state.toastTimer);
    state.toast = msg;
    render();
    state.toastTimer = setTimeout(() => {
      state.toast = null;
      render();
    }, 3800);
  }

  // --- Date Formatting Helpers ---
  function formatDeadline(isoString) {
    if (!isoString) return "No deadline set";
    try {
      const dt = new Date(isoString);
      return dt.toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      });
    } catch {
      return isoString;
    }
  }

  // --- Render System ---
  function render() {
    const root = document.getElementById("app");
    if (!root) return;

    if (!state.token || !state.user) {
      root.innerHTML = renderLogin();
      bindLoginEvents();
      return;
    }

    root.innerHTML = renderWorkspace();
    bindWorkspaceEvents();
  }

  // --- 1. IMDR-Styled Institutional Login Component ---
  function renderLogin() {
    const isStudent = state.loginTab === "STUDENT";
    return `
      <div class="login-screen">
        <div class="login-card">
          <div class="login-brand">
            <div class="brand-mark" aria-hidden="true"><span></span></div>
            <div>
              <div class="login-title">Openclass</div>
              <div style="font-size: 8px; font-family: var(--app-font-mono); color: #a78bfa; letter-spacing: 0.12em;">IMDR ACADEMIC CLOUD</div>
            </div>
          </div>

          <p class="login-sub">
            A unified cognitive workspace connecting timetables, interactive Google Meet sessions, and assignment lifecycle.
          </p>

          <!-- Primary SSO Buttons -->
          <button class="sso-btn sso-google" id="btn-sso-google">
            <svg width="16" height="16" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>
            Continue with Institutional SSO (Google)
          </button>

          <button class="sso-btn sso-ms" id="btn-sso-ms">
            <svg width="16" height="16" viewBox="0 0 24 24"><rect x="1" y="1" width="10" height="10" fill="#F25022"/><rect x="13" y="1" width="10" height="10" fill="#7FBA00"/><rect x="1" y="13" width="10" height="10" fill="#00A4EF"/><rect x="13" y="13" width="10" height="10" fill="#FFB900"/></svg>
            Sign in with Microsoft 365 / Outlook
          </button>

          <div class="login-divider">or direct credentials</div>

          <!-- Explicit Tabs for Student and Faculty -->
          <div class="role-tabs">
            <button class="role-tab-btn ${isStudent ? 'active' : ''}" id="tab-student">
              🎓 Student Portal
            </button>
            <button class="role-tab-btn ${!isStudent ? 'active' : ''}" id="tab-faculty">
              🏛️ Faculty Portal
            </button>
          </div>

          <!-- Password Form -->
          <form id="form-login">
            <label class="field-label" for="login-email">College / Institutional Email</label>
            <input
              id="login-email"
              type="email"
              class="field-input"
              required
              placeholder="${isStudent ? 'arjun.rao@college.edu' : 'priya.menon@college.edu'}"
              value="${state.loginEmail}"
            />

            <label class="field-label" for="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              class="field-input"
              required
              placeholder="Enter institutional password"
              value="${state.loginPassword || 'password123'}"
            />

            ${state.loginError ? `
              <div style="background: rgba(255, 107, 107, 0.15); border: 1px solid #ff6b6b55; border-radius: 8px; padding: 10px 12px; margin-bottom: 14px; font-size: 10px; color: #ff8b7b; display: flex; align-items: center; gap: 8px;">
                ${getIcon("close", 14)}
                <span>${state.loginError}</span>
              </div>
            ` : ""}

            <button type="submit" class="primary-btn" style="width: 100%; padding: 12px; margin-top: 4px;" ${state.loading ? "disabled" : ""}>
              ${state.loading ? `<span class="spinner"></span>` : (isStudent ? `Sign in as Student` : `Sign in as Faculty`)}
            </button>
          </form>

          <!-- Quick Test Accounts -->
          <div class="demo-accounts">
            <div class="demo-title">⚡ Instant Testing Shortcuts</div>
            <div class="demo-chips">
              <button class="demo-chip" data-email="priya.menon@college.edu" data-role="FACULTY">Faculty (Priya Menon)</button>
              <button class="demo-chip" data-email="arjun.rao@college.edu" data-role="STUDENT">Student (Arjun Rao · CS-2A)</button>
              <button class="demo-chip" data-email="meera.shah@college.edu" data-role="STUDENT">Student (Meera Shah · CS-2A)</button>
              <button class="demo-chip" data-email="rohan.varma@college.edu" data-role="STUDENT">Student (Rohan · CS-1B)</button>
            </div>
          </div>
        </div>
      </div>
      ${renderToast()}
    `;
  }

  function bindLoginEvents() {
    const tabStudent = document.getElementById("tab-student");
    const tabFaculty = document.getElementById("tab-faculty");
    const emailInput = document.getElementById("login-email");
    const passwordInput = document.getElementById("login-password");
    const form = document.getElementById("form-login");

    if (tabStudent) {
      tabStudent.addEventListener("click", () => {
        state.loginTab = "STUDENT";
        state.loginEmail = "arjun.rao@college.edu";
        state.loginPassword = "password123";
        state.loginError = "";
        render();
      });
    }

    if (tabFaculty) {
      tabFaculty.addEventListener("click", () => {
        state.loginTab = "FACULTY";
        state.loginEmail = "priya.menon@college.edu";
        state.loginPassword = "password123";
        state.loginError = "";
        render();
      });
    }

    if (form) {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const email = emailInput.value.trim();
        const password = passwordInput.value;
        api.login(email, password, state.loginTab);
      });
    }

    // SSO buttons
    const btnGoogle = document.getElementById("btn-sso-google");
    if (btnGoogle) {
      btnGoogle.addEventListener("click", () => {
        const isFaculty = state.loginTab === "FACULTY";
        const email = isFaculty ? "priya.menon@college.edu" : "arjun.rao@college.edu";
        api.login(email, "password123", state.loginTab);
      });
    }

    const btnMs = document.getElementById("btn-sso-ms");
    if (btnMs) {
      btnMs.addEventListener("click", () => {
        api.microsoftSso(state.loginTab);
      });
    }

    // Demo chips
    document.querySelectorAll(".demo-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const email = chip.dataset.email;
        const role = chip.dataset.role;
        state.loginTab = role;
        state.loginEmail = email;
        state.loginPassword = "password123";
        api.login(email, "password123", role);
      });
    });
  }

  // --- 2. Main Workspace Layout ---
  function renderWorkspace() {
    const user = state.user || {};
    const userRole = (user.role || "STUDENT").toUpperCase();
    const isActualFaculty = userRole === "FACULTY";

    // Strictly enforce student role if logged-in account is a student
    if (!isActualFaculty) {
      state.role = "student";
    }

    const isFaculty = state.role === "faculty";
    const initials = (user.name || "User").split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase();

    const navItems = isFaculty
      ? [
          { label: "Dashboard", icon: "dashboard" },
          { label: "Timetable & Attendance", icon: "calendar" },
          { label: "Assignments & Sessions", icon: "assignment" },
          { label: "Class Threads", icon: "threads" },
          { label: "People", icon: "people" }
        ]
      : [
          { label: "Dashboard", icon: "dashboard" },
          { label: "My Timetable", icon: "calendar" },
          { label: "Assignments", icon: "assignment" },
          { label: "Class Threads", icon: "threads" },
          { label: "Knowledge Hub", icon: "hub" },
          { label: "People", icon: "people" }
        ];

    // Ensure valid currentTab for role
    const validTabs = navItems.map((n) => n.label);
    if (!validTabs.includes(state.currentTab) && state.currentTab !== "Workspace Settings") {
      state.currentTab = "Dashboard";
    }

    return `
      <div class="shell">
        <!-- Sidebar -->
        <aside class="sidebar">
          <div class="brand">
            <div class="brand-mark" aria-hidden="true"><span></span></div>
            <span class="brand-name">Openclass</span>
            <span class="brand-beta">BETA</span>
          </div>

          <div class="nav-label">Workspace</div>
          <nav class="nav-list" aria-label="workspace navigation">
            ${navItems
              .map(
                (item) => `
              <button class="nav-item ${state.currentTab === item.label ? "active" : ""}" data-tab="${item.label}">
                ${getIcon(item.icon, 16)}
                <span>${item.label}</span>
              </button>
            `
              )
              .join("")}
          </nav>

          <div style="margin-top: 26px;" class="nav-label">System</div>
          <button class="nav-item ${state.currentTab === "Workspace Settings" ? "active" : ""}" data-tab="Workspace Settings">
            ${getIcon("sparkles", 16)}
            <span>Workspace Settings</span>
          </button>

          <!-- Sidebar Footer with User Profile & Prominent Sign Out Button -->
          <div class="sidebar-footer">
            <div class="profile">
              <div class="avatar">${initials}</div>
              <div class="profile-copy">
                <div class="profile-name">${user.name || "Member"}</div>
                <div class="profile-role">${isActualFaculty ? "Course Coordinator" : `Student · ${user.batch_id || "CS-2A"}`}</div>
              </div>
            </div>
            <button class="sidebar-signout-btn" id="btn-sidebar-signout" title="Sign out of OpenClass">
              ${getIcon("logout", 14)}
              <span>Sign Out</span>
            </button>
          </div>
        </aside>

        <!-- Main Body -->
        <main class="main">
          <!-- Topbar -->
          <header class="topbar">
            <div style="display: flex; align-items: center; gap: 12px;">
              <div class="breadcrumb">
                <span>Workspace</span>
                <span style="opacity: 0.4;">/</span>
                <strong>${state.currentTab}</strong>
              </div>
            </div>

            <div class="top-actions">
              ${isActualFaculty ? `
                <!-- Role Switcher (Visible ONLY for Faculty accounts) -->
                <div class="role-switch" aria-label="Choose portal view">
                  <button class="${state.role === "faculty" ? "active" : ""}" id="switch-faculty">Faculty portal</button>
                  <button class="${state.role === "student" ? "active" : ""}" id="switch-student">Student view</button>
                </div>
              ` : `
                <!-- Student Workspace Indicator: Hardcoded portal switcher completely removed -->
                <div class="student-badge-indicator">
                  <span class="live-dot" style="background: #61d7da;"></span>
                  <span>Student Workspace · ${user.batch_id || "CS-2A"}</span>
                </div>
              `}

              <!-- Search -->
              <div class="command-search">
                ${getIcon("search", 13)}
                <input
                  type="text"
                  id="knowledge-search"
                  placeholder="${isFaculty ? "Search classes & rosters" : "Search your knowledge"}"
                  value="${state.filterSearch}"
                  style="background: transparent; border: 0; color: #fff; font-size: 11px; outline: none; width: 140px;"
                />
              </div>

              <!-- Notification Bell -->
              <button class="icon-btn" id="btn-notifications" aria-label="Notifications">
                ${getIcon("bell", 15)}
              </button>

              <div class="avatar" title="${user.name} (${user.role})">${initials}</div>

              <!-- Clean Topbar Sign Out Button -->
              <button class="topbar-signout-btn" id="btn-topbar-signout" title="Sign out of OpenClass">
                ${getIcon("logout", 13)}
                <span>Sign Out</span>
              </button>
            </div>
          </header>

          <!-- Notification Popover -->
          ${state.notificationOpen ? `
            <div class="notification-pop">
              <strong>Workspace Pulse</strong>
              <p>Professor Iyer scheduled an extra review lecture with Google Meet host controls active.</p>
              <p style="margin-top: 6px; font-size: 9px; color: #8e87a2;">All reminders synced with classroomflow database.</p>
            </div>
          ` : ""}

          <!-- Dynamic Content -->
          <div class="content">
            ${renderTabContent()}
          </div>
        </main>

        <!-- Floating Action Button -->
        <button class="primary-btn" id="btn-floating-action" style="position: fixed; right: 28px; bottom: 25px; z-index: 25;">
          ${isActualFaculty ? getIcon("video", 14) : getIcon("plus", 14)}
          ${isActualFaculty ? "Schedule sudden class" : "Start new thread"}
        </button>
      </div>

      <!-- Active Modal -->
      ${renderActiveModal()}

      <!-- Success / Alert Toast -->
      ${renderToast()}
    `;
  }

  function renderTabContent() {
    const userRole = (state.user && state.user.role ? state.user.role : "STUDENT").toUpperCase();
    const isActualFaculty = userRole === "FACULTY";

    if (!isActualFaculty) {
      state.role = "student";
    }

    switch (state.currentTab) {
      case "Dashboard":
        return isActualFaculty && state.role === "faculty"
          ? renderFacultyDashboard()
          : renderStudentDashboard();
      case "Assignments":
      case "Assignments & Sessions":
        return renderAssignmentsView();
      case "My Timetable":
      case "Timetable & Attendance":
        return renderTimetableView();
      case "People":
        return renderPeopleView();
      case "Class Threads":
        return renderThreadsView();
      default:
        return isActualFaculty && state.role === "faculty"
          ? renderFacultyDashboard()
          : renderStudentDashboard();
    }
  }

  // --- 3. Faculty Dashboard ---
  function renderFacultyDashboard() {
    const user = state.user || {};
    const todayClasses = state.classes.slice(0, 3);
    const activeAssignments = state.assignments.slice(0, 4);

    return `
      <div class="faculty-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">Faculty Portal · Live Academic Control</div>
            <h1 class="hero-title">Coordinate the whole class, <span class="accent">${user.name || "Faculty"}.</span></h1>
            <p class="hero-copy">Manage rosters, real-time Google Meet spaces with strict host controls, assignment deadlines, and batch notifications.</p>
          </div>
          <div class="date-note">
            Coordinator mode <b>active</b>
          </div>
        </div>

        <div class="faculty-grid">
          <!-- Timetable & Ingestion Card -->
          <section class="panel management-card">
            <div class="panel-head">
              <div class="panel-title">${getIcon("calendar", 15)} Timetable & Ingestion</div>
              <span class="panel-meta">CS-2A · 42 learners</span>
            </div>
            <div class="management-body">
              <div class="roster-upload">
                <div class="management-icon">${getIcon("upload", 20)}</div>
                <div class="management-copy">
                  <strong>Ingest university roster (.xlsx)</strong>
                  <span>Drop an .xlsx timetable to automatically map lectures, rooms, and Google Meet spaces.</span>
                </div>
                <button class="secondary-btn" id="btn-open-upload-modal">Upload roster</button>
              </div>

              <div class="faculty-stats">
                <div class="faculty-stat">
                  <span>Lectures mapped</span>
                  <strong>${String(state.classes.length).padStart(2, "0")}</strong>
                  <button class="text-action" id="btn-open-sudden-class">+ Schedule lecture</button>
                </div>
                <div class="faculty-stat">
                  <span>Attendance today</span>
                  <strong>38 <small>/ 42</small></strong>
                  <button class="text-action" id="btn-trigger-reminders">⚡ Batch Reminders</button>
                </div>
              </div>
            </div>
          </section>

          <!-- Assignment & Session Control Card -->
          <section class="panel management-card">
            <div class="panel-head">
              <div class="panel-title">${getIcon("assignment", 15)} Assignment & Session Control</div>
              <span class="panel-meta">${state.assignments.length} active portals</span>
            </div>
            <div class="management-body">
              ${activeAssignments.length > 0 ? activeAssignments.map((a) => `
                <div class="assignment-row">
                  <div class="assignment-mark">${getIcon("assignment", 15)}</div>
                  <div class="management-copy">
                    <strong>${a.title}</strong>
                    <span>Deadline · ${formatDeadline(a.deadline)} · ${a.batch_id}</span>
                  </div>
                  <span class="status-pill">${a.submission_count || 0} / ${a.total_students || 42}</span>
                </div>
              `).join("") : `<p style="font-size: 11px; color: #8e87a2;">No assignment portals created yet.</p>`}

              <div class="control-actions">
                <button class="quick-action compact-action" id="btn-quick-new-assignment">
                  ${getIcon("plus", 14)}
                  <div>
                    <strong>Upload assignment portal</strong>
                    <span>Set deadline, batch, and auto-dispatch email alert.</span>
                  </div>
                </button>
                <button class="quick-action compact-action" id="btn-quick-sudden-class">
                  ${getIcon("video", 14)}
                  <div>
                    <strong>Schedule sudden class</strong>
                    <span>Instant Google Meet host link + email in one step.</span>
                  </div>
                </button>
              </div>
            </div>
          </section>
        </div>

        <!-- Batch Attendance Overview -->
        <section class="panel faculty-overview" style="margin-top: 18px;">
          <div class="panel-head">
            <div class="panel-title">${getIcon("people", 15)} Batch Attendance & Roster Overview</div>
            <button class="muted-btn" id="btn-manage-batches">Manage batches ${getIcon("arrowRight", 12)}</button>
          </div>
          <div class="batch-grid">
            <div class="batch-card">
              <div>
                <span class="batch-kicker">CS-2A · Data Structures</span>
                <strong>38 / 42 present</strong>
                <small>90% attendance today</small>
              </div>
              <div class="progress-ring"><span>90%</span></div>
            </div>
            <div class="batch-card">
              <div>
                <span class="batch-kicker">CS-1B · Algorithms</span>
                <strong>33 / 36 present</strong>
                <small>92% attendance today</small>
              </div>
              <div class="progress-ring teal"><span>92%</span></div>
            </div>
            <div class="faculty-note">
              ${getIcon("sparkles", 15)}
              <div>
                <strong>Strict Host Controls Active</strong>
                <span>Generated Google Meet links assign faculty as sole host; student privileges to mute others or kick participants are locked.</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    `;
  }

  // --- 4. Student Dashboard ---
  function renderStudentDashboard() {
    const user = state.user || {};
    const upNext = state.classes[0] || {
      id: 1,
      subject: "Data Structures CS-2A",
      start_time: "10:00",
      faculty_name: "Professor Iyer",
      google_meet_url: "https://meet.google.com/dks-pqnr-kty"
    };

    return `
      <div class="student-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">Student Portal · Batch ${user.batch_id || "CS-2A"}</div>
            <h1 class="hero-title">Good morning, <span class="accent">${user.name || "Student"}.</span></h1>
            <p class="hero-copy">Your personalized learning space, arranged around lectures, submissions, and class notes.</p>
          </div>
          <div class="date-note">
            Synced via <b>Microsoft 365 OIDC</b>
          </div>
        </div>

        <div class="dashboard-grid">
          <!-- Up Next Class Card (with Strict Host Google Meet Integration) -->
          <div class="class-card panel">
            <div class="class-overline"><span class="live-dot"></span> Up next · Today</div>
            <div class="class-title">${upNext.subject}</div>
            <div class="class-sub">Faculty: ${upNext.faculty_name || "Course Lead"} · Starts at ${upNext.start_time || "10:00"}</div>
            <div class="class-right">
              <div class="count-label">starts at</div>
              <div class="count">${upNext.start_time || "10:00"}</div>
              <button class="meet-btn" data-action="launch-meet" data-id="${upNext.id}">
                ${getIcon("video", 14)} Join Google Meet as Student
              </button>
              <div class="restricted-badge-chip">
                ${getIcon("shield", 10)} Restricted Participant Mode · Host controls enforced
              </div>
            </div>
          </div>

          <!-- Knowledge Graph Card -->
          <section class="panel graph-panel">
            <div class="panel-head">
              <div class="panel-title">${getIcon("hub", 15)} Knowledge Graph</div>
              <button class="muted-btn">Explore ${getIcon("arrowRight", 12)}</button>
            </div>
            <div class="graph-wrap">
              <svg class="graph-lines" viewBox="0 0 600 330" preserveAspectRatio="none" aria-hidden="true">
                <line x1="300" y1="168" x2="312" y2="42" stroke="rgba(147,133,204,0.3)" stroke-width="1.5"></line>
                <line x1="300" y1="168" x2="97" y2="168" stroke="rgba(147,133,204,0.3)" stroke-width="1.5"></line>
                <line x1="300" y1="168" x2="504" y2="168" stroke="rgba(147,133,204,0.3)" stroke-width="1.5"></line>
                <line x1="300" y1="168" x2="300" y2="286" stroke="rgba(147,133,204,0.3)" stroke-width="1.5"></line>
                <circle cx="300" cy="168" r="4" fill="#a78bfa"></circle>
              </svg>
              <div class="graph-node central n-center">
                <div class="node-kicker">Current class</div>
                <span class="node-name">Data Structures CS-2A</span>
              </div>
              <div class="graph-node n-top">
                <div class="node-kicker">Document</div>
                <span class="node-name">Lecture Notes</span>
              </div>
              <div class="graph-node n-left">
                <div class="node-kicker">Assignment</div>
                <span class="node-name">Graph Traversal</span>
              </div>
              <div class="graph-node n-right">
                <div class="node-kicker">Updates</div>
                <span class="node-name">Announcements</span>
              </div>
            </div>
          </section>

          <!-- Today's Rhythm -->
          <div class="side-stack">
            <section class="panel schedule-panel">
              <div class="panel-head">
                <div class="panel-title">${getIcon("calendar", 15)} Today’s Rhythm</div>
                <span class="panel-meta">${state.classes.length || 3} sessions</span>
              </div>
              <div class="schedule-list">
                ${state.classes.slice(0, 3).map((c, i) => `
                  <div class="schedule-item">
                    <div class="schedule-time">${c.start_time}</div>
                    <div class="schedule-bar"></div>
                    <div class="schedule-details">
                      <strong>${c.subject}</strong>
                      <span>${c.faculty_name || "Faculty"} · ${c.batch || "CS-2A"}</span>
                    </div>
                    ${i === 0 ? `<span class="status-pill">NEXT</span>` : ""}
                  </div>
                `).join("")}
              </div>
            </section>
          </div>
        </div>
      </div>
    `;
  }

  // --- 5. Interactive Assignment Portal View (Role-Adaptive) ---
  function renderAssignmentsView() {
    const isFaculty = state.role === "faculty";
    const assignments = state.assignments || [];

    return `
      <div class="assignments-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">${isFaculty ? "Faculty Management" : "Student Portal"} · Assignment Lifecycles</div>
            <h1 class="hero-title">${isFaculty ? "Assignments & Submissions." : "Your Course Assignments."}</h1>
            <p class="hero-copy">${isFaculty
              ? "Create portals, edit or extend deadlines dynamically, and inspect student submissions."
              : `Active assignments filtered strictly for your enrolled batch (${state.user?.batch_id || "CS-2A"}).`}</p>
          </div>
          <div>
            ${isFaculty ? `
              <button class="primary-btn" id="btn-create-assignment-view">
                ${getIcon("plus", 14)} Create Assignment Portal
              </button>
            ` : `
              <div class="date-note">Enrolled Batch: <b>${state.user?.batch_id || "CS-2A"}</b></div>
            `}
          </div>
        </div>

        <div class="assignment-list">
          ${assignments.length > 0 ? assignments.map((a) => {
            const hasSubmitted = Boolean(a.has_submitted);
            const isUrgent = a.hours_remaining && a.hours_remaining <= 24 && !hasSubmitted;

            return `
              <div class="assignment-card">
                <div class="assignment-card-head">
                  <div>
                    <div class="assignment-card-title">${a.title}</div>
                    <div class="assignment-card-meta">
                      <span><strong>Course:</strong> ${a.subject || "Data Structures"}</span>
                      <span>•</span>
                      <span><strong>Batch:</strong> ${a.batch_id}</span>
                      <span>•</span>
                      <span><strong>Faculty:</strong> ${a.faculty_name || "Priya Menon"}</span>
                    </div>
                  </div>

                  <div>
                    ${hasSubmitted ? `
                      <span class="deadline-badge deadline-submitted">${getIcon("check", 12)} Submitted</span>
                    ` : isUrgent ? `
                      <span class="deadline-badge deadline-urgent">${getIcon("clock", 12)} Due in ${Math.round(a.hours_remaining)}h</span>
                    ` : `
                      <span class="deadline-badge deadline-normal">${getIcon("clock", 12)} Due: ${formatDeadline(a.deadline)}</span>
                    `}
                  </div>
                </div>

                <p style="font-size: 11px; color: #b3aec5; margin: 10px 0; line-height: 1.5;">
                  ${a.description || "Review problem description and submit your source code or report."}
                </p>

                <!-- Actions for Faculty vs Student -->
                <div class="assignment-actions">
                  ${isFaculty ? `
                    <span class="status-pill" style="font-size: 10px;">${a.submission_count || 0} / ${a.total_students || 42} submitted</span>
                    <button class="mini-btn" data-action="edit-assignment" data-id="${a.id}">
                      ${getIcon("edit", 12)} Edit Deadline & Portal
                    </button>
                    <button class="mini-btn" data-action="view-submissions" data-id="${a.id}">
                      ${getIcon("people", 12)} View Submissions (${a.submission_count || 0})
                    </button>
                    <a href="/api/assignments/${a.id}/export" class="mini-btn" download>
                      ${getIcon("download", 12)} Export ZIP
                    </a>
                    <button class="mini-btn danger" data-action="delete-assignment" data-id="${a.id}">
                      ${getIcon("trash", 12)} Delete
                    </button>
                  ` : `
                    ${hasSubmitted ? `
                      <span style="font-size: 10px; color: #71cac7; display: flex; align-items: center; gap: 6px;">
                        ${getIcon("check", 14)} File submitted on ${formatDeadline(a.submission_details?.submitted_at)}
                      </span>
                      <button class="mini-btn" data-action="submit-assignment" data-id="${a.id}">
                        ${getIcon("upload", 12)} Replace Submission
                      </button>
                    ` : `
                      <button class="mini-btn primary" data-action="submit-assignment" data-id="${a.id}">
                        ${getIcon("upload", 12)} Upload & Submit Assignment
                      </button>
                    `}
                  `}
                </div>
              </div>
            `;
          }).join("") : `
            <div class="panel" style="padding: 32px; text-align: center; color: #8e87a2;">
              ${getIcon("assignment", 32)}
              <h3 style="color: #f4f1ff; margin: 10px 0 6px;">No assignments found</h3>
              <p style="font-size: 11px;">There are currently no active assignments matching your batch.</p>
            </div>
          `}
        </div>
      </div>
    `;
  }

  // --- 6. Timetable & Schedule View ---
  function renderTimetableView() {
    const isFaculty = state.role === "faculty";
    const classes = state.classes || [];

    return `
      <div class="timetable-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">${isFaculty ? "Faculty Control" : "Student View"} · University Timetable</div>
            <h1 class="hero-title">Academic Schedule & Lectures.</h1>
            <p class="hero-copy">All sessions are integrated with Google Meet spaces and strict host controls.</p>
          </div>
          <div>
            ${isFaculty ? `
              <div style="display: flex; gap: 8px;">
                <button class="secondary-btn" id="btn-upload-timetable-view">${getIcon("upload", 13)} Ingest .xlsx</button>
                <button class="primary-btn" id="btn-sudden-class-view">${getIcon("plus", 13)} Sudden Class</button>
              </div>
            ` : ""}
          </div>
        </div>

        <div style="display: grid; gap: 12px; margin-top: 16px;">
          ${classes.length > 0 ? classes.map((c) => `
            <div class="panel" style="padding: 16px 20px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;">
              <div style="display: flex; align-items: center; gap: 16px;">
                <div style="background: rgba(167, 139, 250, 0.15); border: 1px solid rgba(167, 139, 250, 0.3); border-radius: 8px; padding: 8px 12px; text-align: center;">
                  <strong style="color: #a78bfa; font-size: 13px; display: block;">${c.start_time}</strong>
                  <span style="font-size: 9px; color: #8e87a2;">${c.weekday || "Thursday"}</span>
                </div>
                <div>
                  <strong style="font-size: 13px; color: #f4f1ff; display: block;">${c.subject}</strong>
                  <span style="font-size: 10px; color: #8e87a2;">Faculty: ${c.faculty_name || "Faculty Lead"} · Batch: ${c.batch || "CS-2A"}</span>
                </div>
              </div>

              <div style="display: flex; align-items: center; gap: 10px;">
                <button class="meet-btn ${isFaculty ? "host-mode" : ""}" data-action="launch-meet" data-id="${c.id}">
                  ${getIcon("video", 14)} ${isFaculty ? "Launch Google Meet (Host)" : "Join Google Meet"}
                </button>
              </div>
            </div>
          `).join("") : `<p>No timetable entries available.</p>`}
        </div>
      </div>
    `;
  }

  // --- 7. People Directory View ---
  function renderPeopleView() {
    const isFaculty = state.role === "faculty";
    const people = state.people.length > 0 ? state.people : [
      { full_name: "Priya Menon", email: "priya.menon@college.edu", phone: "+919876543210" },
      { full_name: "Professor Iyer", email: "iyer@college.edu", phone: "+919876543211" },
      { full_name: "Dr. Nandita Bose", email: "bose@college.edu", phone: "+919876543212" }
    ];

    return `
      <div class="directory-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">${isFaculty ? "Faculty Portal" : "Student Portal"} · Connected Directory</div>
            <h1 class="hero-title">${isFaculty ? "The people behind every class." : 'Meet your <span class="accent">teachers.</span>'}</h1>
            <p class="hero-copy">Find teaching teams, mentors, and batch coordinators in one shared directory.</p>
          </div>
          <div class="date-note">${people.length} active educators</div>
        </div>

        <div class="people-grid">
          ${people.map((p) => {
            const inits = (p.full_name || "Faculty").split(" ").map((n) => n[0]).join("");
            return `
              <article class="panel person-card">
                <div class="person-avatar purple">${inits}</div>
                <div class="person-copy">
                  <strong>${p.full_name}</strong>
                  <span>Course Faculty</span>
                  <small>${p.email}</small>
                </div>
                <div class="person-actions">
                  <a href="mailto:${p.email}" class="secondary-btn" style="text-decoration: none;">Contact</a>
                </div>
              </article>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }

  // --- 8. Class Threads View ---
  function renderThreadsView() {
    return `
      <div class="threads-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">Academic Discussion · Collaborative Forum</div>
            <h1 class="hero-title">Class Discussion Threads.</h1>
            <p class="hero-copy">Open loops for questions, concept breakthroughs, and office hour follow-ups.</p>
          </div>
          <button class="primary-btn" id="btn-open-thread-modal">
            ${getIcon("plus", 14)} Start New Thread
          </button>
        </div>

        <div style="display: grid; gap: 10px; margin-top: 16px;">
          ${state.threads.map((t) => `
            <div class="panel" style="padding: 14px 18px; display: flex; align-items: center; justify-content: space-between;">
              <div style="display: flex; align-items: center; gap: 12px;">
                <div class="avatar" style="width: 28px; height: 28px; font-size: 10px;">${t.by.split(" ").map(n => n[0]).join("")}</div>
                <div>
                  <strong style="color: #f4f1ff; font-size: 12px; display: block;">${t.title}</strong>
                  <span style="font-size: 10px; color: #8e87a2;">Started by ${t.by}</span>
                </div>
              </div>
              <span class="status-pill">${t.count} replies</span>
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }

  // --- 9. Modals Layer ---
  function renderActiveModal() {
    if (!state.activeModal) return "";

    switch (state.activeModal) {
      case "assignment_create":
        return renderCreateAssignmentModal();
      case "assignment_edit":
        return renderEditAssignmentModal();
      case "assignment_submit":
        return renderSubmitAssignmentModal();
      case "submissions_view":
        return renderSubmissionsViewModal();
      case "sudden_class":
        return renderSuddenClassModal();
      case "upload_timetable":
        return renderUploadTimetableModal();
      case "manage_batches":
        return renderManageBatchesModal();
      case "thread":
        return renderStartThreadModal();
      default:
        return "";
    }
  }

  function renderCreateAssignmentModal() {
    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div>
              <h2>Upload assignment portal</h2>
              <p>Set the deadline once and dispatch automated notification emails to all enrolled students.</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <form id="form-create-assignment">
            <label class="field-label" for="assign-title">Assignment title</label>
            <input id="assign-title" class="field-input" required placeholder="e.g. Assignment 3: Graph Traversal" />

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <div>
                <label class="field-label" for="assign-subject">Course Subject</label>
                <input id="assign-subject" class="field-input" required value="Data Structures" />
              </div>
              <div>
                <label class="field-label" for="assign-batch">Target Batch</label>
                <input id="assign-batch" class="field-input" required value="CS-2A" />
              </div>
            </div>

            <label class="field-label" for="assign-deadline">Final Submission Deadline</label>
            <input id="assign-deadline" class="field-input" type="datetime-local" required />

            <label class="field-label" for="assign-desc">Instructions & Guidelines</label>
            <textarea id="assign-desc" class="field-input" style="height: 60px; resize: none;" placeholder="Instructions for the students..."></textarea>

            <div style="background: rgba(167, 139, 250, 0.1); border: 1px solid rgba(167, 139, 250, 0.2); border-radius: 8px; padding: 10px 12px; margin-bottom: 14px; font-size: 10px; color: #cfc2ff; display: flex; align-items: center; gap: 8px;">
              ${getIcon("shield", 14)}
              <span>Automated background task will send formatted assignment notification emails to the batch upon creation.</span>
            </div>

            <div class="modal-actions">
              <button type="button" class="secondary-btn" id="btn-cancel-modal">Cancel</button>
              <button type="submit" class="primary-btn" ${state.loading ? "disabled" : ""}>
                ${state.loading ? `<span class="spinner"></span>` : `${getIcon("upload", 13)} Save portal & Dispatch blast`}
              </button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  function renderEditAssignmentModal() {
    const a = state.modalData || {};
    let deadlineVal = "";
    if (a.deadline) {
      try {
        const d = new Date(a.deadline);
        deadlineVal = d.toISOString().slice(0, 16);
      } catch {}
    }

    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div>
              <h2>Edit Assignment Portal</h2>
              <p>Dynamically extend or change deadlines and modify assignment guidelines.</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <form id="form-edit-assignment">
            <label class="field-label" for="edit-title">Assignment title</label>
            <input id="edit-title" class="field-input" required value="${a.title || ""}" />

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <div>
                <label class="field-label" for="edit-subject">Course Subject</label>
                <input id="edit-subject" class="field-input" required value="${a.subject || "Data Structures"}" />
              </div>
              <div>
                <label class="field-label" for="edit-batch">Target Batch</label>
                <input id="edit-batch" class="field-input" required value="${a.batch_id || "CS-2A"}" />
              </div>
            </div>

            <label class="field-label" for="edit-deadline">Dynamically Adjust Deadline</label>
            <input id="edit-deadline" class="field-input" type="datetime-local" required value="${deadlineVal}" />

            <label class="field-label" for="edit-desc">Instructions</label>
            <textarea id="edit-desc" class="field-input" style="height: 60px; resize: none;">${a.description || ""}</textarea>

            <div class="modal-actions">
              <button type="button" class="secondary-btn" id="btn-cancel-modal">Cancel</button>
              <button type="submit" class="primary-btn" ${state.loading ? "disabled" : ""}>
                ${state.loading ? `<span class="spinner"></span>` : `${getIcon("check", 13)} Update Deadline`}
              </button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  function renderSubmitAssignmentModal() {
    const a = state.modalData || {};
    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div>
              <h2>Submit Assignment</h2>
              <p>${a.title || "Assignment Submission"} · ${a.batch_id}</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <form id="form-submit-assignment">
            <label class="upload-zone" id="upload-zone-drop">
              ${getIcon("upload", 28)}
              <strong style="color: #f4f1ff;">Choose submission file</strong>
              <span>PDF or Image (PNG, JPG) up to 25 MB</span>
              <input type="file" id="submit-file-input" accept=".pdf,.png,.jpg,.jpeg,.gif" style="display: none;" />
            </label>
            <div id="selected-file-name" style="font-size: 11px; color: #61d7da; margin-bottom: 12px; text-align: center;"></div>

            <div class="modal-actions">
              <button type="button" class="secondary-btn" id="btn-cancel-modal">Cancel</button>
              <button type="submit" class="primary-btn" id="btn-do-submit" disabled>
                ${getIcon("check", 13)} Upload & Submit
              </button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  function renderSubmissionsViewModal() {
    const a = state.modalData || {};
    const list = state.submissions || [];

    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" style="width: min(580px, 100%);" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div>
              <h2>Submissions for ${a.title || "Assignment"}</h2>
              <p>${list.length} student submissions received</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <div style="max-height: 320px; overflow-y: auto; margin: 12px 0;">
            ${list.length > 0 ? list.map((s) => `
              <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(138,127,195,0.15); border-radius: 8px; padding: 12px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
                <div>
                  <strong style="color: #f4f1ff; font-size: 12px;">${s.student_name || "Student " + s.student_id}</strong>
                  <div style="font-size: 10px; color: #8e87a2;">${s.original_filename || "submission.pdf"} · ${formatDeadline(s.submitted_at)}</div>
                </div>
                <span class="status-pill" style="color: #48c78e; border-color: #48c78e44;">Submitted</span>
              </div>
            `).join("") : `<p style="font-size: 11px; color: #8e87a2; text-align: center; padding: 20px;">No student submissions recorded yet.</p>`}
          </div>

          <div class="modal-actions">
            <button class="primary-btn" id="btn-cancel-modal">Done</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderSuddenClassModal() {
    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div>
              <h2>Schedule a Sudden Class</h2>
              <p>Instant Google Meet generation with Strict Host Controls & batch email blast.</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <form id="form-sudden-class">
            <label class="field-label" for="sudden-title">Session Title</label>
            <input id="sudden-title" class="field-input" required placeholder="e.g. Graph Traversal Algorithms Review" />

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <div>
                <label class="field-label" for="sudden-date">Date</label>
                <input id="sudden-date" class="field-input" type="date" required value="${new Date().toISOString().slice(0, 10)}" />
              </div>
              <div>
                <label class="field-label" for="sudden-time">Time</label>
                <input id="sudden-time" class="field-input" type="time" required value="17:00" />
              </div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <div>
                <label class="field-label" for="sudden-batch">Target Batch</label>
                <select id="sudden-batch" class="field-input">
                  <option value="CS-2A">CS-2A (Data Structures)</option>
                  <option value="CS-1B">CS-1B (Algorithms)</option>
                </select>
              </div>
              <div>
                <label class="field-label" for="sudden-duration">Duration</label>
                <select id="sudden-duration" class="field-input">
                  <option value="60">60 minutes</option>
                  <option value="45">45 minutes</option>
                  <option value="90">90 minutes</option>
                </select>
              </div>
            </div>

            <div class="delivery-options" style="padding: 10px; margin-bottom: 14px;">
              <label style="display: flex; align-items: center; gap: 8px; font-size: 10px; color: #c5c0d6; margin-bottom: 6px;">
                <input type="checkbox" checked disabled />
                Generate Google Meet space (Strict Faculty Host Controls)
              </label>
              <label style="display: flex; align-items: center; gap: 8px; font-size: 10px; color: #c5c0d6;">
                <input type="checkbox" id="sudden-send-email" checked />
                Auto-dispatch alert emails to enrolled batch students
              </label>
            </div>

            <div class="modal-actions">
              <button type="button" class="secondary-btn" id="btn-cancel-modal">Cancel</button>
              <button type="submit" class="primary-btn" ${state.loading ? "disabled" : ""}>
                ${state.loading ? `<span class="spinner"></span>` : `${getIcon("video", 13)} Schedule & Dispatch`}
              </button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  function renderUploadTimetableModal() {
    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div>
              <h2>Upload University Timetable</h2>
              <p>Map .xlsx or .xlsm rosters into lectures and Google Meet spaces.</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <form id="form-upload-timetable">
            <label class="upload-zone" id="upload-zone-tt">
              ${getIcon("upload", 28)}
              <strong style="color: #f4f1ff;">Drop university roster here</strong>
              <span>.XLSX or .XLSM up to 10 MB</span>
              <input type="file" id="tt-file-input" accept=".xlsx,.xlsm" style="display: none;" />
            </label>
            <div id="tt-file-name" style="font-size: 11px; color: #61d7da; margin-bottom: 12px; text-align: center;"></div>

            <div class="modal-actions">
              <button type="button" class="secondary-btn" id="btn-cancel-modal">Cancel</button>
              <button type="submit" class="primary-btn" id="btn-do-upload-tt" disabled>
                ${getIcon("upload", 13)} Ingest Timetable
              </button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  function renderManageBatchesModal() {
    const batches = state.batches || [];
    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div>
              <h2>Manage Batches</h2>
              <p>Active learning groups and roster sizes.</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <div style="display: grid; gap: 8px; margin: 14px 0;">
            ${batches.map((b) => `
              <div class="schedule-item" style="background: rgba(255,255,255,0.02); padding: 11px; border-radius: 8px; border: 1px solid rgba(147,133,204,0.15);">
                <div class="avatar" style="width: 27px; height: 27px;">${b.name.slice(0, 2)}</div>
                <div class="schedule-details">
                  <strong>Batch ${b.name}</strong>
                  <span>${b.learner_count || 42} enrolled learners · active</span>
                </div>
                ${getIcon("check", 15, "accent")}
              </div>
            `).join("")}
          </div>

          <div class="modal-actions">
            <button class="primary-btn" id="btn-cancel-modal">Done</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderStartThreadModal() {
    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div>
              <h2>Start a New Thread</h2>
              <p>Open a clear loop for your class to think together.</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <form id="form-start-thread">
            <label class="field-label" for="thread-title-input">Thread Title</label>
            <input id="thread-title-input" class="field-input" required placeholder="What are we exploring?" />

            <div class="modal-actions">
              <button type="button" class="secondary-btn" id="btn-cancel-modal">Cancel</button>
              <button type="submit" class="primary-btn">Start Thread</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  // --- 10. Workspace Event Bindings ---
  function bindWorkspaceEvents() {
    // Navigation Tabs
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        if (tab) {
          state.currentTab = tab;
          render();
        }
      });
    });

    const isActualFaculty = (state.user && state.user.role ? state.user.role : "STUDENT").toUpperCase() === "FACULTY";

    // Role Switchers (Only available and bound for Faculty accounts)
    const switchFac = document.getElementById("switch-faculty");
    const switchStd = document.getElementById("switch-student");
    if (switchFac && isActualFaculty) {
      switchFac.addEventListener("click", () => {
        state.role = "faculty";
        state.currentTab = "Dashboard";
        showToast("Switched to Faculty Portal view");
        render();
      });
    }
    if (switchStd && isActualFaculty) {
      switchStd.addEventListener("click", () => {
        state.role = "student";
        state.currentTab = "Dashboard";
        showToast("Switched to Student Portal preview");
        render();
      });
    }

    // Sign Out Action Handlers
    const btnLogout = document.getElementById("btn-logout");
    if (btnLogout) {
      btnLogout.addEventListener("click", () => api.logout());
    }
    const btnSidebarSignout = document.getElementById("btn-sidebar-signout");
    if (btnSidebarSignout) {
      btnSidebarSignout.addEventListener("click", () => api.logout());
    }
    const btnTopbarSignout = document.getElementById("btn-topbar-signout");
    if (btnTopbarSignout) {
      btnTopbarSignout.addEventListener("click", () => api.logout());
    }

    // Notifications toggle
    const btnNotif = document.getElementById("btn-notifications");
    if (btnNotif) {
      btnNotif.addEventListener("click", () => {
        state.notificationOpen = !state.notificationOpen;
        render();
      });
    }

    // Floating action button
    const btnFloating = document.getElementById("btn-floating-action");
    if (btnFloating) {
      btnFloating.addEventListener("click", () => {
        if (isActualFaculty && state.role === "faculty") {
          state.activeModal = "sudden_class";
        } else {
          state.activeModal = "thread";
        }
        render();
      });
    }

    // Faculty dashboard action triggers
    const btnOpenUpload = document.getElementById("btn-open-upload-modal");
    if (btnOpenUpload) btnOpenUpload.addEventListener("click", () => { state.activeModal = "upload_timetable"; render(); });

    const btnOpenSudden = document.getElementById("btn-open-sudden-class");
    if (btnOpenSudden) btnOpenSudden.addEventListener("click", () => { state.activeModal = "sudden_class"; render(); });

    const btnQuickSudden = document.getElementById("btn-quick-sudden-class");
    if (btnQuickSudden) btnQuickSudden.addEventListener("click", () => { state.activeModal = "sudden_class"; render(); });

    const btnQuickAssign = document.getElementById("btn-quick-new-assignment");
    if (btnQuickAssign) btnQuickAssign.addEventListener("click", () => { state.activeModal = "assignment_create"; render(); });

    const btnCreateAssignView = document.getElementById("btn-create-assignment-view");
    if (btnCreateAssignView) btnCreateAssignView.addEventListener("click", () => { state.activeModal = "assignment_create"; render(); });

    const btnManageBatches = document.getElementById("btn-manage-batches");
    if (btnManageBatches) btnManageBatches.addEventListener("click", () => { state.activeModal = "manage_batches"; render(); });

    const btnTriggerReminders = document.getElementById("btn-trigger-reminders");
    if (btnTriggerReminders) btnTriggerReminders.addEventListener("click", () => api.triggerReminders());

    const btnUploadTtView = document.getElementById("btn-upload-timetable-view");
    if (btnUploadTtView) btnUploadTtView.addEventListener("click", () => { state.activeModal = "upload_timetable"; render(); });

    const btnSuddenClassView = document.getElementById("btn-sudden-class-view");
    if (btnSuddenClassView) btnSuddenClassView.addEventListener("click", () => { state.activeModal = "sudden_class"; render(); });

    const btnOpenThread = document.getElementById("btn-open-thread-modal");
    if (btnOpenThread) btnOpenThread.addEventListener("click", () => { state.activeModal = "thread"; render(); });

    // Meet launch buttons
    document.querySelectorAll('[data-action="launch-meet"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.id;
        api.launchMeet(id);
      });
    });

    // Assignment buttons
    document.querySelectorAll('[data-action="edit-assignment"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = Number(btn.dataset.id);
        const a = state.assignments.find((item) => item.id === id);
        state.modalData = a;
        state.activeModal = "assignment_edit";
        render();
      });
    });

    document.querySelectorAll('[data-action="view-submissions"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = Number(btn.dataset.id);
        const a = state.assignments.find((item) => item.id === id);
        state.modalData = a;
        api.viewSubmissions(id);
      });
    });

    document.querySelectorAll('[data-action="delete-assignment"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = Number(btn.dataset.id);
        api.deleteAssignment(id);
      });
    });

    document.querySelectorAll('[data-action="submit-assignment"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = Number(btn.dataset.id);
        const a = state.assignments.find((item) => item.id === id);
        state.modalData = a;
        state.activeModal = "assignment_submit";
        render();
      });
    });

    // Modal Close
    bindModalEvents();
  }

  function bindModalEvents() {
    const backdrop = document.getElementById("modal-backdrop");
    const closeBtn = document.getElementById("btn-close-modal");
    const cancelBtn = document.getElementById("btn-cancel-modal");

    const closeModal = () => {
      state.activeModal = null;
      state.modalData = null;
      render();
    };

    if (backdrop) backdrop.addEventListener("click", closeModal);
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    if (cancelBtn) cancelBtn.addEventListener("click", closeModal);

    // Create Assignment Form
    const formCreate = document.getElementById("form-create-assignment");
    if (formCreate) {
      formCreate.addEventListener("submit", (e) => {
        e.preventDefault();
        const title = document.getElementById("assign-title").value.trim();
        const subject = document.getElementById("assign-subject").value.trim();
        const batch_id = document.getElementById("assign-batch").value.trim();
        const deadline = document.getElementById("assign-deadline").value;
        const description = document.getElementById("assign-desc").value.trim();

        api.createAssignment({
          title,
          subject,
          batch_id,
          deadline: new Date(deadline).toISOString(),
          description
        });
      });
    }

    // Edit Assignment Form
    const formEdit = document.getElementById("form-edit-assignment");
    if (formEdit) {
      formEdit.addEventListener("submit", (e) => {
        e.preventDefault();
        const title = document.getElementById("edit-title").value.trim();
        const subject = document.getElementById("edit-subject").value.trim();
        const batch_id = document.getElementById("edit-batch").value.trim();
        const deadline = document.getElementById("edit-deadline").value;
        const description = document.getElementById("edit-desc").value.trim();

        api.updateAssignment(state.modalData.id, {
          title,
          subject,
          batch_id,
          deadline: new Date(deadline).toISOString(),
          description
        });
      });
    }

    // Submit Assignment Form (File Picker & Dropzone)
    const formSubmit = document.getElementById("form-submit-assignment");
    const dropZone = document.getElementById("upload-zone-drop");
    const fileInput = document.getElementById("submit-file-input");
    const fileNameDisplay = document.getElementById("selected-file-name");
    const submitBtn = document.getElementById("btn-do-submit");
    let chosenFile = null;

    if (dropZone && fileInput) {
      dropZone.addEventListener("click", () => fileInput.click());
      dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragging"); });
      dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
      dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragging");
        if (e.dataTransfer.files.length) {
          chosenFile = e.dataTransfer.files[0];
          fileNameDisplay.textContent = `Selected: ${chosenFile.name} (${Math.round(chosenFile.size / 1024)} KB)`;
          if (submitBtn) submitBtn.disabled = false;
        }
      });
      fileInput.addEventListener("change", () => {
        if (fileInput.files.length) {
          chosenFile = fileInput.files[0];
          fileNameDisplay.textContent = `Selected: ${chosenFile.name} (${Math.round(chosenFile.size / 1024)} KB)`;
          if (submitBtn) submitBtn.disabled = false;
        }
      });
    }

    if (formSubmit) {
      formSubmit.addEventListener("submit", (e) => {
        e.preventDefault();
        if (chosenFile && state.modalData) {
          api.submitAssignment(state.modalData.id, chosenFile);
        }
      });
    }

    // Sudden Class Form
    const formSudden = document.getElementById("form-sudden-class");
    if (formSudden) {
      formSudden.addEventListener("submit", (e) => {
        e.preventDefault();
        const subject = document.getElementById("sudden-title").value.trim();
        const class_date = document.getElementById("sudden-date").value;
        const start_time = document.getElementById("sudden-time").value;
        const batch = document.getElementById("sudden-batch").value;
        const duration_minutes = Number(document.getElementById("sudden-duration").value);

        api.scheduleSuddenClass({
          subject,
          class_date,
          start_time,
          batch,
          duration_minutes,
          faculty_name: state.user?.name || "Priya Menon",
          faculty_email: state.user?.email || "priya.menon@college.edu"
        });
      });
    }

    // Upload Timetable Form
    const formUploadTt = document.getElementById("form-upload-timetable");
    const dropZoneTt = document.getElementById("upload-zone-tt");
    const fileInputTt = document.getElementById("tt-file-input");
    const fileNameTt = document.getElementById("tt-file-name");
    const uploadTtBtn = document.getElementById("btn-do-upload-tt");
    let chosenTtFile = null;

    if (dropZoneTt && fileInputTt) {
      dropZoneTt.addEventListener("click", () => fileInputTt.click());
      dropZoneTt.addEventListener("dragover", (e) => { e.preventDefault(); dropZoneTt.classList.add("dragging"); });
      dropZoneTt.addEventListener("dragleave", () => dropZoneTt.classList.remove("dragging"));
      dropZoneTt.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZoneTt.classList.remove("dragging");
        if (e.dataTransfer.files.length) {
          chosenTtFile = e.dataTransfer.files[0];
          fileNameTt.textContent = `Selected: ${chosenTtFile.name}`;
          if (uploadTtBtn) uploadTtBtn.disabled = false;
        }
      });
      fileInputTt.addEventListener("change", () => {
        if (fileInputTt.files.length) {
          chosenTtFile = fileInputTt.files[0];
          fileNameTt.textContent = `Selected: ${chosenTtFile.name}`;
          if (uploadTtBtn) uploadTtBtn.disabled = false;
        }
      });
    }

    if (formUploadTt) {
      formUploadTt.addEventListener("submit", (e) => {
        e.preventDefault();
        if (chosenTtFile) {
          api.uploadTimetable(chosenTtFile);
        }
      });
    }

    // Start Thread Form
    const formThread = document.getElementById("form-start-thread");
    if (formThread) {
      formThread.addEventListener("submit", (e) => {
        e.preventDefault();
        const title = document.getElementById("thread-title-input").value.trim();
        if (title) {
          state.threads.unshift({ title, by: state.user?.name || "Member", count: 0 });
          showToast(`Discussion thread created: "${title}"`);
          state.activeModal = null;
          render();
        }
      });
    }
  }

  function renderToast() {
    if (!state.toast) return "";
    return `
      <div class="toast">
        ${getIcon("check", 14)}
        <span>${state.toast}</span>
      </div>
    `;
  }

  // --- Initial Startup ---
  window.addEventListener("DOMContentLoaded", async () => {
    if (state.token && state.user) {
      await api.loadDashboardData();
    }
    render();
  });
})();