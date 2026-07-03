import React from "react";
import { createRoot } from "react-dom/client";
import { Chart } from "chart.js/auto";
import {
  Activity,
  BarChart3,
  BriefcaseBusiness,
  Building2,
  Database,
  Download,
  Gauge,
  Moon,
  Search,
  ShieldCheck,
  Sun,
  X,
} from "lucide-react";
import "./styles.css";

const api = async (path) => {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
};

const navItems = [
  { href: "#/overview", label: "Overview", icon: BarChart3 },
  { href: "#/explorer", label: "Explorer", icon: Gauge },
  { href: "#/jobs", label: "Evidence", icon: BriefcaseBusiness },
  { href: "#/admin", label: "Admin", icon: ShieldCheck },
];

function App() {
  const [route, setRoute] = React.useState(window.location.hash || "#/overview");
  const [query, setQuery] = React.useState("");
  const [payload, setPayload] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [dark, setDark] = React.useState(
    window.localStorage.getItem("roleradar.theme") === "dark",
  );

  React.useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash || "#/overview");
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  React.useEffect(() => {
    document.body.classList.toggle("dark", dark);
    window.localStorage.setItem("roleradar.theme", dark ? "dark" : "light");
  }, [dark]);

  React.useEffect(() => {
    setError(null);
    setPayload(null);

    const params = new URLSearchParams();
    if (query && route.startsWith("#/jobs")) {
      params.set("q", query);
    }

    const endpoint = route.startsWith("#/jobs")
      ? `/api/v1/jobs?limit=50&${params.toString()}`
      : route.startsWith("#/admin")
        ? "/api/v1/admin/duplicates?limit=50"
        : "/api/v1/analytics/overview";

    api(endpoint).then(setPayload).catch((err) => setError(err.message));
  }, [route, query]);

  return (
    <div className={selected ? "app-shell inspector-open" : "app-shell"}>
      <Sidebar
        route={route}
        query={query}
        setQuery={setQuery}
        dark={dark}
        setDark={setDark}
      />
      <main className="workspace">
        {error && <div className="notice error">{error}</div>}
        {!payload && !error && <LoadingState />}
        {payload && route.startsWith("#/jobs") && (
          <JobsView payload={payload} setSelected={setSelected} />
        )}
        {payload && route.startsWith("#/admin") && (
          <AdminView payload={payload} setSelected={setSelected} />
        )}
        {payload &&
          !route.startsWith("#/jobs") &&
          !route.startsWith("#/admin") && (
            <OverviewView
              payload={payload}
              route={route}
              setSelected={setSelected}
            />
          )}
      </main>
      <Inspector selected={selected} setSelected={setSelected} />
    </div>
  );
}

function Sidebar({ route, query, setQuery, dark, setDark }) {
  return (
    <aside className="sidebar">
      <div className="brand-lockup">
        <div className="brand-mark">
          <Activity size={20} strokeWidth={2.3} />
        </div>
        <div>
          <div className="brand">RoleRadar</div>
          <div className="brand-subtitle">SG labour signals</div>
        </div>
      </div>

      <nav className="nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <a
              href={item.href}
              className={route.startsWith(item.href) ? "active" : ""}
              key={item.href}
            >
              <Icon size={17} />
              <span>{item.label}</span>
            </a>
          );
        })}
      </nav>

      <div className="sidebar-section">
        <div className="section-label">Global Search</div>
        <label className="search-box">
          <Search size={16} />
          <input
            value={query}
            onInput={(event) => setQuery(event.target.value)}
            placeholder="role, company, skill"
          />
        </label>
      </div>

      <div className="sidebar-footer">
        <button className="utility-button" onClick={() => setDark(!dark)}>
          {dark ? <Sun size={16} /> : <Moon size={16} />}
          <span>{dark ? "Light mode" : "Dark mode"}</span>
        </button>
      </div>
    </aside>
  );
}

