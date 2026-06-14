const manifestUrl = new URL("../sources.manifest.json", window.location.href).href;
const metadataLogUrls = [
  new URL("../metadata/downloads.jsonl", window.location.href).href,
  new URL("../metadata/skipped.jsonl", window.location.href).href,
  new URL("../metadata/errors.jsonl", window.location.href).href,
];
const layoutLines = [
  "karpathy-corpus/",
  "  README.md",
  "  sources.manifest.json",
  "  metadata/  -> run logs and skips",
  "  raw/       -> normalized Markdown, PDFs, transcripts",
  "  sources/   -> staged HTML, repos, and subtitles",
  "  scripts/   -> ingestion and normalization",
  "  tests/     -> parser fixtures and goldens",
];

const pipeline = [
  {
    title: "Collect",
    copy: "Fetch stable public sources: blogs, talks, course pages, Git repos, and papers.",
  },
  {
    title: "Stage",
    copy: "Keep fetched pages and subtitles in source form so every normalized file can be traced back.",
  },
  {
    title: "Normalize",
    copy: "Render HTML into Markdown and captions into a single transcript JSON schema.",
  },
  {
    title: "Record",
    copy: "Emit run logs, skip logs, and source metadata for reproducibility.",
  },
];

const state = {
  manifest: [],
  bucketFilter: "all",
  query: "",
  statusMap: {},
};

const els = {
  stats: document.getElementById("stats"),
  pipeline: document.getElementById("pipeline"),
  buckets: document.getElementById("buckets"),
  sources: document.getElementById("sources"),
  layout: document.getElementById("layout"),
  filter: document.getElementById("filter"),
  chips: Array.from(document.querySelectorAll(".chip")),
  manifestMeta: document.getElementById("manifest-meta"),
};

function kindLabel(kind) {
  return {
    url: "HTML/PDF",
    youtube: "YouTube",
    git: "Git",
    copy_tree: "Copy",
  }[kind] ?? kind;
}

function renderStats(manifest) {
  const counts = manifest.reduce(
    (acc, source) => {
      acc.total += 1;
      acc[source.kind] = (acc[source.kind] ?? 0) + 1;
      return acc;
    },
    { total: 0 }
  );
  const ingested = manifest.filter((source) => state.statusMap[source.id]?.status === "ok").length;

  const cards = [
    ["Sources", counts.total, "Tracked in the manifest"],
    ["Ingested", `${ingested} / ${counts.total}`, "Sources with status: ok"],
    ["HTML/PDF", counts.url ?? 0, "Rendered to Markdown or stored as PDFs"],
    ["YouTube", counts.youtube ?? 0, "Normalized transcripts"],
    ["Repos", counts.git ?? 0, "Cloned source trees"],
  ];

  els.stats.innerHTML = cards
    .map(
      ([label, value, note]) => `
        <article class="stat">
          <span class="stat-label">${label}</span>
          <span class="stat-value">${value}</span>
          <span class="stat-note">${note}</span>
        </article>`
    )
    .join("");
}

