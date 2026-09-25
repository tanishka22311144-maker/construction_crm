"""Dashboard HTML and Client UI Generator for Construction CRM.

Features:
1. Work Prediction S-Curve Chart (Expected vs Actual vs Predicted Forecast vs Date).
2. Dedicated Project Excel Viewer & Editor (strictly projects only) with required core & custom fields.
3. Real-Time Two-Way Sync with Supabase (Supabase Realtime WebSocket listener + live REST sync).
4. Direct .xlsx download button.
"""

def get_dashboard_html(supabase_url: str = "", supabase_anon_key: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Construction CRM — Project Analytics & Real-Time Excel Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
  <style>
    body {{
      background-color: #0f172a;
      color: #f8fafc;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    }}
    .excel-table th {{
      position: sticky;
      top: 0;
      background-color: #1e293b;
      z-index: 10;
    }}
    .editable-cell:focus {{
      outline: 2px solid #3b82f6;
      background-color: #1e293b;
    }}
    .pulse-dot {{
      animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: .4; }}
    }}
  </style>
</head>
<body class="min-h-screen flex flex-col">
  <!-- Top Navigation -->
  <header class="bg-slate-900 border-b border-slate-800 px-6 py-4 flex flex-wrap items-center justify-between gap-4 sticky top-0 z-50">
    <div class="flex items-center space-x-3">
      <div class="bg-blue-600 text-white p-2 rounded-lg text-lg">
        <i class="fa-solid fa-helmet-safety"></i>
      </div>
      <div>
        <h1 class="text-xl font-bold tracking-tight text-white flex items-center gap-2">
          Construction CRM
          <span class="text-xs font-semibold px-2 py-0.5 rounded bg-blue-900/60 text-blue-300 border border-blue-700">Stage 7</span>
        </h1>
        <p class="text-xs text-slate-400">Project Prediction & Real-Time Dedicated Excel Engine</p>
      </div>
    </div>

    <!-- Project Selector & Live Status -->
    <div class="flex items-center space-x-4">
      <div class="flex items-center bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-300">
        <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 pulse-dot mr-2" id="syncStatusDot"></span>
        <span id="syncStatusText">Real-Time Sync Active</span>
      </div>

      <div class="flex items-center space-x-2">
        <label for="projectSelector" class="text-xs text-slate-400 font-medium">Select Project:</label>
        <select id="projectSelector" class="bg-slate-800 border border-slate-700 text-white text-sm rounded-lg px-3 py-1.5 focus:ring-blue-500 focus:border-blue-500 cursor-pointer">
          <option value="">Loading projects...</option>
        </select>
      </div>

      <button id="btnNewProject" class="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition shadow-sm">
        <i class="fa-solid fa-plus"></i> New Project
      </button>
    </div>
  </header>

  <!-- Main Content -->
  <main class="flex-1 p-6 max-w-7xl mx-auto w-full space-y-6">
    <!-- Project KPIs -->
    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4" id="kpiGrid">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs text-slate-400 uppercase font-semibold">Project Code / Status</div>
        <div class="text-lg font-bold text-white mt-1 flex items-center gap-2" id="kpiProjectCode">—</div>
        <div class="text-xs text-slate-500 mt-1" id="kpiLocation">—</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs text-slate-400 uppercase font-semibold">Current Progress</div>
        <div class="text-2xl font-bold text-emerald-400 mt-1" id="kpiProgress">0%</div>
        <div class="text-xs text-slate-500 mt-1" id="kpiExpectedProgress">Expected: 0%</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs text-slate-400 uppercase font-semibold">Schedule Status</div>
        <div class="text-lg font-bold text-white mt-1" id="kpiScheduleStatus">—</div>
        <div class="text-xs text-slate-500 mt-1" id="kpiVariance">Variance: 0%</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs text-slate-400 uppercase font-semibold">Predicted Completion</div>
        <div class="text-lg font-bold text-amber-400 mt-1" id="kpiPredictedDate">—</div>
        <div class="text-xs text-slate-500 mt-1" id="kpiPlannedDate">Planned: —</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs text-slate-400 uppercase font-semibold">Total Logged Entries</div>
        <div class="text-2xl font-bold text-blue-400 mt-1" id="kpiTotalRecords">0</div>
        <div class="text-xs text-slate-500 mt-1" id="kpiVelocity">Velocity: 0%/day</div>
      </div>
    </section>

    <!-- Prediction S-Curve Chart -->
    <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
        <div>
          <h2 class="text-base font-semibold text-white flex items-center gap-2">
            <i class="fa-solid fa-chart-line text-blue-400"></i>
            Work Prediction vs. Date (Expected S-Curve vs. Actual vs. Forecast)
          </h2>
          <p class="text-xs text-slate-400">Comparison of planned baseline schedule, actual recorded progress, and velocity-projected completion</p>
        </div>
        <div class="flex items-center gap-3 text-xs">
          <span class="flex items-center gap-1.5"><span class="w-3 h-1 bg-blue-500 inline-block rounded"></span> Planned S-Curve</span>
          <span class="flex items-center gap-1.5"><span class="w-3 h-1 bg-emerald-500 inline-block rounded"></span> Actual Work Done</span>
          <span class="flex items-center gap-1.5"><span class="w-3 h-1 border-t-2 border-dashed border-amber-400 inline-block"></span> Predicted Forecast</span>
        </div>
      </div>
      <div class="relative h-72 w-full">
        <canvas id="predictionChart"></canvas>
      </div>
    </section>

    <!-- Dedicated Project Excel Section -->
    <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <div class="flex items-center gap-2">
            <span class="bg-emerald-900/60 text-emerald-400 text-xs px-2.5 py-0.5 rounded-full font-semibold border border-emerald-700 flex items-center gap-1.5">
              <i class="fa-solid fa-file-excel"></i> Dedicated Project Excel
            </span>
            <span class="text-xs text-slate-500">Only projects have excels &bull; Real-time synchronized with Supabase</span>
          </div>
          <h2 class="text-lg font-bold text-white mt-1" id="excelProjectTitle">Project Excel Workbook</h2>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <input type="file" id="excelFileInput" accept=".xlsx" class="hidden" />
          <button id="btnImportExcel" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold px-3 py-2 rounded-lg flex items-center gap-2 transition shadow-sm">
            <i class="fa-solid fa-file-import"></i> Import .xlsx
          </button>
          <button id="btnDownloadExcel" class="bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold px-3 py-2 rounded-lg border border-slate-700 flex items-center gap-2 transition">
            <i class="fa-solid fa-download text-emerald-400"></i> Download .xlsx
          </button>
          <button id="btnAddRow" class="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-2 rounded-lg flex items-center gap-2 transition">
            <i class="fa-solid fa-plus"></i> Add Row
          </button>
          <button id="btnSaveSheet" class="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold px-3 py-2 rounded-lg flex items-center gap-2 transition">
            <i class="fa-solid fa-cloud-arrow-up"></i> Sync to Supabase
          </button>
        </div>
      </div>

      <!-- Sheet Tabs -->
      <div class="flex space-x-2 border-b border-slate-800" id="sheetTabs">
        <button class="sheet-tab px-4 py-2 text-xs font-semibold text-white border-b-2 border-blue-500 bg-slate-800/50 rounded-t-lg" data-sheet="daily_log">
          <i class="fa-regular fa-calendar-check mr-1.5"></i> Daily Logs
        </button>
        <button class="sheet-tab px-4 py-2 text-xs font-semibold text-slate-400 hover:text-white border-b-2 border-transparent hover:border-slate-600 rounded-t-lg" data-sheet="expense">
          <i class="fa-solid fa-receipt mr-1.5"></i> Expenses
        </button>
        <button class="sheet-tab px-4 py-2 text-xs font-semibold text-slate-400 hover:text-white border-b-2 border-transparent hover:border-slate-600 rounded-t-lg" data-sheet="equipment_log">
          <i class="fa-solid fa-truck-pickup mr-1.5"></i> Equipment Logs
        </button>
      </div>

      <!-- Interactive Spreadsheet Grid -->
      <div class="overflow-x-auto max-h-96 border border-slate-800 rounded-lg">
        <table class="excel-table w-full text-left text-xs border-collapse">
          <thead>
            <tr id="tableHeaderRow" class="text-slate-300 font-semibold border-b border-slate-800">
              <!-- Dynamically populated headers -->
            </tr>
          </thead>
          <tbody id="tableBody" class="divide-y divide-slate-800/60 bg-slate-950/40">
            <!-- Dynamically populated rows -->
          </tbody>
        </table>
      </div>
      <div class="flex items-center justify-between text-xs text-slate-400 pt-1">
        <div id="recordCountInfo">0 rows loaded</div>
        <div class="flex items-center gap-2">
          <i class="fa-solid fa-info-circle text-blue-400"></i>
          <span>Click any cell to edit directly. Changes sync immediately to Supabase database.</span>
        </div>
      </div>
    </section>
  </main>

  <!-- Notification Toast -->
  <div id="toast" class="fixed bottom-5 right-5 bg-slate-800 border border-slate-700 text-white text-xs px-4 py-3 rounded-lg shadow-xl hidden transition-all duration-300 z-50 flex items-center gap-2">
    <i class="fa-solid fa-check-circle text-emerald-400" id="toastIcon"></i>
    <span id="toastMsg">Synced</span>
  </div>

  <!-- Modal: Create New Project -->
  <div id="modalNewProject" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md p-6 shadow-2xl space-y-4">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <h3 class="text-base font-bold text-white flex items-center gap-2">
          <i class="fa-solid fa-folder-plus text-blue-400"></i> Create New Project
        </h3>
        <button id="btnCloseNewProject" class="text-slate-400 hover:text-white transition">
          <i class="fa-solid fa-xmark text-lg"></i>
        </button>
      </div>

      <form id="formNewProject" class="space-y-4">
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Project Name *</label>
          <input type="text" id="inputNewProjectName" required placeholder="e.g. City Center Mall" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1">Project Code</label>
            <input type="text" id="inputNewProjectCode" placeholder="e.g. CCM-01" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" />
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1">Status</label>
            <select id="selectNewProjectStatus" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500 cursor-pointer">
              <option value="active">Active</option>
              <option value="planning">Planning</option>
              <option value="completed">Completed</option>
            </select>
          </div>
        </div>
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Location</label>
          <input type="text" id="inputNewProjectLocation" placeholder="e.g. Downtown Sector 4" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" />
        </div>

        <div class="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
          <button type="button" id="btnCancelNewProject" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg transition">Cancel</button>
          <button type="submit" id="btnSubmitNewProject" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg flex items-center gap-1.5 transition">
            <i class="fa-solid fa-plus"></i> Create Project
          </button>
        </div>
      </form>
    </div>
  </div>

  <!-- Modal: Import Excel Workbook -->
  <div id="modalImportExcel" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg p-6 shadow-2xl space-y-4">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <h3 class="text-base font-bold text-white flex items-center gap-2">
          <i class="fa-solid fa-file-import text-indigo-400"></i> Import Excel Workbook (.xlsx)
        </h3>
        <button id="btnCloseImportExcel" class="text-slate-400 hover:text-white transition">
          <i class="fa-solid fa-xmark text-lg"></i>
        </button>
      </div>

      <!-- File Details -->
      <div class="bg-slate-800/80 border border-slate-700 rounded-xl p-3.5 flex items-center gap-3">
        <div class="bg-emerald-950 border border-emerald-700/60 p-2.5 rounded-lg text-emerald-400 text-xl">
          <i class="fa-solid fa-file-excel"></i>
        </div>
        <div class="flex-1 min-w-0">
          <div class="text-sm font-semibold text-white truncate" id="importFileName">workbook.xlsx</div>
          <div class="text-xs text-slate-400 mt-0.5" id="importFileSize">0 KB</div>
        </div>
      </div>

      <!-- Reconcile Warning / Mode Selection -->
      <div class="space-y-3">
        <div class="text-xs text-slate-400">
          Choose reconciliation mode for this workbook:
        </div>

        <div class="space-y-2">
          <label class="flex items-start gap-3 p-3 bg-slate-800/50 hover:bg-slate-800 border border-slate-700 rounded-xl cursor-pointer transition">
            <input type="radio" name="importTargetMode" value="existing" checked class="mt-0.5 text-indigo-600 focus:ring-indigo-500" id="radioImportExisting" />
            <div>
              <div class="text-xs font-semibold text-white">Reconcile into Current Project (<span id="importCurrentProjectName">Current</span>)</div>
              <p class="text-[11px] text-slate-400 mt-0.5">
                Exact mirror: matching Record IDs update, new rows insert, omitted records in Supabase are deleted, and new custom columns are auto-registered.
              </p>
            </div>
          </label>

          <label class="flex items-start gap-3 p-3 bg-slate-800/50 hover:bg-slate-800 border border-slate-700 rounded-xl cursor-pointer transition">
            <input type="radio" name="importTargetMode" value="new" class="mt-0.5 text-indigo-600 focus:ring-indigo-500" id="radioImportNew" />
            <div>
              <div class="text-xs font-semibold text-white">Create as a New Project</div>
              <p class="text-[11px] text-slate-400 mt-0.5">
                Creates a brand new project record and imports all records & custom fields from the workbook sheets.
              </p>
            </div>
          </label>
        </div>

        <!-- Optional fields if New Project is selected -->
        <div id="importNewProjectFields" class="hidden bg-slate-800/40 p-3 rounded-xl border border-slate-700/60 space-y-2">
          <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">New Project Name (optional, defaults to workbook title)</label>
            <input type="text" id="inputImportProjectName" placeholder="e.g. Metro Line Phase 2" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">Project Code (optional)</label>
            <input type="text" id="inputImportProjectCode" placeholder="e.g. MLP-02" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500" />
          </div>
        </div>
      </div>

      <div class="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
        <button type="button" id="btnCancelImportExcel" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg transition">Cancel</button>
        <button type="button" id="btnConfirmImportExcel" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg flex items-center gap-1.5 transition">
          <i class="fa-solid fa-cloud-arrow-up"></i> Reconcile & Import
        </button>
      </div>
    </div>
  </div>

  <script>
    // Configuration
    const SUPABASE_URL = "{supabase_url}";
    const SUPABASE_KEY = "{supabase_anon_key}";
    let supabaseClient = null;
    if (SUPABASE_URL && SUPABASE_KEY) {{
      try {{
        supabaseClient = supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
      }} catch (e) {{
        console.warn("Supabase client init error:", e);
      }}
    }}

    const API_BASE = "/api/index";
    let currentProjectId = "";
    let spreadsheetData = null;
    let currentSheetType = "daily_log";
    let chartInstance = null;
    let isLocalSyncing = false;

    // Toast helper
    function showToast(message, isError = false) {{
      const toast = document.getElementById("toast");
      const msg = document.getElementById("toastMsg");
      const icon = document.getElementById("toastIcon");
      msg.textContent = message;
      if (isError) {{
        icon.className = "fa-solid fa-circle-exclamation text-rose-400";
      }} else {{
        icon.className = "fa-solid fa-check-circle text-emerald-400";
      }}
      toast.classList.remove("hidden");
      setTimeout(() => toast.classList.add("hidden"), 3500);
    }}

    // 1. Load Projects List
    async function loadProjects(preferredProjectId = null) {{
      try {{
        const res = await fetch(`${{API_BASE}}/projects`);
        const data = await res.json();
        const selector = document.getElementById("projectSelector");
        selector.innerHTML = "";
        
        if (!data.projects || data.projects.length === 0) {{
          selector.innerHTML = '<option value="">No projects found</option>';
          return;
        }}

        data.projects.forEach((p, idx) => {{
          const opt = document.createElement("option");
          opt.value = p.id;
          opt.textContent = `${{p.project_name}} (${{p.project_code || 'No code'}})`;
          selector.appendChild(opt);
        }});

        if (preferredProjectId && data.projects.some((p) => p.id === preferredProjectId)) {{
          currentProjectId = preferredProjectId;
        }} else if (currentProjectId && data.projects.some((p) => p.id === currentProjectId)) {{
          // keep current selection
        }} else {{
          currentProjectId = data.projects[0].id;
        }}
        selector.value = currentProjectId;
        await refreshProjectDashboard();
        initRealtimeSubscription();
      }} catch (err) {{
        console.error("Failed to load projects:", err);
        showToast("Error loading projects: " + err.message, true);
      }}
    }}

    // 2. Refresh Dashboard (Prediction + Excel)
    async function refreshProjectDashboard() {{
      if (!currentProjectId) return;
      await Promise.all([
        loadPredictionData(),
        loadSpreadsheetData(),
      ]);
    }}

    // 3. Load & Render Prediction Chart
    async function loadPredictionData() {{
      try {{
        const res = await fetch(`${{API_BASE}}/projects/${{currentProjectId}}/prediction`);
        const pred = await res.json();

        // Update KPIs
        const m = pred.metrics || {{}};
        document.getElementById("kpiProjectCode").textContent = `${{pred.project_code || '—'}}`;
        document.getElementById("kpiLocation").textContent = pred.location ? `Location: ${{pred.location}}` : 'Location: Not specified';
        document.getElementById("kpiProgress").textContent = `${{m.current_progress_pct || 0}}%`;
        document.getElementById("kpiExpectedProgress").textContent = `Expected: ${{m.expected_progress_pct || 0}}%`;
        
        const statusEl = document.getElementById("kpiScheduleStatus");
        statusEl.textContent = m.schedule_status || '—';
        if (m.schedule_status === 'Ahead of Schedule') {{
          statusEl.className = "text-lg font-bold text-emerald-400 mt-1";
        }} else if (m.schedule_status === 'Behind Schedule') {{
          statusEl.className = "text-lg font-bold text-rose-400 mt-1";
        }} else {{
          statusEl.className = "text-lg font-bold text-blue-400 mt-1";
        }}

        document.getElementById("kpiVariance").textContent = `Variance: ${{m.variance_pct > 0 ? '+' : ''}}${{m.variance_pct || 0}}%`;
        document.getElementById("kpiPredictedDate").textContent = m.predicted_completion_date || '—';
        document.getElementById("kpiPlannedDate").textContent = `Planned: ${{m.planned_completion_date || '—'}}`;
        document.getElementById("kpiTotalRecords").textContent = m.total_records || 0;
        document.getElementById("kpiVelocity").textContent = `Velocity: ${{m.velocity_pct_per_day || 0}}%/day`;

        // Render Chart.js
        renderPredictionChart(pred.dates, pred.expected_work, pred.actual_work, pred.predicted_work);
      }} catch (err) {{
        console.error("Failed to load prediction data:", err);
      }}
    }}

    function renderPredictionChart(dates, expected, actual, predicted) {{
      const ctx = document.getElementById("predictionChart").getContext("2d");
      if (chartInstance) {{
        chartInstance.destroy();
      }}

      chartInstance = new Chart(ctx, {{
        type: "line",
        data: {{
          labels: dates,
          datasets: [
            {{
              label: "Planned S-Curve (%)",
              data: expected,
              borderColor: "#3b82f6",
              backgroundColor: "rgba(59, 130, 246, 0.1)",
              borderWidth: 2,
              tension: 0.3,
              fill: false,
              pointRadius: 0,
            }},
            {{
              label: "Actual Work Done (%)",
              data: actual,
              borderColor: "#10b981",
              backgroundColor: "rgba(16, 185, 129, 0.15)",
              borderWidth: 3,
              tension: 0.2,
              fill: true,
              pointRadius: 4,
              pointHoverRadius: 6,
            }},
            {{
              label: "Predicted Forecast (%)",
              data: predicted,
              borderColor: "#f59e0b",
              borderDash: [5, 5],
              borderWidth: 2,
              tension: 0.2,
              fill: false,
              pointRadius: 2,
            }},
          ],
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          interaction: {{
            mode: "index",
            intersect: false,
          }},
          plugins: {{
            legend: {{ display: false }},
            tooltip: {{
              backgroundColor: "#1e293b",
              titleColor: "#f8fafc",
              bodyColor: "#94a3b8",
              borderColor: "#334155",
              borderWidth: 1,
              callbacks: {{
                label: function (ctx) {{
                  if (ctx.parsed.y === null || ctx.parsed.y === undefined) return null;
                  return `${{ctx.dataset.label}}: ${{ctx.parsed.y}}%`;
                }},
              }},
            }},
          }},
          scales: {{
            x: {{
              grid: {{ color: "rgba(51, 65, 85, 0.4)" }},
              ticks: {{ color: "#94a3b8", font: {{ size: 10 }}, maxTicksLimit: 12 }},
            }},
            y: {{
              min: 0,
              max: 100,
              grid: {{ color: "rgba(51, 65, 85, 0.4)" }},
              ticks: {{
                color: "#94a3b8",
                font: {{ size: 10 }},
                callback: (v) => v + "%",
              }},
            }},
          }},
        }},
      }});
    }}

    // 4. Load & Render Project Dedicated Excel Spreadsheet
    // 4. Load & Render Project Dedicated Excel Spreadsheet
    async function loadSpreadsheetData() {{
      try {{
        const res = await fetch(`${{API_BASE}}/projects/${{currentProjectId}}/spreadsheet`);
        spreadsheetData = await res.json();
        
        document.getElementById("excelProjectTitle").textContent = 
          `${{spreadsheetData.project.project_name}} — Excel Workbook`;

        updateTabBadges();
        renderSpreadsheet();
      }} catch (err) {{
        console.error("Failed to load spreadsheet data:", err);
      }}
    }}

    function updateTabBadges() {{
      if (!spreadsheetData || !spreadsheetData.sheets) return;
      document.querySelectorAll(".sheet-tab").forEach((tab) => {{
        const sType = tab.dataset.sheet;
        const s = spreadsheetData.sheets[sType];
        const rowCount = s && s.rows ? s.rows.length : 0;
        const customCols = s && s.columns ? s.columns.filter((c) => c.is_custom) : [];

        let icon = "fa-regular fa-calendar-check";
        let label = "Daily Logs";
        if (sType === "expense") {{
          icon = "fa-solid fa-receipt";
          label = "Expenses";
        }} else if (sType === "equipment_log") {{
          icon = "fa-solid fa-truck-pickup";
          label = "Equipment Logs";
        }}

        let badgeHtml = `<span class="ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] bg-slate-700/80 text-slate-300">${{rowCount}}</span>`;
        if (customCols.length > 0) {{
          badgeHtml += `<span class="ml-1.5 px-1.5 py-0.5 rounded text-[10px] bg-purple-900/60 text-purple-300 border border-purple-700/60" title="Custom fields: ${{customCols.map((c) => c.title).join(', ')}}">${{customCols.length}} Custom</span>`;
        }}

        tab.innerHTML = `<i class="${{icon}} mr-1.5"></i> ${{label}} ${{badgeHtml}}`;
      }});
    }}

    function renderSpreadsheet() {{
      if (!spreadsheetData) return;
      const sheet = spreadsheetData.sheets[currentSheetType];
      if (!sheet) return;

      const thead = document.getElementById("tableHeaderRow");
      thead.innerHTML = "";

      // Headers: ID + columns + Actions
      const thId = document.createElement("th");
      thId.className = "px-3 py-2 text-slate-400 uppercase tracking-wider text-[11px] w-24";
      thId.textContent = "Record ID";
      thead.appendChild(thId);

      sheet.columns.forEach((col) => {{
        const th = document.createElement("th");
        th.className = "px-3 py-2 text-slate-300 uppercase tracking-wider text-[11px]";
        if (col.is_custom) {{
          th.innerHTML = `${{col.title}} <span class="ml-1 px-1.5 py-0.5 rounded text-[9px] bg-purple-900/70 text-purple-300 border border-purple-700 font-semibold normal-case">Custom</span>` + (col.required ? " *" : "");
        }} else {{
          th.textContent = col.title + (col.required ? " *" : "");
        }}
        thead.appendChild(th);
      }});

      const thAct = document.createElement("th");
      thAct.className = "px-3 py-2 text-slate-400 uppercase tracking-wider text-[11px] text-right w-20";
      thAct.textContent = "Action";
      thead.appendChild(thAct);

      // Rows
      const tbody = document.getElementById("tableBody");
      tbody.innerHTML = "";

      sheet.rows.forEach((row, rowIdx) => {{
        const tr = document.createElement("tr");
        tr.className = (row._dirty ? "bg-blue-900/30 " : "") + "hover:bg-slate-900/60 transition";
        tr.dataset.rowId = row.id || "";
        tr.dataset.rowIdx = rowIdx;
        tr.dataset.dirty = row._dirty ? "true" : "false";

        // ID cell
        const tdId = document.createElement("td");
        tdId.className = "px-3 py-2 font-mono text-[10px] text-slate-500 truncate max-w-[80px]";
        tdId.textContent = row.id ? row.id.substring(0, 8) + '...' : 'NEW';
        tr.appendChild(tdId);

        // Editable Column cells
        sheet.columns.forEach((col) => {{
          const td = document.createElement("td");
          td.className = "px-3 py-2 text-slate-200 editable-cell cursor-text";
          td.contentEditable = "true";
          td.dataset.colName = col.name;
          td.dataset.colType = col.type;
          
          let val = row[col.name];
          if (val === undefined || val === null) val = "";
          td.textContent = val;

          // Input listener: capture user typing immediately, mark row dirty & highlight
          td.addEventListener("input", (e) => {{
            const rawVal = e.target.textContent.trim();
            row[col.name] = col.type === "numeric" ? (rawVal === "" ? null : parseFloat(rawVal)) : rawVal;
            row._dirty = true;
            tr.dataset.dirty = "true";
            tr.classList.add("bg-blue-900/30");
          }});

          // Blur listener: ensure value is committed to row
          td.addEventListener("blur", (e) => {{
            const rawVal = e.target.textContent.trim();
            row[col.name] = col.type === "numeric" ? (rawVal === "" ? null : parseFloat(rawVal)) : rawVal;
          }});

          tr.appendChild(td);
        }});

        // Action cell (Save Button)
        const tdAct = document.createElement("td");
        tdAct.className = "px-3 py-2 text-right";
        const btnSave = document.createElement("button");
        btnSave.className = "text-blue-400 hover:text-blue-300 text-xs px-2 py-1 rounded hover:bg-slate-800 transition";
        btnSave.innerHTML = '<i class="fa-solid fa-check"></i>';
        btnSave.title = "Save this row to Supabase";
        btnSave.addEventListener("click", () => saveRow(row, tr));
        tdAct.appendChild(btnSave);
        tr.appendChild(tdAct);

        tbody.appendChild(tr);
      }});

      const customNames = sheet.columns.filter((c) => c.is_custom).map((c) => c.title);
      let customInfo = customNames.length ? ` • Custom fields: ${{customNames.join(', ')}}` : "";
      document.getElementById("recordCountInfo").textContent = `${{sheet.rows.length}} rows loaded${{customInfo}}`;
    }}

    // 5. Save Single Row to Supabase (Excel -> Supabase sync)
    async function saveRow(row, trElement = null) {{
      isLocalSyncing = true;
      try {{
        if (trElement) {{
          trElement.querySelectorAll(".editable-cell").forEach((cell) => {{
            const cName = cell.dataset.colName;
            const cType = cell.dataset.colType;
            const txt = cell.textContent.trim();
            row[cName] = cType === "numeric" ? (txt === "" ? null : parseFloat(txt)) : txt;
          }});
        }}

        const payload = {{
          record_type: currentSheetType,
          ...row,
        }};
        delete payload._dirty;
        if (!payload.id || payload.id === "" || payload.id === "NEW") {{
          delete payload.id;
        }}

        const res = await fetch(`${{API_BASE}}/projects/${{currentProjectId}}/sync_row`, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});

        const result = await res.json();
        if (result.success && result.record) {{
          row.id = result.record.id;
          row._dirty = false;
          if (trElement) {{
            trElement.dataset.rowId = result.record.id;
            trElement.dataset.dirty = "false";
            trElement.classList.remove("bg-blue-900/30");
            const idCell = trElement.querySelector("td");
            if (idCell) {{
              idCell.textContent = result.record.id.substring(0, 8) + '...';
            }}
          }}
          showToast(`Row "${{result.record.title || 'Entry'}}" synced to Supabase`);
          updateTabBadges();
          loadPredictionData();
        }} else {{
          showToast("Sync error: " + (result.error || "Failed"), true);
        }}
      }} catch (err) {{
        console.error("Save row failed:", err);
        showToast("Error syncing row: " + err.message, true);
      }} finally {{
        setTimeout(() => {{
          isLocalSyncing = false;
        }}, 1500);
      }}
    }}

    // 6. Add New Blank Row
    document.getElementById("btnAddRow").addEventListener("click", () => {{
      if (!spreadsheetData) return;
      const sheet = spreadsheetData.sheets[currentSheetType];
      if (!sheet) return;

      const newRow = {{
        id: "",
        record_type: currentSheetType,
        record_date: new Date().toISOString().substring(0, 10),
        title: "New Entry",
        description: "",
        _dirty: true,
      }};

      sheet.columns.forEach((c) => {{
        if (newRow[c.name] === undefined) {{
          newRow[c.name] = c.default !== undefined && c.default !== null ? c.default : "";
        }}
      }});

      sheet.rows.unshift(newRow);
      renderSpreadsheet();
      updateTabBadges();
      showToast("Added new row — edit cells and click 'Sync to Supabase'");
    }});

    // 7. Sync to Supabase Button (Batch / Whole-Sheet Sync)
    document.getElementById("btnSaveSheet").addEventListener("click", async () => {{
      if (!spreadsheetData) return;
      const sheet = spreadsheetData.sheets[currentSheetType];
      if (!sheet) return;

      const btn = document.getElementById("btnSaveSheet");
      const origHtml = btn.innerHTML;

      // 1. Gather all latest values from DOM cells into sheet.rows and detect dirty rows
      const tbody = document.getElementById("tableBody");
      const trs = Array.from(tbody.querySelectorAll("tr"));

      trs.forEach((tr) => {{
        const rowIdx = parseInt(tr.dataset.rowIdx, 10);
        const row = sheet.rows[rowIdx];
        if (!row) return;

        tr.querySelectorAll(".editable-cell").forEach((cell) => {{
          const colName = cell.dataset.colName;
          const colType = cell.dataset.colType;
          const textVal = cell.textContent.trim();
          const parsedVal = colType === "numeric" ? (textVal === "" ? null : parseFloat(textVal)) : textVal;
          if (row[colName] !== parsedVal) {{
            row[colName] = parsedVal;
            row._dirty = true;
            tr.dataset.dirty = "true";
          }}
        }});
      }});

      // 2. Filter to rows that need syncing (dirty rows or unsaved/new rows)
      let rowsToSync = [];
      trs.forEach((tr) => {{
        const rowIdx = parseInt(tr.dataset.rowIdx, 10);
        const row = sheet.rows[rowIdx];
        if (!row) return;
        if (row._dirty || !row.id || row.id === "" || row.id === "NEW") {{
          rowsToSync.push({{ row, tr }});
        }}
      }});

      if (rowsToSync.length === 0) {{
        showToast("All rows are already synchronized with Supabase.");
        return;
      }}

      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Syncing...';
      isLocalSyncing = true;
      showToast(`Syncing ${{rowsToSync.length}} row${{rowsToSync.length > 1 ? 's' : ''}} to Supabase...`);

      let successCount = 0;
      let failCount = 0;
      let firstError = "";

      for (const item of rowsToSync) {{
        const row = item.row;
        const tr = item.tr;

        try {{
          const payload = {{
            record_type: currentSheetType,
            ...row,
          }};
          delete payload._dirty;
          if (!payload.id || payload.id === "" || payload.id === "NEW") {{
            delete payload.id;
          }}

          const res = await fetch(`${{API_BASE}}/projects/${{currentProjectId}}/sync_row`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload),
          }});

          const result = await res.json();
          if (result.success && result.record) {{
            row.id = result.record.id;
            row._dirty = false;
            tr.dataset.rowId = result.record.id;
            tr.dataset.dirty = "false";
            tr.classList.remove("bg-blue-900/30");
            const idCell = tr.querySelector("td");
            if (idCell) {{
              idCell.textContent = result.record.id.substring(0, 8) + '...';
            }}
            successCount++;
          }} else {{
            failCount++;
            if (!firstError) firstError = result.error || "Save failed";
          }}
        }} catch (e) {{
          console.error("Sync row error:", e);
          failCount++;
          if (!firstError) firstError = e.message;
        }}
      }}

      setTimeout(() => {{
        isLocalSyncing = false;
      }}, 1500);

      btn.disabled = false;
      btn.innerHTML = origHtml;

      if (failCount > 0) {{
        showToast(`Synced ${{successCount}} rows, ${{failCount}} failed: ${{firstError}}`, true);
      }} else {{
        showToast(`Successfully synced ${{successCount}} row${{successCount > 1 ? 's' : ''}} to Supabase!`);
      }}

      updateTabBadges();
      loadPredictionData();
    }});

    // 8. Download Live .xlsx
    document.getElementById("btnDownloadExcel").addEventListener("click", () => {{
      if (!currentProjectId) return;
      window.location.href = `${{API_BASE}}/projects/${{currentProjectId}}/excel`;
    }});

    // 9. Tab Navigation
    document.querySelectorAll(".sheet-tab").forEach((tab) => {{
      tab.addEventListener("click", (e) => {{
        document.querySelectorAll(".sheet-tab").forEach((t) => {{
          t.className = "sheet-tab px-4 py-2 text-xs font-semibold text-slate-400 hover:text-white border-b-2 border-transparent hover:border-slate-600 rounded-t-lg";
        }});
        const target = e.currentTarget;
        target.className = "sheet-tab px-4 py-2 text-xs font-semibold text-white border-b-2 border-blue-500 bg-slate-800/50 rounded-t-lg";
        currentSheetType = target.dataset.sheet;
        renderSpreadsheet();
      }});
    }});

    // 10. Project Selector Change
    document.getElementById("projectSelector").addEventListener("change", (e) => {{
      currentProjectId = e.target.value;
      refreshProjectDashboard();
      initRealtimeSubscription();
    }});

    // 11. Realtime Subscription (Supabase -> Excel live sync)
    let activeChannel = null;
    function initRealtimeSubscription() {{
      if (!supabaseClient || !currentProjectId) return;

      if (activeChannel) {{
        supabaseClient.removeChannel(activeChannel);
      }}

      activeChannel = supabaseClient
        .channel(`public:${{currentProjectId}}`)
        .on(
          "postgres_changes",
          {{
            event: "*",
            schema: "public",
            table: "project_records",
            filter: `project_id=eq.${{currentProjectId}}`,
          }},
          (payload) => {{
            console.log("Realtime event received from Supabase:", payload);
            if (isLocalSyncing) {{
              console.log("Skipping realtime reload during local sync");
              return;
            }}
            showToast(`Real-time update from Supabase (${{payload.eventType}})`);
            refreshProjectDashboard();
          }}
        )
        .on(
          "postgres_changes",
          {{
            event: "*",
            schema: "public",
            table: "project_field_definitions",
            filter: `project_id=eq.${{currentProjectId}}`,
          }},
          (payload) => {{
            console.log("Realtime field definitions update:", payload);
            if (isLocalSyncing) {{
              return;
            }}
            showToast(`Custom fields updated (${{payload.eventType}})`);
            refreshProjectDashboard();
          }}
        )
        .subscribe((status) => {{
          const dot = document.getElementById("syncStatusDot");
          const text = document.getElementById("syncStatusText");
          if (status === "SUBSCRIBED") {{
            dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-500 pulse-dot mr-2";
            text.textContent = "Real-Time Sync Active";
          }} else {{
            dot.className = "w-2.5 h-2.5 rounded-full bg-amber-500 mr-2";
            text.textContent = `Sync: ${{status}}`;
          }}
        }});
    }}

    // 12. Create New Project Modal Logic
    const modalNewProject = document.getElementById("modalNewProject");
    const btnNewProject = document.getElementById("btnNewProject");
    const btnCloseNewProject = document.getElementById("btnCloseNewProject");
    const btnCancelNewProject = document.getElementById("btnCancelNewProject");
    const formNewProject = document.getElementById("formNewProject");
    const btnSubmitNewProject = document.getElementById("btnSubmitNewProject");

    if (btnNewProject) {{
      btnNewProject.addEventListener("click", () => {{
        document.getElementById("inputNewProjectName").value = "";
        document.getElementById("inputNewProjectCode").value = "";
        document.getElementById("inputNewProjectLocation").value = "";
        document.getElementById("selectNewProjectStatus").value = "active";
        modalNewProject.classList.remove("hidden");
        document.getElementById("inputNewProjectName").focus();
      }});
    }}

    const closeNewProjectModal = () => {{
      modalNewProject.classList.add("hidden");
    }};
    if (btnCloseNewProject) btnCloseNewProject.addEventListener("click", closeNewProjectModal);
    if (btnCancelNewProject) btnCancelNewProject.addEventListener("click", closeNewProjectModal);

    if (formNewProject) {{
      formNewProject.addEventListener("submit", async (e) => {{
        e.preventDefault();
        const name = document.getElementById("inputNewProjectName").value.trim();
        const code = document.getElementById("inputNewProjectCode").value.trim();
        const loc = document.getElementById("inputNewProjectLocation").value.trim();
        const status = document.getElementById("selectNewProjectStatus").value;

        if (!name) return;

        btnSubmitNewProject.disabled = true;
        btnSubmitNewProject.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating...';

        try {{
          const res = await fetch(`${{API_BASE}}/projects/create`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
              project_name: name,
              project_code: code || null,
              location: loc || null,
              status: status,
            }}),
          }});
          const data = await res.json();
          if (data.success && data.project) {{
            showToast(`Project "${{data.project.project_name}}" created successfully!`);
            closeNewProjectModal();
            await loadProjects(data.project.id);
          }} else {{
            showToast("Failed to create project: " + (data.error || "Unknown error"), true);
          }}
        }} catch (err) {{
          showToast("Error creating project: " + err.message, true);
        }} finally {{
          btnSubmitNewProject.disabled = false;
          btnSubmitNewProject.innerHTML = '<i class="fa-solid fa-plus"></i> Create Project';
        }}
      }});
    }}

    // 13. Excel Import & Reconciliation Logic
    const excelFileInput = document.getElementById("excelFileInput");
    const btnImportExcel = document.getElementById("btnImportExcel");
    const modalImportExcel = document.getElementById("modalImportExcel");
    const btnCloseImportExcel = document.getElementById("btnCloseImportExcel");
    const btnCancelImportExcel = document.getElementById("btnCancelImportExcel");
    const btnConfirmImportExcel = document.getElementById("btnConfirmImportExcel");
    const radioImportExisting = document.getElementById("radioImportExisting");
    const radioImportNew = document.getElementById("radioImportNew");
    const importNewProjectFields = document.getElementById("importNewProjectFields");

    let selectedImportFile = null;

    if (btnImportExcel && excelFileInput) {{
      btnImportExcel.addEventListener("click", () => {{
        excelFileInput.value = "";
        excelFileInput.click();
      }});

      excelFileInput.addEventListener("change", (e) => {{
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        selectedImportFile = file;

        document.getElementById("importFileName").textContent = file.name;
        const sizeKb = (file.size / 1024).toFixed(1);
        document.getElementById("importFileSize").textContent = `${{sizeKb}} KB`;

        const currentProjOpt = document.getElementById("projectSelector").selectedOptions[0];
        document.getElementById("importCurrentProjectName").textContent = currentProjOpt ? currentProjOpt.textContent : "Current";

        radioImportExisting.checked = true;
        importNewProjectFields.classList.add("hidden");
        document.getElementById("inputImportProjectName").value = "";
        document.getElementById("inputImportProjectCode").value = "";

        modalImportExcel.classList.remove("hidden");
      }});
    }}

    if (radioImportExisting) {{
      radioImportExisting.addEventListener("change", () => {{
        importNewProjectFields.classList.add("hidden");
      }});
    }}

    if (radioImportNew) {{
      radioImportNew.addEventListener("change", () => {{
        importNewProjectFields.classList.remove("hidden");
      }});
    }}

    const closeImportModal = () => {{
      modalImportExcel.classList.add("hidden");
      selectedImportFile = null;
    }};
    if (btnCloseImportExcel) btnCloseImportExcel.addEventListener("click", closeImportModal);
    if (btnCancelImportExcel) btnCancelImportExcel.addEventListener("click", closeImportModal);

    if (btnConfirmImportExcel) {{
      btnConfirmImportExcel.addEventListener("click", async () => {{
        if (!selectedImportFile) return;

        const isNew = radioImportNew.checked;
        btnConfirmImportExcel.disabled = true;
        btnConfirmImportExcel.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Reconciling with Supabase...';

        try {{
          const formData = new FormData();
          formData.append("file", selectedImportFile);

          let url = "";
          if (isNew) {{
            url = `${{API_BASE}}/projects/import_new`;
            const pName = document.getElementById("inputImportProjectName").value.trim();
            const pCode = document.getElementById("inputImportProjectCode").value.trim();
            if (pName) formData.append("project_name", pName);
            if (pCode) formData.append("project_code", pCode);
          }} else {{
            if (!currentProjectId) {{
              showToast("No active project selected to reconcile into.", true);
              btnConfirmImportExcel.disabled = false;
              btnConfirmImportExcel.innerHTML = '<i class="fa-solid fa-cloud-arrow-up"></i> Reconcile & Import';
              return;
            }}
            url = `${{API_BASE}}/projects/${{currentProjectId}}/import_excel`;
          }}

          const res = await fetch(url, {{
            method: "POST",
            body: formData,
          }});
          const data = await res.json();

          if (data.success) {{
            const rec = data.reconciliation || {{}};
            const msg = `Reconciliation Complete: ${{rec.inserted || 0}} added, ${{rec.updated || 0}} updated, ${{rec.deleted || 0}} deleted, ${{rec.custom_fields_added || 0}} new custom fields.`;
            showToast(msg);
            closeImportModal();
            const targetProjId = data.project_id || currentProjectId;
            await loadProjects(targetProjId);
          }} else {{
            showToast("Import failed: " + (data.error || "Unknown error"), true);
          }}
        }} catch (err) {{
          showToast("Error importing Excel: " + err.message, true);
        }} finally {{
          btnConfirmImportExcel.disabled = false;
          btnConfirmImportExcel.innerHTML = '<i class="fa-solid fa-cloud-arrow-up"></i> Reconcile & Import';
        }}
      }});
    }}

    // Initialize on load
    window.addEventListener("DOMContentLoaded", () => loadProjects());
  </script>
</body>
</html>
"""
