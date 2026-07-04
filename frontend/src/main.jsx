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
  Loader2,
  Moon,
  Play,
  Search,
  ShieldCheck,
  Sun,
  X,
} from "lucide-react";
import "./styles.css";

const api = async (path, options) => {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await response.json()
    : null;
  if (!response.ok) {
    throw new Error(body?.detail || `${response.status} ${response.statusText}`);
  }
  return body;
};

const navItems = [
  { href: "#/overview", label: "Overview", icon: BarChart3 },
  { href: "#/explorer", label: "Explorer", icon: Gauge },
  { href: "#/jobs", label: "Evidence", icon: BriefcaseBusiness },
  { href: "#/load", label: "Load Sources", icon: Database },
  { href: "#/admin", label: "Admin", icon: ShieldCheck },
];

const sourceOptions = [
  { value: "all", label: "All query-capable sources" },
  { value: "careers_gov", label: "MyCareersFuture" },
  { value: "jobstreet", label: "JobStreet" },
  { value: "adzuna", label: "Adzuna" },
];

const customRoleFamilyPrefix = "custom:";
const customRoleFamilyAcronyms = new Map([
  ["ai", "AI"],
  ["api", "API"],
  ["bi", "BI"],
  ["crm", "CRM"],
  ["devops", "DevOps"],
  ["llm", "LLM"],
  ["ml", "ML"],
  ["nlp", "NLP"],
  ["qa", "QA"],
  ["sre", "SRE"],
  ["ui", "UI"],
  ["ux", "UX"],
]);