function OverviewView({ payload, route, setSelected }) {
  const data = payload.data;
  const isExplorer = route.startsWith("#/explorer");

  return (
    <>
      <PageHeader
        eyebrow={isExplorer ? "Unified Explorer" : "Market Overview"}
        title={
          isExplorer
            ? "Browse current demand by skill, source, and salary signal"
            : "Singapore job-market intelligence"
        }
        meta={`${payload.meta.total_records_in_db} source listings`}
        actions={<CsvActions />}
      />

      <section className="kpi-strip">
        <Metric
          label="Canonical jobs"
          value={data.kpis.canonical_jobs}
          icon={BriefcaseBusiness}
          onClick={() => setSelected(metricDetail("Canonical jobs", data.kpis))}
        />
        <Metric
          label="Companies"
          value={data.kpis.companies}
          icon={Building2}
          onClick={() => setSelected(metricDetail("Companies", data.kpis))}
        />
        <Metric
          label="Skills"
          value={data.kpis.skills}
          icon={Database}
          onClick={() => setSelected(metricDetail("Skills", data.kpis))}
        />
        <Metric
          label="Salary coverage"
          value={data.kpis.salary_disclosure_rate}
          icon={Gauge}
          formatter={formatValue}
          tone="amber"
          onClick={() => setSelected(data.salary.coverage)}
        />
      </section>

      <section className="analysis-grid">
        <SkillChart rows={data.top_skills} />
        <ListPanel
          title="Source Quality"
          subtitle="Full-text availability by source"
          rows={data.skill_extraction_coverage}
          label="source"
          value="full_text_rate"
          formatter={(value) => `${Math.round(value * 100)}%`}
        />
      </section>

      <section className="analysis-grid secondary">
        <ListPanel
          title="Salary Coverage"
          subtitle="Employer-disclosed salary share"
          rows={data.salary.by_source}
          label="group"
          value="disclosure_rate"
          formatter={(value) => `${Math.round(value * 100)}%`}
        />
        <ListPanel
          title="Recent Ingestion Runs"
          subtitle="Latest local pipeline activity"
          rows={data.recent_ingestion_runs}
          label="source"
          value="status"
        />
      </section>

      <footer className="meta-line">
        Generated {new Date(payload.meta.generated_at).toLocaleString()}.{" "}
        {data.trend_caveat}
      </footer>
    </>
  );
}

function SkillChart({ rows }) {
  const canvasRef = React.useRef(null);

  React.useEffect(() => {
    if (!canvasRef.current || !rows.length) return undefined;
    const chart = new Chart(canvasRef.current, {
      type: "bar",
      data: {
        labels: rows.map((row) => row.skill_name),
        datasets: [
          {
            label: "Active jobs",
            data: rows.map((row) => row.job_count),
            borderRadius: 6,
            backgroundColor: "#0d9488",
            hoverBackgroundColor: "#2563eb",
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: "rgba(100, 116, 139, 0.16)" } },
          y: { grid: { display: false } },
        },
      },
    });
    return () => chart.destroy();
  }, [rows]);

  return (
    <section className="panel chart-panel">
      <PanelHeader
        title="Top Skills"
        subtitle="Current active canonical job count"
      />
      {rows.length ? (
        <div className="chart-box">
          <canvas ref={canvasRef} />
        </div>
      ) : (
        <EmptyState text="No job data detected. Run roleradar ingest or review Admin imports." />
      )}
    </section>
  );
}

