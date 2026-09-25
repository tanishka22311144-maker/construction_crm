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
    async function loadProjects() {{
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

        currentProjectId = data.projects[0].id;
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
    async function loadSpreadsheetData() {{
      try {{
        const res = await fetch(`${{API_BASE}}/projects/${{currentProjectId}}/spreadsheet`);
        spreadsheetData = await res.json();
        
        document.getElementById("excelProjectTitle").textContent = 
          `${{spreadsheetData.project.project_name}} — Excel Workbook`;

        renderSpreadsheet();
      }} catch (err) {{
        console.error("Failed to load spreadsheet data:", err);
      }}
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
        th.textContent = col.title + (col.required ? " *" : "");
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
        tr.className = "hover:bg-slate-900/60 transition";
        tr.dataset.rowId = row.id || "";
        tr.dataset.rowIdx = rowIdx;

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

          // On cell blur, auto-save / stage edit
          td.addEventListener("blur", (e) => {{
            const newVal = e.target.textContent.trim();
            row[col.name] = newVal;
            saveRow(row);
          }});

          tr.appendChild(td);
        }});

        // Action cell (Save Button)
        const tdAct = document.createElement("td");
        tdAct.className = "px-3 py-2 text-right";
        const btnSave = document.createElement("button");
        btnSave.className = "text-blue-400 hover:text-blue-300 text-xs";
        btnSave.innerHTML = '<i class="fa-solid fa-check"></i>';
        btnSave.title = "Save row to Supabase";
        btnSave.addEventListener("click", () => saveRow(row));
        tdAct.appendChild(btnSave);
        tr.appendChild(tdAct);

        tbody.appendChild(tr);
      }});

      document.getElementById("recordCountInfo").textContent = `${{sheet.rows.length}} rows loaded`;
    }}

    // 5. Save Row to Supabase (Excel -> Supabase sync)
    async function saveRow(row) {{
      try {{
        const payload = {{
          id: row.id || undefined,
          record_type: currentSheetType,
          ...row,
        }};

        const res = await fetch(`${{API_BASE}}/projects/${{currentProjectId}}/sync_row`, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});

        const result = await res.json();
        if (result.success) {{
          row.id = result.record.id;
          showToast(`Row ${{result.record.title || ''}} synced to Supabase`);
          loadPredictionData(); // refresh prediction curve with new data
        }} else {{
          showToast("Sync error: " + (result.error || "Failed"), true);
        }}
      }} catch (err) {{
        console.error("Save row failed:", err);
        showToast("Error syncing row: " + err.message, true);
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
      }};

      sheet.columns.forEach((c) => {{
        if (!newRow[c.name]) newRow[c.name] = c.default || "";
      }});

      sheet.rows.unshift(newRow);
      renderSpreadsheet();
      showToast("Added new row — enter values and click checkmark or click outside cell to sync");
    }});

    // 7. Download Live .xlsx
    document.getElementById("btnDownloadExcel").addEventListener("click", () => {{
      if (!currentProjectId) return;
      window.location.href = `${{API_BASE}}/projects/${{currentProjectId}}/excel`;
    }});

    // 8. Tab Navigation
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

    // 9. Project Selector Change
    document.getElementById("projectSelector").addEventListener("change", (e) => {{
      currentProjectId = e.target.value;
      refreshProjectDashboard();
      initRealtimeSubscription();
    }});

    // 10. Realtime Subscription (Supabase -> Excel live sync)
    let activeChannel = null;
    function initRealtimeSubscription() {{
      if (!supabaseClient || !currentProjectId) return;

      if (activeChannel) {{
        supabaseClient.removeChannel(activeChannel);
      }}

      activeChannel = supabaseClient
        .channel(`public:project_records:${{currentProjectId}}`)
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
            showToast(`Real-time update from Supabase (${{payload.eventType}})`);
            // Automatically refresh spreadsheet and prediction curve
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

    // Initialize on load
    window.addEventListener("DOMContentLoaded", loadProjects);
  </script>
</body>
</html>
"""