function App() {
  const [route, setRoute] = React.useState(window.location.hash || "#/overview");
  const [query, setQuery] = React.useState("");
  const [roleFamily, setRoleFamily] = React.useState("");
  const [overviewRoleFamily, setOverviewRoleFamily] = React.useState("");
  const [roleFamilies, setRoleFamilies] = React.useState([]);
  const [payload, setPayload] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [dark, setDark] = React.useState(
    window.localStorage.getItem("roleradar.theme") === "dark",
  );
  const routeSection = getRouteSection(route);
  const payloadKey = getPayloadKey(
    routeSection,
    query,
    roleFamily,
    overviewRoleFamily,
  );
  const viewPayload =
    payload?.routeSection === routeSection && payload?.key === payloadKey
      ? payload.response
      : null;

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
    if (
      !route.startsWith("#/jobs") &&
      !route.startsWith("#/overview") &&
      !route.startsWith("#/explorer") &&
      !route.startsWith("#/load")
    ) {
      return;
    }
    let isCurrent = true;
    const controller = new AbortController();

    const includeEmpty = route.startsWith("#/load") ? "&include_empty=true" : "";
    api(`/api/v1/role-families?limit=100${includeEmpty}`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (isCurrent) setRoleFamilies(response.data.items || []);
      })
      .catch((err) => {
        if (isCurrent && err.name !== "AbortError") setRoleFamilies([]);
      });

    return () => {
      isCurrent = false;
      controller.abort();
    };
  }, [route, viewPayload?.meta?.freshness_timestamp]);

  React.useEffect(() => {
    let isCurrent = true;
    const controller = new AbortController();

    setError(null);
    setPayload(null);

    if (route.startsWith("#/load")) {
      return () => {
        isCurrent = false;
        controller.abort();
      };
    }

    const params = new URLSearchParams();
    if (query && route.startsWith("#/jobs")) {
      params.set("q", query);
    }
    if (roleFamily && route.startsWith("#/jobs")) {
      params.set("role_family", roleFamily);
    }

    const overviewParams = new URLSearchParams();
    if (overviewRoleFamily && routeSection === "overview") {
      overviewParams.set("role_family", overviewRoleFamily);
    }

    const endpoint = route.startsWith("#/jobs")
      ? `/api/v1/jobs?limit=50&${params.toString()}`
      : route.startsWith("#/admin")
        ? "/api/v1/admin/duplicates?limit=50"
        : `/api/v1/analytics/overview${
            overviewParams.toString() ? `?${overviewParams.toString()}` : ""
          }`;

    api(endpoint, { signal: controller.signal })
      .then((response) => {
        if (isCurrent) setPayload({ routeSection, key: payloadKey, response });
      })
      .catch((err) => {
        if (isCurrent && err.name !== "AbortError") setError(err.message);
      });

    return () => {
      isCurrent = false;
      controller.abort();
    };
  }, [route, routeSection, payloadKey, query, roleFamily, overviewRoleFamily]);

  const isLoadRoute = route.startsWith("#/load");

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
        {!isLoadRoute && !viewPayload && !error && <LoadingState />}
          {isLoadRoute && (
            <LoadSourcesView setQuery={setQuery} roleFamilies={roleFamilies} />
          )}
        {viewPayload && route.startsWith("#/jobs") && (
          <JobsView
            payload={viewPayload}
            setSelected={setSelected}
            query={query}
            roleFamily={roleFamily}
            setRoleFamily={setRoleFamily}
            roleFamilies={roleFamilies}
          />
        )}
        {viewPayload && route.startsWith("#/admin") && (
          <AdminView
            payload={viewPayload}
            setPayload={(response) =>
              setPayload({ routeSection, key: payloadKey, response })
            }
            setSelected={setSelected}
          />
        )}
        {viewPayload &&
          !isLoadRoute &&
          !route.startsWith("#/jobs") &&
          !route.startsWith("#/admin") && (
            <OverviewView
              payload={viewPayload}
              route={route}
              setSelected={setSelected}
              selectedRoleFamily={overviewRoleFamily}
              setSelectedRoleFamily={setOverviewRoleFamily}
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

function LoadSourcesView({ setQuery, roleFamilies }) {
  const [source, setSource] = React.useState("careers_gov");
  const [role, setRole] = React.useState("AI engineer");
  const [roleFamily, setRoleFamily] = React.useState("");
  const [roleFamilyMode, setRoleFamilyMode] = React.useState("catalog");
  const [customRoleFamily, setCustomRoleFamily] = React.useState("");
  const [location, setLocation] = React.useState("Singapore");
  const [resultsPerPage, setResultsPerPage] = React.useState(20);
  const [maxPages, setMaxPages] = React.useState(1);
  const [result, setResult] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const resultRoleFamily = result
    ? roleFamilies.find((item) => item.id === result.data.role_family)
    : null;
  const selectedRoleFamilyId =
    roleFamilyMode === "custom"
      ? customRoleFamilyId(customRoleFamily)
      : roleFamily;
  const selectedRoleFamilyLabel =
    roleFamilyMode === "custom"
      ? normalizeCustomRoleFamilyLabel(customRoleFamily)
      : roleFamilies.find((item) => item.id === roleFamily)?.label;
  const canSubmit = Boolean(selectedRoleFamilyId);

  const submitLoad = async (event) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    setIsLoading(true);

    try {
      const response = await api("/api/v1/admin/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source,
          query: role,
          role_family: selectedRoleFamilyId,
          location,
          results_per_page: Number(resultsPerPage),
          max_pages: Number(maxPages),
        }),
      });
      setQuery(role);
      setResult(response);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Source Loader"
        title="Load role listings from job sources"
        meta="Search-driven ingestion"
      />

      <section className="load-grid">
        <form className="panel load-form" onSubmit={submitLoad}>
          <PanelHeader
            title="Load From Sources"
            subtitle="Choose a source, role query, canonical family, and page depth."
          />

          <div className="field-grid">
            <label className="field-control">
              <span>Source</span>
              <select
                value={source}
                onChange={(event) => setSource(event.target.value)}
              >
                {sourceOptions.map((option) => (
                  <option value={option.value} key={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="field-control">
              <span>Role query</span>
              <input
                value={role}
                onInput={(event) => setRole(event.target.value)}
                placeholder="AI engineer"
                required
              />
            </label>

            <label className="field-control">
              <span>Canonical role family</span>
              <select
                value={roleFamily}
                onChange={(event) => setRoleFamily(event.target.value)}
                disabled={roleFamilyMode === "custom"}
                required={roleFamilyMode === "catalog"}
              >
                <option value="">Select a role family</option>
                {roleFamilies.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="toggle-control">
              <input
                type="checkbox"
                checked={roleFamilyMode === "custom"}
                onChange={(event) =>
                  setRoleFamilyMode(event.target.checked ? "custom" : "catalog")
                }
              />
              <span>Define my own canonical role family</span>
            </label>

            {roleFamilyMode === "custom" && (
              <label className="field-control">
                <span>Custom family name</span>
                <input
                  value={customRoleFamily}
                  onInput={(event) => setCustomRoleFamily(event.target.value)}
                  placeholder="Data Platform"
                  required
                />
                <small className="field-hint">
                  {selectedRoleFamilyId
                    ? `Will be saved as ${selectedRoleFamilyId}`
                    : "Use letters or numbers so RoleRadar can create a stable family ID."}
                </small>
              </label>
            )}

            <label className="field-control">
              <span>Location</span>
              <input
                value={location}
                onInput={(event) => setLocation(event.target.value)}
                placeholder="Singapore"
              />
            </label>

            <div className="field-row">
              <label className="field-control">
                <span>Results per page</span>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={resultsPerPage}
                  onInput={(event) => setResultsPerPage(event.target.value)}
                />
              </label>

              <label className="field-control">
                <span>Pages</span>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={maxPages}
                  onInput={(event) => setMaxPages(event.target.value)}
                />
              </label>
            </div>
          </div>

          <div className="form-actions">
            <button
              className="action-button primary"
              disabled={isLoading || !canSubmit}
            >
              {isLoading ? <Loader2 size={16} /> : <Play size={16} />}
              <span>{isLoading ? "Loading" : "Load Listings"}</span>
            </button>
            {result && (
              <a className="action-button" href="#/jobs">
                <BriefcaseBusiness size={16} />
                <span>View Evidence</span>
              </a>
            )}
          </div>
        </form>

        <section className="panel">
          <PanelHeader
            title="Run Result"
            subtitle="Per-source ingestion summary for this request."
          />

          {error && <div className="notice error compact">{error}</div>}

          {!result && !error && (
            <EmptyState text="No source load has been run yet." />
          )}

          {result && (
            <div className="result-list">
              <div className="result-summary">
                <strong>{formatNumber(result.data.source_listings_upserted)}</strong>
                <span>source listings upserted</span>
                <span>
                  Assigned to{" "}
                  {result.data.role_family_label ||
                    resultRoleFamily?.label ||
                    roleFamilyLabel(result.data.role_family, roleFamilies) ||
                    selectedRoleFamilyLabel ||
                    "Unknown"}
                </span>
              </div>
              {result.data.results.map((item) => (
                <div className="result-row" key={item.source}>
                  <span>
                    <strong>{sourceLabel(item.source)}</strong>
                    <small>{item.error_message || `${item.jobs_seen} jobs seen`}</small>
                  </span>
                  <span className={`badge ${item.status === "completed" ? "" : "muted"}`}>
                    {item.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </section>
    </>
  );
}

function OverviewView({
  payload,
  route,
  setSelected,
  selectedRoleFamily,
  setSelectedRoleFamily,
}) {
  const data = payload.data;
  const isExplorer = route.startsWith("#/explorer");
  const selectedRole = data.selected_role_family;

  return (
    <>
      <PageHeader
        eyebrow={isExplorer ? "Unified Explorer" : "Market Overview"}
        title={
          isExplorer
            ? "Browse current demand by skill, source, and salary signal"
            : "Singapore job-market intelligence"
        }
        meta={
          selectedRole
            ? `${selectedRole.label} · ${formatNumber(data.kpis.source_listings)} source listings`
            : `${payload.meta.total_records_in_db} source listings`
        }
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

      <RoleFamiliesPanel
        rows={data.role_families || []}
        selectedRoleFamily={selectedRoleFamily}
        setSelectedRoleFamily={setSelectedRoleFamily}
        setSelected={setSelected}
      />

      <section className="analysis-grid">
        <SkillChart rows={data.top_skills} roleFamily={selectedRole} />
        <HiringCompaniesPanel
          rows={data.top_hiring_companies || []}
          roleFamily={selectedRole}
          setSelected={setSelected}
        />
      </section>

      <section className="analysis-grid secondary">
        <ListPanel
          title="Source Quality"
          subtitle="Full-text availability by source"
          rows={data.skill_extraction_coverage}
          label="source"
          value="full_text_rate"
          formatter={(value) => `${Math.round(value * 100)}%`}
        />
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

function RoleFamiliesPanel({
  rows,
  selectedRoleFamily,
  setSelectedRoleFamily,
  setSelected,
}) {
  const selectedRow = rows.find((row) => row.id === selectedRoleFamily);

  return (
    <section className="panel role-family-panel">
      <PanelHeader
        title="Canonical Role Families"
        subtitle="Normalized demand across messy source titles"
      />

      <div className="role-family-toolbar">
        <label className="field-control">
          <span>Analyze family</span>
          <select
            value={selectedRoleFamily}
            onChange={(event) => setSelectedRoleFamily(event.target.value)}
          >
            <option value="">All canonical role families</option>
            {rows.map((row) => (
              <option value={row.id} key={row.id}>
                {row.label}
              </option>
            ))}
          </select>
        </label>
        {selectedRow && (
          <button
            className="action-button"
            onClick={() => setSelectedRoleFamily("")}
          >
            <span>Clear filter</span>
          </button>
        )}
      </div>

      {!rows.length ? (
        <EmptyState text="No role-family signals yet. Load listings to classify role demand." />
      ) : (
        <div className="role-family-list">
          {rows.map((row) => (
            <button
              className={`role-family-row ${
                row.id === selectedRoleFamily ? "active" : ""
              }`}
              key={row.id}
              onClick={() => setSelectedRoleFamily(row.id)}
              onDoubleClick={() => setSelected(row)}
            >
              <span className="role-family-main">
                <strong>{row.label}</strong>
                <small>{roleFamilySubtitle(row)}</small>
              </span>
              <span className="role-family-metric">
                <strong>{formatNumber(row.job_count)}</strong>
                <small>jobs</small>
              </span>
              <span className="role-family-metric">
                <strong>{formatNumber(row.company_count)}</strong>
                <small>companies</small>
              </span>
              <span className="role-family-metric salary">
                <strong>{formatAnnualSalary(row.average_annualized_salary)}</strong>
                <small>avg salary</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function HiringCompaniesPanel({ rows, roleFamily, setSelected }) {
  return (
    <section className="panel">
      <PanelHeader
        title={roleFamily ? `Top Hiring Companies: ${roleFamily.label}` : "Top Hiring Companies"}
        subtitle={
          roleFamily
            ? "Ranked within the selected canonical role family"
            : "Ranked by active canonical jobs"
        }
      />

      {!rows.length ? (
        <EmptyState text="No company hiring signals yet." />
      ) : (
        <div className="hiring-company-list">
          {rows.map((row) => (
            <button
              className="hiring-company-row"
              key={row.company_name}
              onClick={() => setSelected({ key: row.company_name, ...row })}
            >
              <span className="hiring-company-main">
                <strong>{row.company_name || "UNKNOWN"}</strong>
                <small>{hiringCompanySubtitle(row)}</small>
              </span>
              <span className="hiring-company-metric">
                <strong>{formatNumber(row.job_count)}</strong>
                <small>jobs</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function SkillChart({ rows, roleFamily }) {
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
        title={roleFamily ? `Top Skills: ${roleFamily.label}` : "Top Skills"}
        subtitle={
          roleFamily
            ? "Current active jobs in the selected canonical role family"
            : "Current active canonical job count"
        }
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

function JobsView({
  payload,
  setSelected,
  query,
  roleFamily,
  setRoleFamily,
  roleFamilies,
}) {
  const rows = payload.data.items;

  return (
    <>
      <PageHeader
        eyebrow="Evidence Browser"
        title="Inspect the listings behind every signal"
        meta={`${payload.data.total} listings`}
        actions={<CsvActions query={query} roleFamily={roleFamily} />}
      />
      <section className="panel evidence-filter-panel">
        <div className="evidence-filters">
          <label className="field-control">
            <span>Role family</span>
            <select
              value={roleFamily}
              onChange={(event) => setRoleFamily(event.target.value)}
            >
              <option value="">All role families</option>
              {roleFamilies.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <div className="filter-summary">
            <strong>{formatNumber(payload.data.total)}</strong>
            <span>matching listings</span>
          </div>
        </div>
      </section>

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
                <th>Structured sections</th>
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
                  <td>
                    <SectionBadges item={item} />
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

function SectionBadges({ item }) {
  const sections = [
    ["Responsibilities", item.responsibilities],
    ["Required", item.required_competencies_and_certifications],
    ["Preferred", item.preferred_competencies_and_qualifications],
  ].filter(([, value]) => Boolean(value));

  if (!sections.length) {
    return <span className="muted-text">None parsed</span>;
  }

  return (
    <div className="section-badges">
      {sections.map(([label, value]) => (
        <span className="section-chip" title={value} key={label}>
          {label}
        </span>
      ))}
    </div>
  );
}

function AdminView({ payload, setPayload, setSelected }) {
  const rows = payload.data.items;
  const duplicateListingGroups =
    (payload.data.source_listing_duplicate_groups || 0) +
    (payload.data.field_duplicate_listing_groups || 0);
  const [dedupeResult, setDedupeResult] = React.useState(null);
  const [dedupeError, setDedupeError] = React.useState(null);
  const [isDeduping, setIsDeduping] = React.useState(false);

  const runSourceListingDedupe = async () => {
    setDedupeError(null);
    setDedupeResult(null);
    setIsDeduping(true);
    try {
      const response = await api("/api/v1/admin/source-listings/dedupe", {
        method: "POST",
      });
      setDedupeResult(response.data);
      const refreshed = await api("/api/v1/admin/duplicates?limit=50");
      setPayload(refreshed);
    } catch (err) {
      setDedupeError(err.message);
    } finally {
      setIsDeduping(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Admin"
        title="Review ingestion and duplicate quality gates"
        meta={`${payload.data.total} pending candidates`}
      />
      <section className="panel">
        <PanelHeader
          title="Dedupe Scan"
          subtitle="Repair exact source IDs and detect cross-source duplicate candidates"
        />
        <div className="result-list">
          <div className="result-summary">
            <strong>{formatNumber(duplicateListingGroups)}</strong>
            <span>duplicate listing groups</span>
          </div>
          <div className="form-actions">
            <button
              className="action-button primary"
              onClick={runSourceListingDedupe}
              disabled={isDeduping}
            >
              {isDeduping ? <Loader2 size={16} /> : <Database size={16} />}
              <span>{isDeduping ? "Deduping" : "Run Dedupe"}</span>
            </button>
          </div>
          {dedupeError && (
            <div className="notice error compact">{dedupeError}</div>
          )}
          {dedupeResult && (
            <>
              <div className="result-row">
                <span>
                  <strong>
                    {formatNumber(dedupeResult.duplicate_candidates_created || 0)}
                  </strong>
                  <small>
                    duplicate candidates created,{" "}
                    {formatNumber(
                      dedupeResult.duplicate_candidates_refreshed || 0,
                    )}{" "}
                    refreshed
                  </small>
                </span>
                <span className="badge">
                  {formatNumber(dedupeResult.duplicate_candidate_pairs_found || 0)}{" "}
                  matches
                </span>
              </div>
              <div className="result-row">
                <span>
                  <strong>
                    {formatNumber(dedupeResult.source_listings_removed)}
                  </strong>
                  <small>
                    source listings removed,{" "}
                    {formatNumber(dedupeResult.observations_moved)} observations moved
                  </small>
                </span>
                <span className="badge">
                  {formatNumber(
                    (dedupeResult.groups_merged || 0) +
                      (dedupeResult.field_groups_merged || 0),
                  )}{" "}
                  groups
                </span>
              </div>
            </>
          )}
        </div>
      </section>
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

function CsvActions({ query = "", roleFamily = "" } = {}) {
  const exportParams = new URLSearchParams();
  if (query) exportParams.set("q", query);
  if (roleFamily) exportParams.set("role_family", roleFamily);
  const exportUrl = `/api/v1/jobs/export.csv${
    exportParams.toString() ? `?${exportParams.toString()}` : ""
  }`;

  return (
    <div className="header-actions">
      <a className="action-button" href={exportUrl} target="_blank">
        <Database size={16} />
        <span>Open CSV</span>
      </a>
      <a className="action-button primary" href={exportUrl} download>
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
  const sectionEntries = selected ? structuredSectionEntries(selected) : [];
  const sectionKeys = new Set(sectionEntries.map(([key]) => key));

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
          {!!sectionEntries.length && (
            <div className="inspector-sections">
              {sectionEntries.map(([key, label, value]) => (
                <div className="section-detail" key={key}>
                  <span>{label}</span>
                  <p>{value}</p>
                </div>
              ))}
            </div>
          )}
          <div className="inspector-body">
            {Object.entries(selected)
              .filter(([key]) => !sectionKeys.has(key))
              .map(([key, value]) => (
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

function getRouteSection(route) {
  if (route.startsWith("#/jobs")) return "jobs";
  if (route.startsWith("#/admin")) return "admin";
  if (route.startsWith("#/load")) return "load";
  return "overview";
}

function getPayloadKey(routeSection, query, roleFamily, overviewRoleFamily) {
  if (routeSection === "jobs") return `jobs:${query}:${roleFamily}`;
  if (routeSection === "overview") return `overview:${overviewRoleFamily}`;
  return routeSection;
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

function formatAnnualSalary(value) {
  if (typeof value !== "number") return "n/a";
  return `SGD ${new Intl.NumberFormat("en-SG", {
    maximumFractionDigits: 0,
  }).format(value)}`;
}

function roleFamilySubtitle(row) {
  const skills = (row.top_skills || [])
    .slice(0, 3)
    .map((item) => item.skill_name)
    .join(", ");
  const sources = (row.top_sources || [])
    .slice(0, 2)
    .map((item) => item.source)
    .join(", ");
  if (skills && sources) return `${skills} · ${sources}`;
  return skills || sources || (row.example_titles || []).slice(0, 2).join(", ");
}

function hiringCompanySubtitle(row) {
  const roles = (row.top_role_families || [])
    .slice(0, 2)
    .map((item) => item.role_family)
    .join(", ");
  const listingCount = formatNumber(row.source_listing_count || 0);
  if (roles) return `${roles} · ${listingCount} source listings`;
  return `${listingCount} source listings`;
}

function formatDetail(value) {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function sourceLabel(value) {
  const option = sourceOptions.find((item) => item.value === value);
  return option ? option.label : value;
}

function normalizeCustomRoleFamilyLabel(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function customRoleFamilyId(value) {
  const slug = normalizeCustomRoleFamilyLabel(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 120);
  return slug ? `${customRoleFamilyPrefix}${slug}` : "";
}

function roleFamilyLabel(roleFamilyId, roleFamilies = []) {
  const catalogRole = roleFamilies.find((item) => item.id === roleFamilyId);
  if (catalogRole) return catalogRole.label;
  if (!roleFamilyId?.startsWith(customRoleFamilyPrefix)) return roleFamilyId;
  const slug = roleFamilyId.slice(customRoleFamilyPrefix.length);
  if (!/^[a-z0-9]+(?:_[a-z0-9]+)*$/.test(slug)) return roleFamilyId;
  return slug
    .split("_")
    .map((word) => customRoleFamilyAcronyms.get(word) || capitalize(word))
    .join(" ");
}

function capitalize(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function structuredSectionEntries(item) {
  return [
    ["responsibilities", "Responsibilities", item.responsibilities],
    [
      "required_competencies_and_certifications",
      "Required competencies and certifications",
      item.required_competencies_and_certifications,
    ],
    [
      "preferred_competencies_and_qualifications",
      "Preferred competencies and qualifications",
      item.preferred_competencies_and_qualifications,
    ],
  ].filter(([, , value]) => Boolean(value));
}

createRoot(document.getElementById("root")).render(<App />);