function JobsView({ payload, setSelected }) {
  const rows = payload.data.items;

  return (
    <>
      <PageHeader
        eyebrow="Evidence Browser"
        title="Inspect the listings behind every signal"
        meta={`${payload.data.total} listings`}
        actions={<CsvActions />}
      />
      {!rows.length ? (
        <EmptyState text="No results match active filters. Try clearing search fields." />
      ) : (
        <div className="table-shell">
          <table>
            <thead>
              <tr>
                <th>Role</th>
                <th>Company</th>
                <th>Source</th>
                <th>Salary</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.source_listing_id} onClick={() => setSelected(item)}>
                  <td>
                    <strong>{item.title}</strong>
                    <span>{item.location || "Location unavailable"}</span>
                  </td>
                  <td>{item.company_name || "UNKNOWN"}</td>
                  <td>
                    <span className="badge">{item.source}</span>
                  </td>
                  <td>{formatSalary(item)}</td>
                  <td>
                    {item.last_seen_at
                      ? new Date(item.last_seen_at).toLocaleDateString()
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function AdminView({ payload, setSelected }) {
  const rows = payload.data.items;

  return (
    <>
      <PageHeader
        eyebrow="Admin"
        title="Review ingestion and duplicate quality gates"
        meta={`${payload.data.total} pending candidates`}
      />
      {!rows.length ? (
        <EmptyState text="No pending duplicate candidates." />
      ) : (
        <section className="panel">
          <PanelHeader
            title="Duplicate Candidates"
            subtitle="Manual review queue for cross-source matches"
          />
          <div className="review-list">
            {rows.map((row) => (
              <button
                className="review-row"
                key={row.id}
                onClick={() => setSelected(row)}
              >
                <span>
                  <strong>{row.job.title}</strong>
                  <small>{row.candidate_job.title}</small>
                </span>
                <span className="score">{Math.round(row.score * 100)}%</span>
                <span className="badge muted">{row.status}</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

function CsvActions() {
  return (
    <div className="header-actions">
      <a className="action-button" href="/api/v1/jobs/export.csv" target="_blank">
        <Database size={16} />
        <span>Open CSV</span>
      </a>
      <a className="action-button primary" href="/api/v1/jobs/export.csv" download>
        <Download size={16} />
        <span>Download</span>
      </a>
    </div>
  );
}

function PageHeader({ eyebrow, title, meta, actions }) {
  return (
    <header className="page-header">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
      </div>
      <div className="page-header-side">
        <span className="header-meta">{meta}</span>
        {actions}
      </div>
    </header>
  );
}

function Metric({ label, value, icon: Icon, formatter = formatNumber, tone, onClick }) {
  return (
    <button className={`metric ${tone || ""}`} onClick={onClick}>
      <span className="metric-icon">
        <Icon size={18} />
      </span>
      <span className="metric-label">{label}</span>
      <strong>{formatter(value)}</strong>
    </button>
  );
}

function PanelHeader({ title, subtitle }) {
  return (
    <div className="panel-header">
      <div>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

function ListPanel({ title, subtitle, rows, label, value, formatter = formatValue }) {
  return (
    <section className="panel">
      <PanelHeader title={title} subtitle={subtitle} />
      {!rows.length ? (
        <EmptyState text="No data available." />
      ) : (
        <div className="signal-list">
          {rows.map((row, index) => (
            <div className="signal-row" key={`${title}-${index}`}>
              <span>{row[label] == null ? "UNKNOWN" : row[label]}</span>
              <strong>{formatter(row[value])}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function Inspector({ selected, setSelected }) {
  return (
    <aside className="inspector">
      {selected && (
        <>
          <div className="inspector-header">
            <div>
              <span>Inspector</span>
              <strong>{selected.title || selected.key || selected.status || "Details"}</strong>
            </div>
            <button className="icon-button" onClick={() => setSelected(null)} title="Close">
              <X size={18} />
            </button>
          </div>
          <div className="inspector-body">
            {Object.entries(selected).map(([key, value]) => (
              <div className="detail-block" key={key}>
                <span>{key.replaceAll("_", " ")}</span>
                <strong>{formatDetail(value)}</strong>
              </div>
            ))}
          </div>
        </>
      )}
    </aside>
  );
}

function LoadingState() {
  return (
    <div className="loading-state">
      <Activity size={22} />
      <span>Loading RoleRadar data...</span>
    </div>
  );
}

function EmptyState({ text }) {
  return <div className="empty-state">{text}</div>;
}

function metricDetail(key, values) {
  return { key, ...values };
}

function formatNumber(value) {
  if (typeof value !== "number") return String(value ?? "");
  return new Intl.NumberFormat("en-SG").format(value);
}

function formatValue(value) {
  if (typeof value !== "number") return String(value ?? "");
  if (value > 0 && value < 1) return `${Math.round(value * 100)}%`;
  return formatNumber(value);
}

function formatSalary(item) {
  if (item.salary_min == null && item.salary_max == null) return "Not disclosed";
  return `${item.salary_currency || ""} ${item.salary_min || ""}-${item.salary_max || ""}`.trim();
}

function formatDetail(value) {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

createRoot(document.getElementById("root")).render(<App />);