function parseJsonl(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

function mergeStatusRecord(statusMap, record) {
  if (!record || !record.id) {
    return;
  }
  const current = statusMap[record.id];
  const nextTimestamp = record.timestamp ?? "";
  const currentTimestamp = current?.timestamp ?? "";
  if (!current || nextTimestamp >= currentTimestamp) {
    statusMap[record.id] = record;
  }
}

async function loadSourceStatusMap() {
  const statusMap = {};
  for (const logUrl of metadataLogUrls) {
    try {
      const response = await fetch(logUrl, { cache: "no-store" });
      if (!response.ok) {
        continue;
      }
      const text = await response.text();
      for (const record of parseJsonl(text)) {
        mergeStatusRecord(statusMap, record);
      }
    } catch {
      continue;
    }
  }
  return statusMap;
}

function statusBadgeForSource(source) {
  const record = state.statusMap[source.id];
  if (!record) {
    return { label: "Not run", className: "badge badge--neutral" };
  }

  if (record.status === "ok") {
    return { label: "Ingested", className: "badge badge--ok" };
  }

  if (record.status === "dry-run") {
    return { label: "Dry run", className: "badge badge--neutral" };
  }

  if (record.status === "skipped") {
    const reason = String(record.reason ?? "").toLowerCase();
    if (reason.includes("already exists")) {
      return { label: "Cached", className: "badge badge--muted" };
    }
    if (reason.includes("not available") || reason.includes("unavailable")) {
      return { label: "Tool missing", className: "badge badge--warn" };
    }
    return { label: "Skipped", className: "badge badge--muted" };
  }

  if (record.status === "error") {
    const label = record.error_code ?? String(record.error ?? "Error").slice(0, 60);
    return { label, className: "badge badge--error" };
  }

  return { label: String(record.status ?? "Unknown"), className: "badge badge--neutral" };
}

function renderPipeline() {
  els.pipeline.innerHTML = pipeline
    .map(
      (step, index) => `
        <li>
          <span class="pipeline-index">${index + 1}</span>
          <div>
            <div class="pipeline-title">${step.title}</div>
            <div class="pipeline-copy">${step.copy}</div>
          </div>
        </li>`
    )
    .join("");
}

function renderBuckets(manifest) {
  const grouped = manifest.reduce((acc, source) => {
    const bucket = source.bucket ?? "uncategorized";
    acc[bucket] = acc[bucket] ?? [];
    acc[bucket].push(source);
    return acc;
  }, {});

  const order = ["github-blog", "courses", "transcripts", "papers", "github", "bear-blog", "medium"];
  const buckets = Object.keys(grouped).sort((a, b) => {
    const ai = order.indexOf(a);
    const bi = order.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });

  els.buckets.innerHTML = buckets
    .map(
      (bucket) => `
        <article class="bucket-card">
          <div class="bucket-header">
            <div class="bucket-name">${bucket}</div>
            <div class="bucket-count">${grouped[bucket].length}</div>
          </div>
          <p>${bucketDescription(bucket)}</p>
        </article>`
    )
    .join("");
}

function bucketDescription(bucket) {
  return {
    "github-blog": "Original blog posts and the cloned Jekyll source.",
    courses: "Course notes and lecture playlists for Zero to Hero and CS231n.",
    transcripts: "YouTube talks and channel pulls normalized into transcript JSON.",
    papers: "Publications and PDFs linked from Karpathy's official site.",
    github: "Project repositories and supporting source trees.",
    "bear-blog": "Current blog index and normalized page capture.",
    medium: "Legacy Medium writing captured in the corpus.",
  }[bucket] ?? "Corpus source group.";
}

function renderManifestMeta(manifest) {
  const byKind = manifest.reduce((acc, source) => {
    acc[source.kind] = (acc[source.kind] ?? 0) + 1;
    return acc;
  }, {});
  els.manifestMeta.textContent = `${manifest.length} sources across ${Object.keys(byKind).length} kinds`;
}

function renderSources(manifest) {
  const filtered = manifest.filter((source) => {
    const kindMatches = state.bucketFilter === "all" || source.kind === state.bucketFilter;
    const query = state.query.trim().toLowerCase();
    const text = JSON.stringify(source).toLowerCase();
    const queryMatches = !query || text.includes(query);
    return kindMatches && queryMatches;
  });

  els.sources.innerHTML = filtered
    .map((source) => {
      const status = statusBadgeForSource(source);
      const extras = [
        source.output ? `output: ${source.output}` : null,
        source.staging_template ? `stage: ${source.staging_template}` : null,
        source.transcript_output ? `transcript: ${source.transcript_output}` : null,
        source.source_dir ? `source_dir: ${source.source_dir}` : null,
      ]
        .filter(Boolean)
        .join(" · ");

      return `
        <article class="source-card">
          <div class="source-topline">
            <div class="source-id">${escapeHtml(source.id)}</div>
            <div class="badge-row">
              <div class="badge badge--kind">${escapeHtml(kindLabel(source.kind))}</div>
              <div class="${status.className}">${escapeHtml(status.label)}</div>
            </div>
          </div>
          <div class="source-url">${escapeHtml(source.url ?? "(local copy)")}</div>
          <div class="source-extra">${escapeHtml(extras)}</div>
        </article>`;
    })
    .join("");

  if (!filtered.length) {
    els.sources.innerHTML = `<article class="source-card"><p>No sources matched the current filter.</p></article>`;
  }
}

async function loadManifest() {
  try {
    const response = await fetch(manifestUrl, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load manifest: ${response.status}`);
    }
    const data = await response.json();
    state.manifest = data.sources ?? [];
    renderBuckets(state.manifest);
    renderManifestMeta(state.manifest);
    renderStats(state.manifest);
    renderSources(state.manifest);
    state.statusMap = await loadSourceStatusMap();
    renderStats(state.manifest);
    renderSources(state.manifest);
  } catch (error) {
    els.sources.innerHTML = `
      <article class="source-card">
        <p>Unable to load manifest from <span class="source-url">${manifestUrl}</span>.</p>
        <p class="source-extra">${error.message}</p>
      </article>`;
  }
}

function bindUI() {
  els.layout.textContent = layoutLines.join("\n");

  els.filter.addEventListener("input", (event) => {
    state.query = event.target.value;
    renderSources(state.manifest);
  });

  els.chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      state.bucketFilter = chip.dataset.kind;
      els.chips.forEach((item) => item.classList.toggle("is-active", item === chip));
      renderSources(state.manifest);
    });
  });
}

bindUI();
loadManifest();
