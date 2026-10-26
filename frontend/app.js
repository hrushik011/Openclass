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
    notes: [],
    notesSearch: "",
    notesSubjectFilter: "All",
    activeModal: null, // "assignment_create" | "assignment_edit" | "assignment_submit" | "submissions_view" | "sudden_class" | "upload_timetable" | "manage_batches" | "thread" | "attendance_roster"
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
    attendanceRoster: null,   // current loaded roster { class_id, subject, roster: [] }
    attendanceLoading: false, // for roster fetch spinner
    studentAttendance: null,  // GET /api/attendance/student/{id} breakdown
    facultyAttendance: null,  // GET /api/faculty/attendance/summary
    threads: [],
    threadScopeFilter: "all",
    activeThread: null,
    threadComposeScope: "public"
  };

  if (state.user && state.user.role) {
    const roleUpper = state.user.role.toUpperCase();
    state.role = roleUpper === "FACULTY" ? "faculty" : "student";
  }

  function cleanSubjectName(raw) {
    if (!raw) return "";
    return String(raw)
      .replace(/\s+(CS-[0-9][A-Z0-9]*|[A-Z]{2,3}-[0-9][A-Z0-9]*)$/i, "")
      .trim() || String(raw).trim();
  }

  function uniqueSubjectList(items = []) {
    const seen = new Set();
    const options = [];
    (items || []).forEach((label) => {
      const value = String(label || "").trim();
      if (!value) return;
      const key = value.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      options.push(value);
    });
    return options;
  }

  function getClassesSubjects() {
    const seen = new Set();
    const subjects = [];
    (state.classes || []).forEach((c) => {
      const raw = String(c.subject || "").trim();
      if (!raw) return;
      const cleaned = cleanSubjectName(raw);
      const key = cleaned.toLowerCase();
      if (!seen.has(key)) {
        seen.add(key);
        subjects.push(cleaned);
      }
    });
    return subjects;
  }

  function facultyNoteSubjects() {
    const extras = [];
    (state.classes || []).forEach((item) => extras.push(cleanSubjectName(item.subject)));
    (state.assignments || []).forEach((item) => extras.push(cleanSubjectName(item.subject)));
    (state.notes || []).forEach((item) => extras.push(cleanSubjectName(item.subject)));
    return uniqueSubjectList(extras);
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
      fileText: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`,
      attendance: `<svg width="${s}" height="${s}" class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"></path><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg>`
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
      state.notes = [];
      state.notesSearch = "";
      state.notesSubjectFilter = "All";
      state.activeModal = null;
      state.modalData = null;
      state.loginError = "";
      state.filterSearch = "";
      state.notificationOpen = false;
      state.attendanceRoster = null;
      state.studentAttendance = null;
      state.facultyAttendance = null;
      state.threads = [];
      state.threadScopeFilter = "all";
      state.activeThread = null;
      state.threadComposeScope = "public";

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
      } catch { }

      // Reset URL to clean base path
      try {
        window.history.replaceState({}, document.title, window.location.pathname);
      } catch { }

      showToast("Signed out successfully from OpenClass.");
      render();
    },

    studentId() {
      const user = state.user || {};
      return user.id || user.roll_no || user.student_id || null;
    },

    async loadStudentAttendance() {
      const sid = api.studentId();
      if (!sid || !state.token) return;
      try {
        const res = await fetch(`/api/attendance/student/${encodeURIComponent(sid)}`, {
          headers: api.headers()
        });
        if (res.ok) state.studentAttendance = await res.json();
      } catch (e) {
        console.warn("Student attendance fetch failed", e);
      }
    },

    async loadFacultyAttendanceSummary() {
      if (!state.token) return;
      try {
        const res = await fetch("/api/faculty/attendance/summary", {
          headers: api.headers()
        });
        if (res.ok) state.facultyAttendance = await res.json();
      } catch (e) {
        console.warn("Faculty attendance summary fetch failed", e);
      }
    },

    async loadThreads() {
      if (!state.token) return;
      try {
        const res = await fetch("/api/threads", { headers: api.headers() });
        if (res.ok) state.threads = await res.json();
      } catch (e) {
        console.warn("Threads fetch failed", e);
      }
    },

    async loadThread(threadId) {
      try {
        const res = await fetch(`/api/threads/${threadId}`, { headers: api.headers() });
        if (!res.ok) throw new Error("Could not open thread");
        state.activeThread = await res.json();
        render();
      } catch (e) {
        showToast(`Error: ${e.message}`);
      }
    },

    async createThread(payload) {
      state.loading = true;
      render();
      try {
        const res = await fetch("/api/threads", {
          method: "POST",
          headers: api.headers(),
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Could not create thread");
        const scope = payload.scope_type;
        if (scope === "private") {
          showToast(`Private message sent to faculty · email alert queued`);
        } else if (scope === "batch") {
          showToast(`Batch thread posted · enrolled students will be notified if this is a faculty announcement`);
        } else {
          showToast(`Public thread started: "${data.title}"`);
        }
        state.activeModal = null;
        state.threadComposeScope = "public";
        await api.loadThreads();
        state.activeThread = data;
      } catch (e) {
        showToast(`Error: ${e.message}`);
      } finally {
        state.loading = false;
        render();
      }
    },

    async postThreadMessage(threadId, body) {
      try {
        const res = await fetch(`/api/threads/${threadId}/messages`, {
          method: "POST",
          headers: api.headers(),
          body: JSON.stringify({ body })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Could not send message");
        await api.loadThread(threadId);
        await api.loadThreads();
      } catch (e) {
        showToast(`Error: ${e.message}`);
      }
    },

    async loadDashboardData() {
      if (!state.token) return;
      try {
        const [clsRes, assignRes, batchRes, peopleRes, notesRes] = await Promise.all([
          fetch("/api/classes", { headers: api.headers() }),
          fetch("/api/assignments", { headers: api.headers() }),
          fetch("/api/batches", { headers: api.headers() }),
          fetch("/api/people", { headers: api.headers() }),
          fetch("/api/notes", { headers: api.headers() })
        ]);
        if (clsRes.ok) state.classes = await clsRes.json();
        if (assignRes.ok) state.assignments = await assignRes.json();
        if (batchRes.ok) state.batches = await batchRes.json();
        if (peopleRes.ok) state.people = await peopleRes.json();
        if (notesRes && notesRes.ok) state.notes = await notesRes.json();
        await api.loadStudentAttendance();
        await api.loadFacultyAttendanceSummary();
        await api.loadThreads();
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
    },

    async attendanceCheckIn(sessionId, sessionData) {
      // Called before opening the Google Meet link for students
      try {
        const user = state.user || {};
        const sid = String(api.studentId() || "std-001");
        await fetch("/api/attendance/check-in", {
          method: "POST",
          headers: api.headers(),
          body: JSON.stringify({
            student_id: sid,
            student_name: user.name || null,
            batch_id: user.batch_id || null,
            class_id: Number(sessionId)
          })
        });
        await api.loadStudentAttendance();
      } catch (e) {
        console.warn("Attendance check-in error (non-blocking):", e.message);
      }
    },

    async launchMeetWithCheckIn(sessionId) {
      // For students: check in first, then open Meet
      const isStudent = (state.user && state.user.role && state.user.role.toUpperCase() === "STUDENT") || state.role === "student";
      if (isStudent) {
        await api.attendanceCheckIn(sessionId);
      }
      const launched = api.launchMeet(sessionId);
      if (isStudent && state.currentTab === "Dashboard") render();
      return launched;
    },

    async loadSessionRoster(classId) {
      state.attendanceLoading = true;
      render();
      try {
        const res = await fetch(`/api/attendance/session/${classId}`, {
          headers: api.headers()
        });
        if (!res.ok) throw new Error("Could not load attendance roster");
        state.attendanceRoster = await res.json();
        state.activeModal = "attendance_roster";
      } catch (e) {
        showToast(`Roster error: ${e.message}`);
      } finally {
        state.attendanceLoading = false;
        render();
      }
    },

    async saveAttendanceOverrides(classId, overrides) {
      state.loading = true;
      render();
      try {
        const res = await fetch(`/api/attendance/session/${classId}/override`, {
          method: "POST",
          headers: api.headers(),
          body: JSON.stringify({ overrides })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Override failed");
        showToast(`Attendance finalized · ${data.overrides_applied} records saved.`);
        await api.loadFacultyAttendanceSummary();
        // Refresh roster in modal
        await api.loadSessionRoster(classId);
      } catch (e) {
        showToast(`Error: ${e.message}`);
      } finally {
        state.loading = false;
        render();
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

  async function handleUploadNotes(event) {
    event.preventDefault();
    const form = event.target;
    if (!form) return;

    const formData = new FormData(form);
    const title = String(formData.get("title") || "").trim();
    const subject = String(formData.get("subject") || "").trim();
    const file = formData.get("file");

    if (!title || !subject || !(file instanceof File) || !file.name) {
      showToast("Please provide a title, subject, and file.");
      return;
    }

    const specialization = String(formData.get("specialization") || "").trim();
    if (!specialization) {
      formData.delete("specialization");
    }

    state.loading = true;
    render();
    try {
      const res = await fetch("/api/faculty/notes", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${state.token}`
        },
        body: formData
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to upload lecture notes");
      const queued = data.emails_queued != null ? data.emails_queued : 0;
      showToast(`Lecture notes "${data.title || title}" posted · ${queued} student email(s) queued`);
    } catch (e) {
      showToast(`Error: ${e.message}`);
    } finally {
      state.loading = false;
      render();
    }
  }

  function ensureNotesFilterStyles() {
    if (document.getElementById("notes-filter-styles")) return;
    const style = document.createElement("style");
    style.id = "notes-filter-styles";
    style.textContent = `
      .notes-filter-bar {
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin: 2px 0 16px;
        padding: 14px 16px;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.025);
        border: 1px solid rgba(147, 133, 204, 0.16);
      }
      .notes-search-wrap {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 9px 14px;
        border-radius: 10px;
        background: rgba(18, 17, 30, 0.65);
        border: 1px solid rgba(147, 133, 204, 0.18);
        transition: border-color 0.15s, box-shadow 0.15s;
      }
      .notes-search-wrap:focus-within {
        border-color: rgba(167, 139, 250, 0.6);
        box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.15);
      }
      .notes-search-wrap svg { opacity: 0.6; flex-shrink: 0; }
      #notes-search-input {
        flex: 1;
        background: transparent;
        border: 0;
        outline: none;
        color: #f4f1ff;
        font-size: 13px;
        font-family: inherit;
      }
      #notes-search-input::placeholder { color: #8e87a2; }
      #notes-subject-filters {
        display: flex;
        gap: 7px;
        overflow-x: auto;
        scrollbar-width: none;
        padding-bottom: 2px;
      }
      #notes-subject-filters::-webkit-scrollbar { display: none; }
      .notes-subject-pill {
        flex-shrink: 0;
        border: 1px solid rgba(147, 133, 204, 0.22);
        background: rgba(255, 255, 255, 0.02);
        color: #b3aec5;
        border-radius: 999px;
        padding: 6px 14px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.01em;
        cursor: pointer;
        font-family: inherit;
        transition: all 0.15s ease;
      }
      .notes-subject-pill:hover {
        color: #f4f1ff;
        border-color: rgba(167, 139, 250, 0.45);
        background: rgba(167, 139, 250, 0.08);
      }
      .notes-subject-pill.active {
        background: rgba(167, 139, 250, 0.22);
        border-color: rgba(167, 139, 250, 0.6);
        color: #ffffff;
        box-shadow: 0 2px 10px rgba(167, 139, 250, 0.2);
      }
      .knowledge-hub-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
        gap: 16px;
        margin-top: 16px;
      }
      .hub-resource-card {
        background: linear-gradient(145deg, rgba(31, 29, 47, 0.75), rgba(20, 19, 31, 0.88));
        border: 1px solid rgba(147, 133, 204, 0.16);
        border-radius: 14px;
        padding: 18px 20px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 195px;
        transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
      }
      .hub-resource-card:hover {
        transform: translateY(-2px);
        border-color: rgba(167, 139, 250, 0.45);
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.4), 0 0 18px rgba(167, 139, 250, 0.12);
      }
      .hub-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }
      .hub-file-badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 9px;
        font-weight: 700;
        font-family: var(--app-font-mono);
        letter-spacing: 0.05em;
      }
      .hub-card-body {
        margin: 12px 0 14px;
        flex: 1;
      }
      .hub-card-title {
        font-size: 13px;
        font-weight: 700;
        color: #f4f1ff;
        margin: 0 0 6px;
        line-height: 1.35;
      }
      .hub-card-filename {
        font-size: 10px;
        color: #9d94bf;
        font-family: var(--app-font-mono);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        display: flex;
        align-items: center;
        gap: 5px;
        margin-bottom: 8px;
        opacity: 0.85;
      }
      .hub-card-meta {
        font-size: 10px;
        color: #8e87a2;
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
      }
      .hub-meta-item {
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }
      .hub-card-footer {
        border-top: 1px solid rgba(147, 133, 204, 0.12);
        padding-top: 12px;
        margin-top: auto;
      }
      .hub-download-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        width: 100%;
        padding: 8px 12px;
        border-radius: 8px;
        background: rgba(167, 139, 250, 0.12);
        border: 1px solid rgba(167, 139, 250, 0.28);
        color: #dcd4ff;
        font-size: 10px;
        font-weight: 700;
        text-decoration: none;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .hub-download-btn:hover {
        background: linear-gradient(135deg, #795bd0, #5c48b2);
        border-color: #a78bfa;
        color: #ffffff;
        box-shadow: 0 4px 14px rgba(121, 91, 208, 0.4);
      }
    `;
    document.head.appendChild(style);
  }

  function getFileBadgeInfo(filename) {
    const ext = String(filename || "").split(".").pop().toLowerCase();
    if (ext === "pdf") {
      return { label: "PDF", color: "#ff8b7b", bg: "rgba(255, 107, 107, 0.15)", border: "rgba(255, 107, 107, 0.3)" };
    } else if (ext === "pptx" || ext === "ppt") {
      return { label: "SLIDES", color: "#fca34d", bg: "rgba(252, 163, 77, 0.15)", border: "rgba(252, 163, 77, 0.3)" };
    } else if (ext === "xlsx" || ext === "xls" || ext === "csv") {
      return { label: "SHEET", color: "#61d7da", bg: "rgba(97, 215, 218, 0.15)", border: "rgba(97, 215, 218, 0.3)" };
    } else if (ext === "docx" || ext === "doc") {
      return { label: "DOC", color: "#a78bfa", bg: "rgba(167, 139, 250, 0.15)", border: "rgba(167, 139, 250, 0.3)" };
    } else {
      return { label: "RESOURCE", color: "#a78bfa", bg: "rgba(167, 139, 250, 0.15)", border: "rgba(167, 139, 250, 0.3)" };
    }
  }

  function notesSubjectOptions() {
    return ["All"].concat(getClassesSubjects());
  }

  function renderNotesSubjectPills() {
    const row = document.getElementById("notes-subject-filters");
    if (!row) return;
    const active = state.notesSubjectFilter || "All";
    row.innerHTML = notesSubjectOptions().map((subject) => {
      const isActive = subject.toLowerCase() === String(active).toLowerCase();
      return `<button type="button" class="notes-subject-pill${isActive ? " active" : ""}" data-subject="${subject}">${subject}</button>`;
    }).join("");
  }

  function filteredStudentNotes() {
    const query = String(state.notesSearch || "").trim().toLowerCase();
    const subjectFilter = String(state.notesSubjectFilter || "All");
    return (state.notes || []).filter((note) => {
      const title = String(note.title || "").toLowerCase();
      const filename = String(note.original_filename || "").toLowerCase();
      const faculty = String(note.faculty_name || "").toLowerCase();
      const spec = String(note.specialization || "").toLowerCase();
      const matchesQuery = !query || title.includes(query) || filename.includes(query) || faculty.includes(query) || spec.includes(query);

      const noteSubject = String(note.subject || "").toLowerCase();
      const targetSubject = subjectFilter.toLowerCase();
      const matchesSubject =
        !subjectFilter ||
        targetSubject === "all" ||
        noteSubject === targetSubject ||
        (targetSubject === "investments" && (noteSubject.includes("investment") || title.includes("invest"))) ||
        noteSubject.includes(targetSubject);

      return matchesQuery && matchesSubject;
    });
  }

  function renderNotesGridContent(notes) {
    if (!(state.notes || []).length) {
      return `
        <div class="panel" style="grid-column: 1 / -1; padding: 48px 24px; text-align: center; color: #8e87a2;">
          <div style="display: inline-flex; align-items: center; justify-content: center; width: 48px; height: 48px; border-radius: 50%; background: rgba(167, 139, 250, 0.12); color: #a78bfa; margin-bottom: 12px;">
            ${getIcon("hub", 24)}
          </div>
          <h3 style="color: #f4f1ff; font-size: 14px; margin-bottom: 6px;">Course Repository is Empty</h3>
          <p style="font-size: 11px; max-width: 420px; margin: 0 auto;">No lecture notes or course resources have been uploaded to the repository yet.</p>
        </div>
      `;
    }

    if (!notes.length) {
      return `
        <div class="panel" style="grid-column: 1 / -1; padding: 48px 24px; text-align: center; color: #8e87a2;">
          <div style="display: inline-flex; align-items: center; justify-content: center; width: 48px; height: 48px; border-radius: 50%; background: rgba(255, 107, 107, 0.1); color: #ff8b7b; margin-bottom: 12px;">
            ${getIcon("search", 24)}
          </div>
          <h3 style="color: #f4f1ff; font-size: 14px; margin-bottom: 6px;">No Matching Resources</h3>
          <p style="font-size: 11px; max-width: 420px; margin: 0 auto;">No documents match "${state.notesSearch || state.notesSubjectFilter}". Try adjusting your search query or subject filter.</p>
          <div style="margin-top: 14px;">
            <button type="button" class="secondary-btn" id="btn-reset-notes-filter">Reset Filters</button>
          </div>
        </div>
      `;
    }

    return notes.map((note) => {
      const fileName = note.original_filename || "Download resource";
      const faculty = note.faculty_name || "Course Lead";
      const spec = note.specialization ? `Batch ${note.specialization}` : "All Batches";
      const posted = note.created_at ? formatDeadline(note.created_at) : "";
      const href = `/api/notes/${note.id}/file`;
      const badge = getFileBadgeInfo(fileName);

      return `
        <article class="hub-resource-card">
          <div class="hub-card-header">
            <div class="hub-file-badge" style="background: ${badge.bg}; color: ${badge.color}; border: 1px solid ${badge.border};">
              ${getIcon("fileText", 12)}
              <span>${badge.label}</span>
            </div>
            <span class="status-pill">${note.subject || "Coursework"}</span>
          </div>

          <div class="hub-card-body">
            <h3 class="hub-card-title" title="${note.title || "Lecture notes"}">${note.title || "Lecture notes"}</h3>
            <div class="hub-card-filename" title="${fileName}">
              ${getIcon("fileText", 11)} <span>${fileName}</span>
            </div>
            <div class="hub-card-meta">
              <span class="hub-meta-item">${getIcon("people", 11)} ${faculty}</span>
              <span class="hub-meta-item">${getIcon("sparkles", 10)} ${spec}</span>
              ${posted ? `<span class="hub-meta-item">${getIcon("clock", 10)} ${posted}</span>` : ""}
            </div>
          </div>

          <div class="hub-card-footer">
            <a class="hub-download-btn" href="${href}" download="${fileName}" title="Download ${fileName}">
              ${getIcon("download", 13)}
              <span>Download Resource</span>
            </a>
          </div>
        </article>
      `;
    }).join("");
  }

  function renderFilteredStudentNotes() {
    const container = document.getElementById("student-notes-container");
    if (!container) return;
    const notes = filteredStudentNotes();
    container.innerHTML = renderNotesGridContent(notes);

    const countEl = document.querySelector(".hub-results-count");
    if (countEl) {
      countEl.innerHTML = `Showing <strong>${notes.length}</strong> of <strong>${(state.notes || []).length}</strong> resources`;
    }

    const resetBtn = document.getElementById("btn-reset-notes-filter");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        state.notesSearch = "";
        state.notesSubjectFilter = "All";
        const searchInput = document.getElementById("notes-search-input");
        if (searchInput) searchInput.value = "";
        renderNotesSubjectPills();
        renderFilteredStudentNotes();
      });
    }
  }

  function bindNotesFilterBar() {
    ensureNotesFilterStyles();
    const search = document.getElementById("notes-search-input");
    const pills = document.getElementById("notes-subject-filters");
    const clearBtn = document.getElementById("btn-clear-notes-search");

    if (search) {
      search.value = state.notesSearch || "";
      search.addEventListener("input", () => {
        state.notesSearch = search.value;
        renderFilteredStudentNotes();
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        state.notesSearch = "";
        if (search) search.value = "";
        renderFilteredStudentNotes();
      });
    }
    if (pills) {
      pills.addEventListener("click", (event) => {
        const btn = event.target.closest(".notes-subject-pill");
        if (!btn) return;
        state.notesSubjectFilter = btn.dataset.subject || "All";
        pills.querySelectorAll(".notes-subject-pill").forEach((pill) => {
          pill.classList.toggle("active", pill === btn);
        });
        renderFilteredStudentNotes();
      });
    }
  }

  async function loadStudentNotes(subject, specialization) {
    const container = document.getElementById("student-notes-container");
    if (!container) return;

    ensureNotesFilterStyles();
    if (subject) state.notesSubjectFilter = subject;

    const params = new URLSearchParams();
    if (specialization) params.set("specialization", specialization);
    const query = params.toString();

    try {
      const res = await fetch(query ? `/api/notes?${query}` : "/api/notes", {
        headers: api.headers()
      });
      if (!res.ok) throw new Error("Could not load lecture notes");
      state.notes = await res.json();
      renderNotesSubjectPills();
      renderFilteredStudentNotes();
    } catch (e) {
      if (container) {
        container.innerHTML = `<p style="font-size: 11px; color: #ff8b7b;">Could not load lecture notes.</p>`;
      }
      console.error(e);
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
        { label: "Attendance Analytics", icon: "attendance" },
        { label: "Assignments & Sessions", icon: "assignment" },
        { label: "Class Threads", icon: "threads" },
        { label: "Knowledge Hub", id: "knowledge-hub", icon: "hub" },
        { label: "People", icon: "people" }
      ]
      : [
        { label: "Dashboard", icon: "dashboard" },
        { label: "My Timetable", icon: "calendar" },
        { label: "Assignments", icon: "assignment" },
        { label: "Class Threads", icon: "threads" },
        { label: "Knowledge Hub", id: "knowledge-hub", icon: "hub" },
        { label: "People", icon: "people" }
      ];

    // Ensure valid currentTab for role
    const validTabs = ["Dashboard", "My Timetable", "Timetable & Attendance", "Attendance Analytics", "Assignments", "Assignments & Sessions", "Class Threads", "People", "Knowledge Hub", "knowledge-hub"];
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
          (item) => {
            const tabKey = item.id || item.label;
            const isActive =
              state.currentTab === item.label ||
              state.currentTab === tabKey ||
              (item.label === "Knowledge Hub" && (state.currentTab === "knowledge-hub" || state.currentTab === "Knowledge Hub"));
            return `
                    <button class="nav-item ${isActive ? "active" : ""}" data-tab="${tabKey}">
                      ${getIcon(item.icon, 16)}
                      <span>${item.label}</span>
                    </button>
                  `;
          }
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
                <strong>${state.currentTab === "knowledge-hub" || state.currentTab === "Knowledge Hub" ? "Knowledge Hub" : state.currentTab}</strong>
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
      case "Attendance Analytics":
        return renderAttendanceAnalytics();
      case "People":
        return renderPeopleView();
      case "Class Threads":
        return renderThreadsView();
      case "Knowledge Hub":
      case "knowledge-hub":
      case "Knowledge-Hub":
        return renderKnowledgeHub();
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
          <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 8px;">
            ${renderFacultyClassesConductedPill()}
            <div class="date-note">
              Coordinator mode <b>active</b>
            </div>
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
                  <span>Total classes conducted</span>
                  <strong>${String(
                    (state.facultyAttendance && state.facultyAttendance.total_classes_conducted != null)
                      ? state.facultyAttendance.total_classes_conducted
                      : state.classes.length
                  ).padStart(2, "0")}</strong>
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
                    <strong>Upload assignment </strong>
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

        <section class="panel faculty-overview" style="margin-top: 18px;">
          <div class="panel-head">
            <div class="panel-title">${getIcon("fileText", 15)} Lecture Notes</div>
            <span class="panel-meta">Notify enrolled students on upload</span>
          </div>
          <form id="upload-notes-form" class="management-body" style="display: grid; gap: 10px;">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <div>
                <label class="field-label" for="notes-title">Title</label>
                <input id="notes-title" name="title" class="field-input" required placeholder="e.g. Graph Traversal lecture notes" />
              </div>
              <div>
                <label class="field-label" for="note-subject">Subject</label>
                <select id="note-subject" name="subject" class="field-input" required>
                  ${facultyNoteSubjects().map((subject) => `
                    <option value="${subject}" ${subject === "Data Structures" ? "selected" : ""}>${subject}</option>
                  `).join("")}
                </select>
              </div>
            </div>
            <div>
              <label class="field-label" for="notes-specialization">Specialization <span style="opacity: 0.5;">(optional)</span></label>
              <input id="notes-specialization" name="specialization" class="field-input" placeholder="e.g. CS-2A or AI" />
            </div>
            <div>
              <label class="field-label" for="notes-file">File attachment</label>
              <input id="notes-file" name="file" class="field-input" type="file" required />
            </div>
            <div style="background: rgba(167, 139, 250, 0.1); border: 1px solid rgba(167, 139, 250, 0.2); border-radius: 8px; padding: 10px 12px; font-size: 10px; color: #cfc2ff; display: flex; align-items: center; gap: 8px;">
              ${getIcon("shield", 14)}
              <span>Students enrolled in this subject across batches will receive an email when notes are posted.</span>
            </div>
            <div style="display: flex; justify-content: flex-end;">
              <button type="submit" class="primary-btn" ${state.loading ? "disabled" : ""}>
                ${state.loading ? `<span class="spinner"></span>` : `${getIcon("upload", 13)} Upload notes & notify`}
              </button>
            </div>
          </form>
        </section>
      </div>
    `;
  }

  function attendanceBarColors(percentage, status) {
    const pct = Number(percentage) || 0;
    const band = status || (pct >= 75 ? "Eligible" : pct >= 50 ? "Warning" : "Shortage");
    if (band === "Eligible" || pct >= 75) {
      return { fill: "#48c78e", track: "rgba(72,199,142,0.18)", text: "#48c78e", label: "Eligible"};
    }
    if (band === "Warning" || pct >= 50) {
      return { fill: "#ffc107", track: "rgba(255,193,7,0.16)", text: "#ffc107", label: "Warning" };
    }
    return { fill: "#ff8b7b", track: "rgba(255,139,123,0.16)", text: "#ff8b7b", label: "Shortage" };
  }

  function facultyAttendanceTotals() {
    const data = state.facultyAttendance;
    const conducted = data && data.total_classes_conducted != null
      ? Number(data.total_classes_conducted)
      : (state.classes || []).length;
    const avg = data && data.overall_average_percentage != null
      ? Number(data.overall_average_percentage)
      : null;
    return { conducted, avg, subjectCount: (data && data.subject_count) || 0 };
  }

  function renderFacultyClassesConductedPill() {
    const { conducted, avg } = facultyAttendanceTotals();
    const colors = avg == null
      ? { fill: "#a78bfa", track: "rgba(167,139,250,0.14)", text: "#cfc2ff" }
      : attendanceBarColors(avg);
    return `
      <div id="faculty-classes-conducted-pill" style="display: inline-flex; align-items: center; gap: 8px; padding: 7px 12px 7px 8px; border-radius: 999px; background: ${colors.track}; border: 1px solid ${colors.fill}55; box-shadow: 0 0 0 3px ${colors.track};">
        <span style="width: 22px; height: 22px; border-radius: 50%; background: ${colors.fill}22; color: ${colors.text}; display: inline-flex; align-items: center; justify-content: center;">
          ${getIcon("calendar", 12)}
        </span>
        <span style="font-size: 11px; font-weight: 650; color: #f4f1ff; letter-spacing: 0.01em; white-space: nowrap;">
          Total Classes Conducted: <strong style="color: ${colors.text};">${conducted}</strong>
          ${avg != null ? `<span style="color: #8e87a2; font-weight: 600;"> · Avg ${avg}%</span>` : ""}
        </span>
      </div>
    `;
  }

  function renderOverallAttendancePill() {
    const data = state.studentAttendance;
    const pct = data && data.overall_percentage != null ? Number(data.overall_percentage) : null;
    const colors = pct == null
      ? { fill: "#a78bfa", track: "rgba(167,139,250,0.14)", text: "#cfc2ff", label: "Loading" }
      : attendanceBarColors(pct);
    const label = colors.label;
    const pctText = pct == null ? "—" : `${pct}%`;
    return `
      <div id="overall-attendance-pill" style="display: inline-flex; align-items: center; gap: 8px; padding: 7px 12px 7px 8px; border-radius: 999px; background: ${colors.track}; border: 1px solid ${colors.fill}55; box-shadow: 0 0 0 3px ${colors.track};">
        <span style="width: 22px; height: 22px; border-radius: 50%; background: ${colors.fill}22; color: ${colors.text}; display: inline-flex; align-items: center; justify-content: center;">
          ${getIcon("attendance", 12)}
        </span>
        <span style="font-size: 11px; font-weight: 650; color: #f4f1ff; letter-spacing: 0.01em; white-space: nowrap;">
          Overall Attendance: <strong style="color: ${colors.text};">${pctText}</strong>
          <span style="color: #8e87a2; font-weight: 600;"> · ${label}</span>
        </span>
      </div>
    `;
  }

  function renderStudentAttendanceCard() {
    const data = state.studentAttendance;
    const subjects = (data && data.subjects) || [];
    const overall = data && data.overall_percentage != null ? data.overall_percentage : null;
    const overallColors = attendanceBarColors(overall);

    return `
      <section class="panel faculty-overview" style="margin-top: 18px;" id="student-attendance-card">
        <div class="panel-head">
          <div class="panel-title">${getIcon("attendance", 15)} 📊 My Subject-Wise Attendance</div>
          <span class="panel-meta">${
            overall != null
              ? `Overall ${overall}% · ${data.total_attended || 0}/${data.total_classes || 0} classes`
              : "Live from OpenClass"
          }</span>
        </div>
        ${overall != null ? `
          <div style="padding: 0 20px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
              <span style="font-size: 11px; color: #8e87a2;">Overall eligibility</span>
              <span style="font-size: 12px; font-weight: 800; color: ${overallColors.text};">${overall}%</span>
            </div>
            <div style="height: 8px; border-radius: 999px; background: ${overallColors.track}; overflow: hidden;">
              <div style="height: 100%; width: ${Math.min(overall, 100)}%; background: ${overallColors.fill}; border-radius: 999px;"></div>
            </div>
          </div>
        ` : ""}
        <div style="padding: 4px 20px 18px; display: grid; gap: 12px;">
          ${!data ? `<p style="font-size: 11px; color: #8e87a2;">Loading live attendance…</p>` : ""}
          ${data && !subjects.length ? `<p style="font-size: 11px; color: #8e87a2;">No subject attendance records yet. Join a Google Meet session to check in.</p>` : ""}
          ${subjects.map((item) => {
            const pct = Number(item.percentage) || 0;
            const colors = attendanceBarColors(pct, item.status);
            const attended = item.attended != null ? item.attended : 0;
            const total = item.total != null ? item.total : 0;
            return `
              <div style="padding: 12px 14px; border-radius: 12px; background: rgba(255,255,255,0.02); border: 1px solid rgba(147,133,204,0.14);">
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px;">
                  <strong style="font-size: 13px; color: #f4f1ff;">${item.subject || "Course"}</strong>
                  <span style="font-size: 9px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: ${colors.text}; background: ${colors.track}; border: 1px solid ${colors.fill}55; border-radius: 999px; padding: 3px 8px;">${colors.label}</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
                  <span style="font-size: 11px; color: #8e87a2;">${attended}/${total} classes</span>
                  <span style="font-size: 16px; font-weight: 800; color: ${colors.text};">${pct}%</span>
                </div>
                <div style="height: 9px; border-radius: 999px; background: ${colors.track}; overflow: hidden;">
                  <div style="height: 100%; width: ${Math.min(Math.max(pct, 0), 100)}%; background: ${colors.fill}; border-radius: 999px; transition: width 0.25s ease;"></div>
                </div>
              </div>
            `;
          }).join("")}
        </div>
      </section>
    `;
  }

  function renderAttendanceAnalytics() {
    const data = state.facultyAttendance;
    const subjects = (data && data.subjects) || [];
    const { conducted, avg, subjectCount } = facultyAttendanceTotals();
    const generated = data && data.generated_at ? formatDeadline(data.generated_at) : "Live";
    const overallColors = attendanceBarColors(avg == null ? 0 : avg);

    return `
      <div class="faculty-view attendance-analytics-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">Faculty Analytics · Institutional Report</div>
            <h1 class="hero-title">Attendance Analytics.</h1>
            <p class="hero-copy">Subject-wise lecture volume and average student attendance for academic review and higher-management reporting.</p>
          </div>
          <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 8px;">
            ${renderFacultyClassesConductedPill()}
            <div class="date-note">Generated <b>${generated}</b></div>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px;">
          <div class="panel" style="padding: 16px 18px;">
            <div style="font-size: 10px; color: #8e87a2; text-transform: uppercase; letter-spacing: 0.08em;">Total Classes Conducted</div>
            <div style="font-size: 28px; font-weight: 800; color: #f4f1ff; margin-top: 6px;">${conducted}</div>
            <div style="font-size: 11px; color: #8e87a2; margin-top: 4px;">Across ${subjectCount || subjects.length} subject${(subjectCount || subjects.length) === 1 ? "" : "s"}</div>
          </div>
          <div class="panel" style="padding: 16px 18px;">
            <div style="font-size: 10px; color: #8e87a2; text-transform: uppercase; letter-spacing: 0.08em;">Overall Average Attendance</div>
            <div style="font-size: 28px; font-weight: 800; color: ${overallColors.text}; margin-top: 6px;">${avg != null ? avg + "%" : "—"}</div>
            <div style="height: 8px; border-radius: 999px; background: ${overallColors.track}; overflow: hidden; margin-top: 10px;">
              <div style="height: 100%; width: ${Math.min(Math.max(avg || 0, 0), 100)}%; background: ${overallColors.fill}; border-radius: 999px;"></div>
            </div>
          </div>
          <div class="panel" style="padding: 16px 18px;">
            <div style="font-size: 10px; color: #8e87a2; text-transform: uppercase; letter-spacing: 0.08em;">Reporting Standard</div>
            <div style="font-size: 13px; font-weight: 700; color: #f4f1ff; margin-top: 8px;">≥75% Strong · ≥50% Watch · &lt;50% At Risk</div>
            <div style="font-size: 11px; color: #8e87a2; margin-top: 6px;">Present + Late counted toward attendance.</div>
          </div>
        </div>

        <section class="panel" style="padding: 0; overflow: hidden;">
          <div class="panel-head" style="padding: 16px 20px;">
            <div class="panel-title">${getIcon("attendance", 15)} Subject-wise lecture report</div>
            <button type="button" class="secondary-btn" id="btn-print-attendance-report" style="font-size: 11px;">
              ${getIcon("download", 12)} Print / Export view
            </button>
          </div>
          <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
              <thead>
                <tr style="text-align: left; color: #8e87a2; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; border-bottom: 1px solid rgba(147,133,204,0.18);">
                  <th style="padding: 10px 20px; font-weight: 700;">Subject</th>
                  <th style="padding: 10px 16px; font-weight: 700;">Batches</th>
                  <th style="padding: 10px 16px; font-weight: 700; text-align: right;">Lectures conducted</th>
                  <th style="padding: 10px 20px; font-weight: 700; min-width: 220px;">Average student attendance</th>
                </tr>
              </thead>
              <tbody>
                ${!data ? `<tr><td colspan="4" style="padding: 24px 20px; color: #8e87a2;">Loading analytics…</td></tr>` : ""}
                ${data && !subjects.length ? `<tr><td colspan="4" style="padding: 24px 20px; color: #8e87a2;">No class sessions found. Ingest a timetable or schedule lectures to populate this report.</td></tr>` : ""}
                ${subjects.map((row) => {
                  const pct = Number(row.average_attendance_percentage) || 0;
                  const colors = attendanceBarColors(pct, row.status === "Strong" ? "Eligible" : row.status === "Watch" ? "Warning" : "Shortage");
                  const batches = (row.batches || []).join(", ") || "—";
                  return `
                    <tr style="border-bottom: 1px solid rgba(147,133,204,0.1);">
                      <td style="padding: 14px 20px; color: #f4f1ff; font-weight: 700;">${row.subject}</td>
                      <td style="padding: 14px 16px; color: #b3aec5;">${batches}</td>
                      <td style="padding: 14px 16px; text-align: right; color: #f4f1ff; font-weight: 800; font-variant-numeric: tabular-nums;">${row.total_classes_conducted}</td>
                      <td style="padding: 14px 20px;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                          <div style="flex: 1; height: 8px; border-radius: 999px; background: ${colors.track}; overflow: hidden;">
                            <div style="height: 100%; width: ${Math.min(Math.max(pct, 0), 100)}%; background: ${colors.fill}; border-radius: 999px;"></div>
                          </div>
                          <strong style="min-width: 52px; text-align: right; color: ${colors.text};">${pct}%</strong>
                          <span style="font-size: 9px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: ${colors.text}; background: ${colors.track}; border-radius: 999px; padding: 3px 8px; white-space: nowrap;">${row.status || colors.label}</span>
                        </div>
                      </td>
                    </tr>
                  `;
                }).join("")}
              </tbody>
            </table>
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

    const allAssignments = state.assignments || [];
    const pendingAssignments = allAssignments.filter((a) => !a.has_submitted);

    return `
      <div class="student-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">Student Portal · Batch ${user.batch_id || "CS-2A"}</div>
            <h1 class="hero-title">Good morning, <span class="accent">${user.name || "Student"}.</span></h1>
            <p class="hero-copy">Your personalized learning space, arranged around lectures, submissions, and class notes.</p>
          </div>
          <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 8px;">
            ${renderOverallAttendancePill()}
            <div class="date-note">
              Synced via <b>Microsoft 365 OIDC</b>
            </div>
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
              <button class="muted-btn" data-action="open-knowledge-hub" data-tab="knowledge-hub">Explore ${getIcon("arrowRight", 12)}</button>
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

        <!-- Pending Assignments & Action Items Feed -->
        <section class="panel feed-panel" style="margin-top: 18px;">
          <div class="panel-head">
            <div class="panel-title">${getIcon("assignment", 15)} Pending Assignments & Action Items</div>
            <span class="panel-meta">${pendingAssignments.length} actionable item${pendingAssignments.length === 1 ? "" : "s"}</span>
          </div>
          <div class="pending-feed-list" style="padding: 6px 20px 16px;">
            ${pendingAssignments.length > 0 ? pendingAssignments.map((a) => {
      const isUrgent = a.hours_remaining && a.hours_remaining <= 24;
      return `
                <div class="assignment-row" style="display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 12px 0; border-bottom: 1px solid rgba(147, 133, 204, 0.12);">
                  <div style="display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1;">
                    <div class="assignment-mark" style="color: ${isUrgent ? "#ff8b7b" : "#a78bfa"}; background: ${isUrgent ? "rgba(255, 107, 107, 0.15)" : "rgba(167, 139, 250, 0.15)"}; flex-shrink: 0;">
                      ${getIcon(isUrgent ? "clock" : "assignment", 14)}
                    </div>
                    <div class="management-copy" style="min-width: 0; flex: 1;">
                      <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <strong style="color: #f4f1ff; font-size: 12px; font-weight: 700;">${a.title}</strong>
                        <span class="status-pill" style="font-size: 8px;">${a.subject || "Coursework"}</span>
                        ${isUrgent ? `<span class="deadline-badge deadline-urgent" style="font-size: 8px;">${getIcon("clock", 10)} Due in ${Math.round(a.hours_remaining)}h</span>` : ""}
                      </div>
                      <span style="font-size: 10px; color: #8e87a2; margin-top: 3px; display: block;">
                        <strong>Deadline:</strong> ${formatDeadline(a.deadline)} · Faculty: ${a.faculty_name || "Course Lead"} · Batch: ${a.batch_id || user.batch_id || "CS-2A"}
                      </span>
                    </div>
                  </div>
                  <div style="flex-shrink: 0;">
                    <button class="mini-btn primary" data-action="submit-assignment" data-id="${a.id}">
                      ${getIcon("upload", 12)} Submit Work
                    </button>
                  </div>
                </div>
              `;
    }).join("") : `
              <div style="padding: 28px 16px; text-align: center; color: #8e87a2;">
                <div style="display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; background: rgba(72, 199, 142, 0.12); color: #48c78e; margin-bottom: 8px;">
                  ${getIcon("check", 18)}
                </div>
                <div style="color: #f4f1ff; font-weight: 700; font-size: 12px;">All Caught Up!</div>
                <p style="font-size: 11px; margin-top: 4px; color: #8e87a2;">
                  ${allAssignments.length > 0 ? "You have submitted all active assignments for your batch." : `No active assignments posted for batch ${user.batch_id || "CS-2A"} right now.`}
                </p>
              </div>
            `}
          </div>
        </section>

        ${renderStudentAttendanceCard()}
      </div>
    `;
  }

  // --- 4b. Dedicated Course Knowledge Hub & Repository ---
  function renderKnowledgeHub() {
    const totalCount = (state.notes || []).length;
    const filtered = filteredStudentNotes();

    return `
      <div class="knowledge-hub-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">Course Repository · Academic Library</div>
            <h1 class="hero-title">Knowledge Hub & Resources.</h1>
            <p class="hero-copy">Dedicated course repository featuring downloadable lecture notes, presentation decks, reading packets, and syllabus resources across all your subjects.</p>
          </div>
          <div class="date-note">
            Repository: <b>${totalCount} document${totalCount === 1 ? "" : "s"}</b>
          </div>
        </div>

        <section class="panel hub-filter-panel" style="margin-bottom: 20px; padding: 18px 20px;">
          <div class="notes-filter-bar" style="margin: 0; padding: 0; background: transparent; border: 0;">
            <div class="notes-search-wrap" style="background: rgba(18, 17, 30, 0.7); border: 1px solid rgba(147, 133, 204, 0.2);">
              ${getIcon("search", 15)}
              <input
                id="notes-search-input"
                type="search"
                placeholder="Search lecture notes, slides, or topics (e.g. Graph, DCF, Investments)…"
                autocomplete="off"
                value="${state.notesSearch || ""}"
              />
              ${state.notesSearch ? `
                <button type="button" id="btn-clear-notes-search" style="background: transparent; border: 0; color: #8e87a2; cursor: pointer; padding: 2px;">
                  ${getIcon("close", 12)}
                </button>
              ` : ""}
            </div>

            <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-top: 10px;">
              <div id="notes-subject-filters" role="tablist" aria-label="Filter notes by subject" style="flex: 1; min-width: 0;">
                ${notesSubjectOptions().map((subject) => {
      const isActive = subject.toLowerCase() === String(state.notesSubjectFilter || "All").toLowerCase();
      return `<button type="button" class="notes-subject-pill${isActive ? " active" : ""}" data-subject="${subject}">${subject}</button>`;
    }).join("")}
              </div>

              <div class="hub-results-count" style="font-size: 11px; color: #8e87a2; font-family: var(--app-font-mono); white-space: nowrap;">
                Showing <strong>${filtered.length}</strong> of <strong>${totalCount}</strong> resources
              </div>
            </div>
          </div>
        </section>

        <!-- Responsive Grid of Downloadable Lecture Notes, Slides, and Resources -->
        <div id="student-notes-container" class="knowledge-hub-grid">
          ${renderNotesGridContent(filtered)}
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
                ${getIcon("plus", 14)} Create Assignment 
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
            <div class="panel" style="padding: 0; overflow: hidden; border-radius: 14px;">
              <!-- Session header row -->
              <div style="padding: 16px 20px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;">
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

                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                  <button class="meet-btn ${isFaculty ? "host-mode" : ""}" data-action="launch-meet" data-id="${c.id}">
                    ${getIcon("video", 14)} ${isFaculty ? "Launch Google Meet (Host)" : "Join Google Meet"}
                  </button>
                  ${isFaculty ? `
                    <button class="secondary-btn" style="font-size: 10px; padding: 7px 12px; gap: 6px; display: flex; align-items: center;" data-action="view-attendance" data-id="${c.id}">
                      ${getIcon("attendance", 13)} Attendance & Logs
                    </button>
                  ` : ""}
                </div>
              </div>

              ${isFaculty ? `
              <!-- Inline attendance summary bar for faculty -->
              <div style="border-top: 1px solid rgba(147,133,204,0.12); padding: 10px 20px; display: flex; align-items: center; gap: 16px; background: rgba(167,139,250,0.04);">
                <span style="font-size: 10px; color: #8e87a2; display: flex; align-items: center; gap: 5px;">
                  ${getIcon("people", 11)}
                  <span>Batch ${c.batch || "CS-2A"}</span>
                </span>
                <span style="font-size: 10px; color: #8e87a2;">·</span>
                <span style="font-size: 10px; color: #61d7da; display: flex; align-items: center; gap: 5px;">
                  ${getIcon("attendance", 11)}
                  Click <strong style="color: #a78bfa; margin: 0 2px;">Attendance & Logs</strong> to view or finalize the smart roster
                </span>
                <div style="margin-left: auto;">
                  <a href="/api/attendance/session/${c.id}/export" class="mini-btn" download style="font-size: 9px; padding: 5px 10px; display: inline-flex; align-items: center; gap: 5px;">
                    ${getIcon("download", 11)} Download CSV
                  </a>
                </div>
              </div>
              ` : ""}
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

  function threadScopeMeta(thread) {
    const scope = String(thread.scope_type || "public").toLowerCase();
    if (scope === "batch") {
      return {
        key: "batch",
        label: "Course batch",
        detail: [thread.batch_id, thread.subject].filter(Boolean).join(" · ") || "Batch thread",
        color: "#61d7da"
      };
    }
    if (scope === "private") {
      return {
        key: "private",
        label: "Private DM",
        detail: thread.recipient_faculty_name ? `To ${thread.recipient_faculty_name}` : "Faculty DM",
        color: "#a78bfa"
      };
    }
    return { key: "public", label: "Public", detail: "Open discussion", color: "#48c78e" };
  }

  function visibleThreads() {
    const filter = state.threadScopeFilter || "all";
    return (state.threads || []).filter((t) => {
      if (filter === "all") return true;
      return String(t.scope_type || "public").toLowerCase() === filter;
    });
  }

  // --- 8. Class Threads View ---
  function renderThreadsView() {
    ensureNotesFilterStyles();
    const isFaculty = state.role === "faculty";
    const threads = visibleThreads();
    const active = state.activeThread;
    const filters = [
      { id: "all", label: "All" },
      { id: "public", label: "Public" },
      { id: "batch", label: "Course batch" },
      { id: "private", label: "Private faculty DMs" }
    ];

    return `
      <div class="threads-view">
        <div class="hero-row">
          <div>
            <div class="eyebrow">Academic Discussion · Scoped Messaging</div>
            <h1 class="hero-title">Class Threads.</h1>
            <p class="hero-copy">${isFaculty
              ? "Post public discussions, batch announcements (email the enrolled class), or reply to private student DMs."
              : "Join public discussions, your batch course threads, or message faculty privately — DMs email the professor."}</p>
          </div>
          <button class="primary-btn" id="btn-open-thread-modal">
            ${getIcon("plus", 14)} ${isFaculty ? "New thread / announcement" : "New thread or faculty DM"}
          </button>
        </div>

        <div id="thread-scope-filters" style="display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 16px;">
          ${filters.map((f) => `
            <button type="button" class="notes-subject-pill${state.threadScopeFilter === f.id ? " active" : ""}" data-thread-scope="${f.id}">${f.label}</button>
          `).join("")}
        </div>

        <div style="display: grid; grid-template-columns: ${active ? "minmax(280px, 1fr) minmax(320px, 1.1fr)" : "1fr"}; gap: 14px; align-items: start;">
          <div style="display: grid; gap: 10px;">
            ${threads.length ? threads.map((t) => {
              const meta = threadScopeMeta(t);
              const author = t.author_name || t.by || "Member";
              const initials = String(author).split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase();
              const selected = active && Number(active.id) === Number(t.id);
              const replies = t.message_count != null ? t.message_count : (t.count || 0);
              return `
                <button type="button" class="panel" data-action="open-thread" data-id="${t.id}" style="padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; text-align: left; cursor: pointer; width: 100%; font-family: inherit; border: 1px solid ${selected ? "rgba(167,139,250,0.45)" : "rgba(147,133,204,0.14)"}; background: ${selected ? "rgba(167,139,250,0.08)" : "rgba(255,255,255,0.02)"};">
                  <div style="display: flex; align-items: center; gap: 12px; min-width: 0;">
                    <div class="avatar" style="width: 28px; height: 28px; font-size: 10px;">${initials}</div>
                    <div style="min-width: 0;">
                      <strong style="color: #f4f1ff; font-size: 12px; display: block;">${t.title}</strong>
                      <span style="font-size: 10px; color: #8e87a2;">${author} · ${meta.detail}</span>
                    </div>
                  </div>
                  <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
                    <span class="status-pill" style="border-color: ${meta.color}55; color: ${meta.color};">${meta.label}</span>
                    <span class="status-pill">${replies} ${replies === 1 ? "reply" : "replies"}</span>
                  </div>
                </button>
              `;
            }).join("") : `<p style="font-size: 12px; color: #8e87a2;">No threads in this scope yet. Start one to open the conversation.</p>`}
          </div>

          ${active ? `
            <section class="panel" style="padding: 0; overflow: hidden;">
              <div class="panel-head" style="padding: 14px 16px;">
                <div>
                  <div class="panel-title">${active.title}</div>
                  <span class="panel-meta">${threadScopeMeta(active).label}${active.batch_id ? " · " + active.batch_id : ""}${active.subject ? " · " + active.subject : ""}${active.recipient_faculty_name ? " · " + active.recipient_faculty_name : ""}</span>
                </div>
                <button type="button" class="muted-btn" id="btn-close-active-thread">Close</button>
              </div>
              ${active.body ? `<p style="padding: 0 16px 12px; font-size: 12px; color: #cfc2ff; line-height: 1.45;">${active.body}</p>` : ""}
              <div style="padding: 0 16px 12px; display: grid; gap: 8px; max-height: 360px; overflow-y: auto;">
                ${(active.messages || []).length ? (active.messages || []).map((m) => `
                  <div style="padding: 10px 12px; border-radius: 10px; background: rgba(255,255,255,0.03); border: 1px solid rgba(147,133,204,0.12);">
                    <div style="display: flex; justify-content: space-between; gap: 8px;">
                      <strong style="font-size: 11px; color: #f4f1ff;">${m.author_name || "Member"}</strong>
                      <span style="font-size: 9px; color: #8e87a2;">${m.author_role || ""} · ${m.created_at ? formatDeadline(m.created_at) : ""}</span>
                    </div>
                    <p style="margin: 6px 0 0; font-size: 12px; color: #d8d3ea; line-height: 1.45;">${m.body}</p>
                  </div>
                `).join("") : `<p style="font-size: 11px; color: #8e87a2;">No replies yet. Be the first to continue the thread.</p>`}
              </div>
              <form id="form-thread-reply" style="padding: 12px 16px 16px; border-top: 1px solid rgba(147,133,204,0.12); display: grid; gap: 8px;">
                <textarea id="thread-reply-input" class="field-input" style="height: 64px; resize: none;" placeholder="${isFaculty && String(active.scope_type).toLowerCase() === "batch" ? "Post a batch announcement (students are emailed)…" : "Write a reply…"}" required></textarea>
                <div style="display: flex; justify-content: flex-end;">
                  <button type="submit" class="primary-btn">${getIcon("threads", 13)} Send</button>
                </div>
              </form>
            </section>
          ` : ""}
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
      case "attendance_roster":
        return renderAttendanceRosterModal();
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
              <h2>Upload assignment </h2>
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
                <select id="assign-subject" class="field-input" required>
                  <option value="" disabled selected>Select course subject...</option>
                  ${getClassesSubjects().map((subject) => `
                    <option value="${subject}">${subject}</option>
                  `).join("")}
                </select>
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
      } catch { }
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
    const isFaculty = state.role === "faculty";
    const scope = state.threadComposeScope || "public";
    const subjects = facultyNoteSubjects();
    const batches = (state.batches || []).length
      ? state.batches
      : [{ name: "CS-2A" }, { name: "CS-1B" }];
    const faculty = state.people || [];
    const studentBatch = (state.user && state.user.batch_id) || "CS-2A";

    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div>
              <h2>${isFaculty ? "Start a thread or announcement" : "Start a thread or faculty DM"}</h2>
              <p>Choose who can see this conversation. Public threads stay silent on email; batch announcements and private DMs notify the right inbox.</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <form id="form-start-thread">
            <label class="field-label">Scope</label>
            <div id="thread-scope-choices" style="display: grid; gap: 8px; margin-bottom: 12px;">
              <label class="field-input" style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                <input type="radio" name="thread_scope" value="public" ${scope === "public" ? "checked" : ""} />
                Public discussion — visible to everyone, no email blast
              </label>
              <label class="field-input" style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                <input type="radio" name="thread_scope" value="batch" ${scope === "batch" ? "checked" : ""} />
                Course batch — ${isFaculty ? "emails enrolled students when you post" : "visible to your batch and subject"}
              </label>
              <label class="field-input" style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                <input type="radio" name="thread_scope" value="private" ${scope === "private" ? "checked" : ""} />
                Private faculty DM — emails the professor
              </label>
            </div>

            <label class="field-label" for="thread-title-input">${scope === "private" ? "Message title" : "Thread title"}</label>
            <input id="thread-title-input" class="field-input" required placeholder="${scope === "private" ? "e.g. Office hours question" : "What are we exploring?"}" />

            <label class="field-label" for="thread-body-input">Opening message</label>
            <textarea id="thread-body-input" class="field-input" style="height: 72px; resize: none;" placeholder="Write the first post…"></textarea>

            <div id="thread-batch-fields" style="display: ${scope === "batch" ? "grid" : "none"}; gap: 10px;">
              <div>
                <label class="field-label" for="thread-batch-input">Batch</label>
                ${isFaculty ? `
                  <select id="thread-batch-input" class="field-input">
                    ${batches.map((b) => `<option value="${b.name}">${b.name}${b.subject ? " · " + b.subject : ""}</option>`).join("")}
                  </select>
                ` : `
                  <input id="thread-batch-input" class="field-input" value="${studentBatch}" readonly />
                `}
              </div>
              <div>
                <label class="field-label" for="thread-subject-input">Subject</label>
                <select id="thread-subject-input" class="field-input">
                  ${subjects.map((s) => `<option value="${s}">${s}</option>`).join("")}
                </select>
              </div>
            </div>

            <div id="thread-faculty-fields" style="display: ${scope === "private" ? "grid" : "none"}; gap: 10px;">
              <label class="field-label" for="thread-faculty-input">Faculty recipient</label>
              <select id="thread-faculty-input" class="field-input">
                ${faculty.map((f) => `<option value="${f.id}">${f.full_name || f.name}${f.email ? " · " + f.email : ""}</option>`).join("")}
              </select>
            </div>

            <div class="modal-actions">
              <button type="button" class="secondary-btn" id="btn-cancel-modal">Cancel</button>
              <button type="submit" class="primary-btn">${scope === "private" ? "Send private message" : "Start thread"}</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  // --- Attendance Smart Roster Modal ---
  function renderAttendanceRosterModal() {
    const roster = state.attendanceRoster;
    if (!roster) {
      return `
        <div class="modal-backdrop" id="modal-backdrop">
          <div class="modal" onclick="event.stopPropagation()">
            <div class="modal-head">
              <div><h2>Attendance Roster</h2><p>Loading...</p></div>
              <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
            </div>
            <div style="padding: 32px; text-align: center;"><span class="spinner"></span></div>
          </div>
        </div>
      `;
    }

    const { class_id, subject, batch, class_date, start_time, faculty_name, total_enrolled, present_count, roster: rows } = roster;
    const absent_count = total_enrolled - present_count;
    const pct = total_enrolled > 0 ? Math.round((present_count / total_enrolled) * 100) : 0;

    const statusColor = (s) => {
      if (s === "Present") return { bg: "rgba(72,199,142,0.15)", text: "#48c78e", border: "rgba(72,199,142,0.3)" };
      if (s === "Late") return { bg: "rgba(255,193,7,0.15)", text: "#ffc107", border: "rgba(255,193,7,0.3)" };
      return { bg: "rgba(255,107,107,0.12)", text: "#ff8b7b", border: "rgba(255,107,107,0.25)" };
    };

    const cycleStatus = (current) => {
      if (current === "Present") return "Late";
      if (current === "Late") return "Absent";
      return "Present";
    };

    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal" style="width: min(680px, 96vw); max-height: 90vh; display: flex; flex-direction: column;" onclick="event.stopPropagation()">
          <!-- Header -->
          <div class="modal-head" style="flex-shrink: 0;">
            <div>
              <h2 style="display: flex; align-items: center; gap: 8px;">${getIcon("attendance", 18)} Attendance & Logs</h2>
              <p>${subject} · Batch ${batch} · ${class_date || "Today"} ${start_time || ""} · Faculty: ${faculty_name || "—"}</p>
            </div>
            <button class="close-btn" id="btn-close-modal">${getIcon("close", 16)}</button>
          </div>

          <!-- Stats Bar -->
          <div style="flex-shrink: 0; display: flex; gap: 12px; padding: 14px 20px; background: rgba(167,139,250,0.06); border-bottom: 1px solid rgba(147,133,204,0.14);">
            <div style="flex: 1; text-align: center;">
              <div style="font-size: 22px; font-weight: 800; color: #48c78e;">${present_count}</div>
              <div style="font-size: 9px; color: #8e87a2; text-transform: uppercase; letter-spacing: 0.08em;">Present</div>
            </div>
            <div style="flex: 1; text-align: center;">
              <div style="font-size: 22px; font-weight: 800; color: #ff8b7b;">${absent_count}</div>
              <div style="font-size: 9px; color: #8e87a2; text-transform: uppercase; letter-spacing: 0.08em;">Absent</div>
            </div>
            <div style="flex: 1; text-align: center;">
              <div style="font-size: 22px; font-weight: 800; color: #a78bfa;">${pct}%</div>
              <div style="font-size: 9px; color: #8e87a2; text-transform: uppercase; letter-spacing: 0.08em;">Attendance</div>
            </div>
            <div style="flex: 1; text-align: center;">
              <div style="font-size: 22px; font-weight: 800; color: #f4f1ff;">${total_enrolled}</div>
              <div style="font-size: 9px; color: #8e87a2; text-transform: uppercase; letter-spacing: 0.08em;">Enrolled</div>
            </div>
          </div>

          <!-- Instructions -->
          <div style="flex-shrink: 0; padding: 10px 20px; background: rgba(167,139,250,0.04); border-bottom: 1px solid rgba(147,133,204,0.1); font-size: 10px; color: #9d94bf; display: flex; align-items: center; gap: 7px;">
            ${getIcon("sparkles", 12)}
            <span>Click any status badge to toggle: <strong style="color:#48c78e">Present</strong> → <strong style="color:#ffc107">Late</strong> → <strong style="color:#ff8b7b">Absent</strong>. Auto-populated from student check-ins.</span>
          </div>

          <!-- Roster List -->
          <div id="attendance-roster-list" style="flex: 1; overflow-y: auto; padding: 12px 20px; display: grid; gap: 6px;">
            ${(rows || []).map((r, idx) => {
      const sc = statusColor(r.status);
      const initials = String(r.student_name || "").split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase();
      const ts = r.timestamp ? new Date(r.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : null;
      return `
                <div class="attendance-row" data-idx="${idx}" data-student-id="${r.student_id}" data-student-name="${r.student_name || ""}" data-batch-id="${r.batch_id || ""}" data-status="${r.status}" style="display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 10px; background: rgba(255,255,255,0.02); border: 1px solid rgba(147,133,204,0.12); transition: border-color 0.15s;">
                  <div style="width: 32px; height: 32px; border-radius: 50%; background: rgba(167,139,250,0.18); color: #a78bfa; font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">${initials}</div>
                  <div style="flex: 1; min-width: 0;">
                    <div style="font-size: 12px; font-weight: 700; color: #f4f1ff;">${r.student_name}</div>
                    <div style="font-size: 10px; color: #8e87a2;">ID: ${r.student_id} · Batch: ${r.batch_id || batch}${ts ? " · Checked in: " + ts : ""}</div>
                  </div>
                  <button type="button" class="attendance-status-toggle" data-idx="${idx}" style="cursor: pointer; font-size: 10px; font-weight: 700; padding: 5px 12px; border-radius: 6px; border: 1px solid ${sc.border}; background: ${sc.bg}; color: ${sc.text}; font-family: inherit; transition: all 0.15s;">
                    ${r.status}
                  </button>
                  ${r.verified_by_faculty ? `<span style="font-size: 9px; color: #a78bfa; opacity: 0.7;">${getIcon("check", 10)} Faculty</span>` : ""}
                </div>
              `;
    }).join("")}
          </div>

          <!-- Actions -->
          <div class="modal-actions" style="flex-shrink: 0; border-top: 1px solid rgba(147,133,204,0.14); padding-top: 14px;">
            <a href="/api/attendance/session/${class_id}/export" class="secondary-btn" download style="display: inline-flex; align-items: center; gap: 7px; text-decoration: none;">
              ${getIcon("download", 13)} Download CSV
            </a>
            <div style="margin-left: auto; display: flex; gap: 8px;">
              <button type="button" class="secondary-btn" id="btn-cancel-modal">Close</button>
              <button type="button" class="primary-btn" id="btn-save-attendance" ${state.loading ? "disabled" : ""}>
                ${state.loading ? `<span class="spinner"></span>` : `${getIcon("check", 13)} Save & Finalize Roster`}
              </button>
            </div>
          </div>
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
    if (btnOpenThread) {
      btnOpenThread.addEventListener("click", () => {
        state.threadComposeScope = "public";
        state.activeModal = "thread";
        render();
      });
    }

    const threadScopeFilters = document.getElementById("thread-scope-filters");
    if (threadScopeFilters) {
      threadScopeFilters.addEventListener("click", (event) => {
        const btn = event.target.closest("[data-thread-scope]");
        if (!btn) return;
        state.threadScopeFilter = btn.dataset.threadScope || "all";
        render();
      });
    }

    document.querySelectorAll('[data-action="open-thread"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        api.loadThread(Number(btn.dataset.id));
      });
    });

    const closeThread = document.getElementById("btn-close-active-thread");
    if (closeThread) {
      closeThread.addEventListener("click", () => {
        state.activeThread = null;
        render();
      });
    }

    const replyForm = document.getElementById("form-thread-reply");
    if (replyForm) {
      replyForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const input = document.getElementById("thread-reply-input");
        const body = input && input.value.trim();
        if (body && state.activeThread) {
          api.postThreadMessage(state.activeThread.id, body);
        }
      });
    }

    const btnPrintAttendance = document.getElementById("btn-print-attendance-report");
    if (btnPrintAttendance) {
      btnPrintAttendance.addEventListener("click", () => window.print());
    }

    const uploadNotesForm = document.getElementById("upload-notes-form");
    if (uploadNotesForm) {
      uploadNotesForm.addEventListener("submit", handleUploadNotes);
    }

    if (document.getElementById("student-notes-container")) {
      bindNotesFilterBar();
      if (!state.notes || state.notes.length === 0) {
        loadStudentNotes();
      } else {
        renderFilteredStudentNotes();
      }
    }

    document.querySelectorAll('[data-action="open-knowledge-hub"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        state.currentTab = "knowledge-hub";
        render();
      });
    });

    // Meet launch buttons
    document.querySelectorAll('[data-action="launch-meet"]').forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        await api.launchMeetWithCheckIn(id);
      });
    });

    // Attendance roster view (faculty timetable)
    document.querySelectorAll('[data-action="view-attendance"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = Number(btn.dataset.id);
        api.loadSessionRoster(id);
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
      formThread.querySelectorAll('input[name="thread_scope"]').forEach((radio) => {
        radio.addEventListener("change", () => {
          state.threadComposeScope = radio.value;
          const batchFields = document.getElementById("thread-batch-fields");
          const facultyFields = document.getElementById("thread-faculty-fields");
          if (batchFields) batchFields.style.display = radio.value === "batch" ? "grid" : "none";
          if (facultyFields) facultyFields.style.display = radio.value === "private" ? "grid" : "none";
        });
      });
      formThread.addEventListener("submit", (e) => {
        e.preventDefault();
        const title = document.getElementById("thread-title-input").value.trim();
        const body = (document.getElementById("thread-body-input") || {}).value || "";
        const scopeEl = formThread.querySelector('input[name="thread_scope"]:checked');
        const scope_type = (scopeEl && scopeEl.value) || "public";
        if (!title) return;
        const payload = { title, body: body.trim(), scope_type };
        if (scope_type === "batch") {
          payload.batch_id = (document.getElementById("thread-batch-input") || {}).value;
          payload.subject = (document.getElementById("thread-subject-input") || {}).value;
        }
        if (scope_type === "private") {
          const facVal = (document.getElementById("thread-faculty-input") || {}).value;
          payload.recipient_faculty_id = facVal ? Number(facVal) : null;
        }
        api.createThread(payload);
      });
    }

    // Attendance Roster Modal — toggle & save
    const rosterList = document.getElementById("attendance-roster-list");
    if (rosterList && state.attendanceRoster) {
      // Maintain a local mutable copy of roster statuses for toggling
      const localRoster = (state.attendanceRoster.roster || []).map(r => ({ ...r }));

      rosterList.addEventListener("click", (e) => {
        const toggleBtn = e.target.closest(".attendance-status-toggle");
        if (!toggleBtn) return;
        const idx = Number(toggleBtn.dataset.idx);
        if (isNaN(idx) || !localRoster[idx]) return;

        const cycle = { Present: "Late", Late: "Absent", Absent: "Present" };
        localRoster[idx].status = cycle[localRoster[idx].status] || "Present";

        // Update the parent row's data-status and re-style the button
        const row = rosterList.querySelector(`.attendance-row[data-idx="${idx}"]`);
        if (row) row.dataset.status = localRoster[idx].status;

        const statusColors = {
          Present: { bg: "rgba(72,199,142,0.15)", text: "#48c78e", border: "rgba(72,199,142,0.3)" },
          Late: { bg: "rgba(255,193,7,0.15)", text: "#ffc107", border: "rgba(255,193,7,0.3)" },
          Absent: { bg: "rgba(255,107,107,0.12)", text: "#ff8b7b", border: "rgba(255,107,107,0.25)" }
        };
        const sc = statusColors[localRoster[idx].status];
        toggleBtn.textContent = localRoster[idx].status;
        toggleBtn.style.background = sc.bg;
        toggleBtn.style.color = sc.text;
        toggleBtn.style.borderColor = sc.border;
      });

      const saveBtn = document.getElementById("btn-save-attendance");
      if (saveBtn) {
        saveBtn.addEventListener("click", () => {
          const overrides = localRoster.map(r => ({
            student_id: r.student_id,
            student_name: r.student_name,
            batch_id: r.batch_id,
            status: r.status
          }));
          api.saveAttendanceOverrides(state.attendanceRoster.class_id, overrides);
        });
      }
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