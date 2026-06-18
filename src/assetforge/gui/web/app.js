let bridge = null;
let state = {};
const logLines = [];
let viewportUrl = null;
let viewportFrame = 0;
let lastAnalysisDebugKey = null;
let lastViewportDebugKey = null;
let firstViewportFrameLogged = false;
let viewportZoom = 1.0;
let lastGeometryReportKey = null;
let lastSimplificationReportKey = null;
let lastQemHeatmapKey = null;
let lastScaleAnalysisKey = null;
let lastAFCostCandidateKey = null;
let pendingAfterPreprocess = null;
let lastPreprocessContinuationKey = null;
let autoPreprocessFileKey = null;
let cleanedPreviewRefreshKey = null;
let pendingPipelineStage = 1;
let lastPipelineReviewKey = null;
let pipelineReviewAction = "apply_stage";
let qemViewMode = "classic";
let heatmapInverted = false;
let pendingHeatmapDiagnostics = false;
const VIEW_YAW = 0.62;
const VIEW_PITCH = -0.22;
const LEGACY_PIPELINE_PREFIX = "Stage";

const $ = (id) => document.getElementById(id);

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString();
}

function formatFloat(value, digits = 3) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString(undefined, {
    maximumFractionDigits: digits,
  });
}

function basename(path) {
  if (!path) return "No file selected";
  return String(path).split(/[\\/]/).pop();
}

function extension(path) {
  const name = basename(path);
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function outputSourceLabel(source) {
  if (source === "auto") return "Auto-detected Cities Skylines Import folder";
  if (source === "auto-missing") return "Cities Skylines default Import folder; created during build if needed";
  if (source === "manual") return "Manual output folder";
  return "Output folder not configured";
}

function setText(id, value) {
  $(id).textContent = value ?? "-";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function debugLog(message) {
  appendLog(`DEBUG frontend: ${message}`);
  if (bridge && bridge.debugLog) {
    bridge.debugLog(message);
  }
}

function previewImageMarkup(url, label) {
  return url
    ? `<img alt="${label}" src="${url}">`
    : '<div class="empty-preview">Preview unavailable</div>';
}

function emptyPreviewMarkup(message) {
  return `<div class="empty-preview">${escapeHtml(message)}</div>`;
}

function formatCost(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  if (number === 0) return "0";
  if (Math.abs(number) < 0.001 || Math.abs(number) >= 1000) return number.toExponential(3);
  return number.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function renderPreviewNotice(kind, title, lines, errors = []) {
  const notice = $("previewNotice");
  const allLines = [...(lines || []), ...(errors || [])].filter(Boolean);
  if (!title && !allLines.length) {
    notice.hidden = true;
    notice.innerHTML = "";
    notice.className = "result-notice";
    return;
  }
  notice.hidden = false;
  notice.className = `result-notice ${errors.length ? "error" : kind || ""}`;
  notice.innerHTML = `
    ${title ? `<strong>${escapeHtml(title)}</strong>` : ""}
    ${allLines.map((line) => `<span>${escapeHtml(line)}</span>`).join("")}
  `;
}

function hasGeometryReport() {
  return Boolean(state.geometryReport && !(state.geometryReport.errors && state.geometryReport.errors.length));
}

function hasOptimizedPreviewForTarget() {
  return hasPreviewForTarget();
}

function currentPreviewItem() {
  const preview = state.realPreview;
  return preview && preview.items && preview.items.length ? preview.items[0] : null;
}

function hasPreviewForTarget() {
  if (!state.currentPreviewTarget || Number(state.currentPreviewTarget) !== targetValue()) return false;
  return Boolean(currentPreviewItem());
}

function previewRanAdvancedReduce(item = currentPreviewItem()) {
  return Boolean(item && (item.warnings || []).some((line) => String(line).startsWith(`${LEGACY_PIPELINE_PREFIX} 2 `)));
}

function previewRanDetailCleanup(item = currentPreviewItem()) {
  return Boolean(item && (item.warnings || []).some((line) => String(line).startsWith(`${LEGACY_PIPELINE_PREFIX} 3 `)));
}

function previewReachedTarget(item = currentPreviewItem()) {
  return Boolean(item && Number(item.actual_triangles) <= targetValue());
}

function needsAggressiveReview() {
  const item = currentPreviewItem();
  return hasPreviewForTarget() && item && !previewRanAdvancedReduce(item) && !previewReachedTarget(item);
}

function needsDetailSuppressionReview() {
  const item = currentPreviewItem();
  return hasPreviewForTarget() && item && previewRanAdvancedReduce(item) && !previewRanDetailCleanup(item) && !previewReachedTarget(item);
}

function importRiskLabel(rating) {
  if (rating === "Critical") return "Too many tris";
  if (rating === "Warning") return "High tris";
  if (rating === "Good") return "Usable";
  if (rating === "Excellent") return "Good";
  return rating || "-";
}

function stageLinesFromWarnings(warnings) {
  return (warnings || []).filter((line) => String(line).startsWith(`${LEGACY_PIPELINE_PREFIX} `));
}

function nonStageWarnings(warnings) {
  return (warnings || []).filter((line) => !String(line).startsWith(`${LEGACY_PIPELINE_PREFIX} `));
}

function userFacingPipelineLines(warnings) {
  return stageLinesFromWarnings(warnings).map((line) => {
    const text = String(line);
    const conservative = `${LEGACY_PIPELINE_PREFIX} 1`;
    const advanced = `${LEGACY_PIPELINE_PREFIX} 2`;
    const cleanup = `${LEGACY_PIPELINE_PREFIX} 3`;
    return text
      .replace(new RegExp(`^${conservative} Conservative Importance-Aware Reduce:`), "Conservative reduce:")
      .replace(new RegExp(`^${conservative} did not reach target; entering ${advanced} Advanced Reduce\\.`), "Conservative reduce stopped above target; advanced reduce was started.")
      .replace(new RegExp(`^${conservative} did not reach target\\. ${advanced} Advanced Reduce was not run because the selected pipeline depth is Conservative only\\.`), "Conservative reduce stopped above target. Advanced reduce was not run.")
      .replace(new RegExp(`^${advanced} Triangle Budget Planner:`), "Triangle budget:")
      .replace(new RegExp(`^${advanced} Advanced Reduce:`), "Advanced reduce:")
      .replace(new RegExp(`^${advanced} did not reach target; entering ${cleanup} Detail Suppression\\.`), "Advanced reduce stopped above target; detail cleanup was started.")
      .replace(new RegExp(`^${cleanup} Detail Suppression:`), "Detail cleanup:")
      .replace(new RegExp(`^${cleanup} `), "Detail cleanup ")
      .replace(new RegExp(`^${advanced} `), "Advanced reduce ")
      .replace(new RegExp(`^${conservative} `), "Conservative reduce ");
  });
}

function workflowActionLabel() {
  return "Heatmap Diagnostics";
}

function runWorkflowAction() {
  appendLog("Heatmap Diagnostics clicked.");
  pendingHeatmapDiagnostics = true;
  if (state.qemHeatmap && state.scaleAnalysis) {
    pendingHeatmapDiagnostics = false;
    openScaleModal();
  } else if (!state.qemHeatmap) {
    runWithOptionalPreprocess("qem");
  } else {
    runWithOptionalPreprocess("scale");
  }
}

function vectorCross(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function vectorNormalize(v) {
  const length = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / length, v[1] / length, v[2] / length];
}

function parseObj(text) {
  const sourceVertices = [];
  const positions = [];
  const normals = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed.startsWith("v ")) {
      const [, x, y, z] = trimmed.split(/\s+/);
      // Blender exports Z-up coordinates. WebGL preview uses Y-up.
      sourceVertices.push([Number(x), Number(z), -Number(y)]);
    } else if (trimmed.startsWith("f ")) {
      const indices = trimmed
        .slice(2)
        .trim()
        .split(/\s+/)
        .map((part) => Number(part.split("/")[0]) - 1);
      for (let i = 1; i < indices.length - 1; i += 1) {
        const triangle = [indices[0], indices[i], indices[i + 1]].map((index) => sourceVertices[index]);
        if (triangle.some((vertex) => !vertex)) continue;
        const edgeA = [
          triangle[1][0] - triangle[0][0],
          triangle[1][1] - triangle[0][1],
          triangle[1][2] - triangle[0][2],
        ];
        const edgeB = [
          triangle[2][0] - triangle[0][0],
          triangle[2][1] - triangle[0][1],
          triangle[2][2] - triangle[0][2],
        ];
        const normal = vectorNormalize(vectorCross(edgeA, edgeB));
        for (const vertex of triangle) {
          positions.push(vertex[0], vertex[1], vertex[2]);
          normals.push(normal[0], normal[1], normal[2]);
        }
      }
    }
  }
  normalizePositions(positions);
  const viewBounds = computeViewBounds(positions);
  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    vertexCount: positions.length / 3,
    viewCenter: viewBounds.center,
    viewBounds,
  };
}

function normalizePositions(positions) {
  if (!positions.length) return;
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      const value = positions[i + axis];
      min[axis] = Math.min(min[axis], value);
      max[axis] = Math.max(max[axis], value);
    }
  }
  const center = [
    (min[0] + max[0]) / 2,
    (min[1] + max[1]) / 2,
    (min[2] + max[2]) / 2,
  ];
  const scale = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 1);
  for (let i = 0; i < positions.length; i += 3) {
    positions[i] = ((positions[i] - center[0]) / scale) * 2;
    positions[i + 1] = ((positions[i + 1] - center[1]) / scale) * 2;
    positions[i + 2] = ((positions[i + 2] - center[2]) / scale) * 2;
  }
}

function computeViewBounds(positions) {
  const cy = Math.cos(VIEW_YAW);
  const sy = Math.sin(VIEW_YAW);
  const cp = Math.cos(VIEW_PITCH);
  const sp = Math.sin(VIEW_PITCH);
  const min = [Infinity, Infinity];
  const max = [-Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3) {
    const x = positions[i];
    const y = positions[i + 1];
    const z = positions[i + 2];
    const ryX = cy * x - sy * z;
    const ryZ = sy * x + cy * z;
    const rxY = cp * y + sp * ryZ;
    min[0] = Math.min(min[0], ryX);
    max[0] = Math.max(max[0], ryX);
    min[1] = Math.min(min[1], rxY);
    max[1] = Math.max(max[1], rxY);
  }
  return {
    min,
    max,
    center: [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2],
  };
}

function fitZoomForBounds(bounds, aspect) {
  const width = Math.max(bounds.max[0] - bounds.min[0], 0.01);
  const height = Math.max(bounds.max[1] - bounds.min[1], 0.01);
  const fitX = aspect / ((width / 2) * 0.94);
  const fitY = 1 / ((height / 2) * 0.94);
  return Math.min(fitX, fitY) * 0.88;
}

function compileShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader));
  }
  return shader;
}

function createProgram(gl) {
  const vertexShader = compileShader(gl, gl.VERTEX_SHADER, `
    attribute vec3 aPosition;
    attribute vec3 aNormal;
    uniform float uAngle;
    uniform float uAspect;
    uniform float uZoom;
    uniform vec2 uViewCenter;
    varying vec3 vNormal;
    void main() {
      float yaw = uAngle;
      float pitch = ${VIEW_PITCH.toFixed(2)};
      float cy = cos(yaw);
      float sy = sin(yaw);
      float cp = cos(pitch);
      float sp = sin(pitch);
      mat3 rotateY = mat3(cy, 0.0, -sy, 0.0, 1.0, 0.0, sy, 0.0, cy);
      mat3 rotateX = mat3(1.0, 0.0, 0.0, 0.0, cp, sp, 0.0, -sp, cp);
      vec3 p = rotateX * rotateY * aPosition;
      p.xy = (p.xy - uViewCenter) * uZoom;
      gl_Position = vec4((p.x / uAspect) * 0.94, p.y * 0.94, p.z * 0.18, 1.0);
      vNormal = rotateX * rotateY * aNormal;
    }
  `);
  const fragmentShader = compileShader(gl, gl.FRAGMENT_SHADER, `
    precision mediump float;
    varying vec3 vNormal;
    void main() {
      vec3 light = normalize(vec3(0.45, 0.75, 0.55));
      float shade = max(dot(normalize(vNormal), light), 0.0);
      vec3 base = vec3(0.62, 0.68, 0.73);
      vec3 color = base * (0.45 + shade * 0.55);
      gl_FragColor = vec4(color, 1.0);
    }
  `);
  const program = gl.createProgram();
  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program));
  }
  return program;
}

function attachBuffer(gl, program, name, values) {
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, values, gl.STATIC_DRAW);
  const location = gl.getAttribLocation(program, name);
  gl.enableVertexAttribArray(location);
  gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 0, 0);
}

function renderViewportPreviewFromText(cacheKey, text) {
  if (!text || viewportUrl === cacheKey) return;
  viewportUrl = cacheKey;
  firstViewportFrameLogged = false;
  const stage = $("previewStage");
  debugLog(`viewport render requested, mesh_chars=${formatNumber(text.length)}`);
  stage.innerHTML = '<canvas id="viewportCanvas" aria-label="Model viewport preview"></canvas>';
  const canvas = $("viewportCanvas");
  try {
    const mesh = parseObj(text);
    debugLog(`OBJ parsed, vertices=${formatNumber(mesh.vertexCount)}, triangles=${formatNumber(mesh.vertexCount / 3)}`);
    if (!mesh.vertexCount) throw new Error("Viewport mesh is empty.");
    const gl = canvas.getContext("webgl", { antialias: true });
    if (!gl) throw new Error("WebGL is not available.");
    debugLog("WebGL context created");
    const program = createProgram(gl);
    gl.useProgram(program);
    attachBuffer(gl, program, "aPosition", mesh.positions);
    attachBuffer(gl, program, "aNormal", mesh.normals);
    const angleLocation = gl.getUniformLocation(program, "uAngle");
    const aspectLocation = gl.getUniformLocation(program, "uAspect");
    const zoomLocation = gl.getUniformLocation(program, "uZoom");
    const viewCenterLocation = gl.getUniformLocation(program, "uViewCenter");
    gl.enable(gl.DEPTH_TEST);
    cancelAnimationFrame(viewportFrame);
    const draw = (time) => {
      const rect = canvas.getBoundingClientRect();
      const scale = window.devicePixelRatio || 1;
      const width = Math.max(1, Math.floor(rect.width * scale));
      const height = Math.max(1, Math.floor(rect.height * scale));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0.78, 0.80, 0.83, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      const aspect = canvas.width / canvas.height;
      const fitZoom = fitZoomForBounds(mesh.viewBounds, aspect);
      gl.uniform1f(angleLocation, VIEW_YAW);
      gl.uniform1f(aspectLocation, aspect);
      gl.uniform1f(zoomLocation, viewportZoom * fitZoom);
      gl.uniform2f(viewCenterLocation, mesh.viewCenter[0], mesh.viewCenter[1]);
      gl.drawArrays(gl.TRIANGLES, 0, mesh.vertexCount);
      if (!firstViewportFrameLogged) {
        firstViewportFrameLogged = true;
        debugLog(`first viewport frame drawn, canvas=${canvas.width}x${canvas.height}`);
      }
      viewportFrame = requestAnimationFrame(draw);
    };
    viewportFrame = requestAnimationFrame(draw);
  } catch (error) {
    viewportUrl = null;
    debugLog(`viewport render failed: ${error.message}`);
    stage.innerHTML = `<div class="empty-preview">Viewport preview unavailable: ${error.message}</div>`;
  }
}

function requestViewportMesh(analysis) {
  const meshPath = analysis.preview_mesh_path;
  const cacheKey = `${meshPath}:${analysis.triangle_count}`;
  if (!meshPath || lastViewportDebugKey === cacheKey) return;
  lastViewportDebugKey = cacheKey;
  $("previewStage").innerHTML = '<div class="empty-preview">Loading viewport mesh...</div>';
  debugLog(`requesting preview mesh from backend: ${meshPath}`);
  bridge.loadPreviewMesh(meshPath, (text) => {
    debugLog(`preview mesh received, mesh_chars=${formatNumber(text ? text.length : 0)}`);
    if (!text) {
      $("previewStage").innerHTML = '<div class="empty-preview">Viewport preview data is unavailable</div>';
      return;
    }
    renderViewportPreviewFromText(cacheKey, text);
  });
}

function updateBusy() {
  document.body.classList.toggle("busy", Boolean(state.busy || state.sourcePreviewBusy));
  const hasFile = Boolean(state.selectedFile);
  const hasBlendFile = extension(state.selectedFile) === ".blend";
  const optimizeEnabled = true;
  const hasCurrentAnalysis = hasGeometryReport();
  const hasCurrentOptimizedPreview = hasOptimizedPreviewForTarget();
  $("workflowActionBtn").disabled = state.busy || !hasFile;
  $("workflowActionBtn").textContent = workflowActionLabel();
  $("simplificationReportBtn").disabled = state.busy || !hasBlendFile || !state.currentPreviewTarget;
  $("buildBtn").disabled = state.busy || !hasBlendFile;
  $("applyPreviewBtn").disabled = state.busy || !state.currentPreviewTarget || !optimizeEnabled;
  $("selectFileBtn").disabled = state.busy;
  $("browseBlenderBtn").disabled = state.busy;
  $("browseOutputBtn").disabled = false;
  $("targetTriangles").disabled = false;
  $("targetSlider").disabled = false;
  document.querySelectorAll("[data-target]").forEach((button) => {
    button.disabled = !optimizeEnabled;
  });
  $("optimizeControls").classList.toggle("enabled", optimizeEnabled);
}

function renderState(nextState) {
  state = nextState || {};
  $("targetTriangles").value = state.targetTriangles || 3000;
  $("targetSlider").value = Math.min(Math.max(Number(state.targetTriangles || 3000), 1000), 30000);
  $("optimizeToggle").checked = true;
  setText("fileTitle", basename(state.selectedFile));
  setText("statusText", state.status || "Ready");
  $("statusText").classList.toggle("success", Boolean(state.build && !(state.build.errors && state.build.errors.length)));
  setText("outputFolderValue", state.outputFolder || "-");
  setText("outputFolderSource", outputSourceLabel(state.outputFolderSource));
  renderWorkflowSteps();
  updateBusy();

  const analysis = state.analysis;
  setText("bodyValue", analysis ? (analysis.has_vehicle_body ? "Detected" : "Missing") : "-");
  setText("wheelValue", analysis ? formatNumber(analysis.wheel_count) : "-");
  setText("objectValue", analysis ? formatNumber(analysis.object_count) : "-");
  setText("vertexValue", analysis ? formatNumber(analysis.vertex_count) : "-");
  setText("triangleValue", analysis ? formatNumber(analysis.triangle_count) : "-");

  const preprocess = state.preprocess;
  const preview = state.realPreview;
  const item = preview && preview.items && preview.items.length ? preview.items[0] : null;
  if (item && hasPreviewForTarget()) {
    viewportUrl = null;
    cancelAnimationFrame(viewportFrame);
    setText("previewEyebrow", "Real Preview");
    setText("previewTitle", "Optimization result");
    $("previewStage").innerHTML = previewImageMarkup(item.preview_image_url, "Optimization preview");
    setText("metricOriginal", `${formatNumber(preview.original_triangle_count)} tris`);
    setText("metricTarget", `${formatNumber(item.target_triangles)} tris`);
    setText("metricActual", `${formatNumber(item.actual_triangles)} tris`);
    setText("metricReduction", `${Number(item.reduction_percent).toFixed(2)}%`);
    setText("metricScore", `${item.compatibility_score}/100`);
    setText("metricRating", importRiskLabel(item.rating));
    renderPreviewNotice(
      "optimized",
      "Optimization result",
      [
        `${formatNumber(preview.original_triangle_count)} -> ${formatNumber(item.actual_triangles)} tris (${Number(item.reduction_percent).toFixed(2)}% removed)`,
        `Target was ${formatNumber(item.target_triangles)} tris. Next optimized build will use ${basename(item.preview_blend_path)}.`,
        ...userFacingPipelineLines(item.warnings),
        ...nonStageWarnings(item.warnings),
      ],
      item.errors || [],
    );
    const reviewKey = `${item.preview_blend_path}:${item.actual_triangles}:${previewRanAdvancedReduce(item)}`;
    if (lastPipelineReviewKey !== reviewKey) {
      lastPipelineReviewKey = reviewKey;
      window.requestAnimationFrame(openPipelineReviewModal);
    }
  } else if (analysis && analysis.preview_mesh_url) {
    const debugKey = `${analysis.preview_mesh_url}:${analysis.triangle_count}`;
    if (lastAnalysisDebugKey !== debugKey) {
      lastAnalysisDebugKey = debugKey;
      debugLog(`analysis state received, busy=${Boolean(state.busy)}, triangles=${formatNumber(analysis.triangle_count)}, mesh_path=${analysis.preview_mesh_path || "none"}`);
    }
    setText("previewEyebrow", preprocess ? "Cleaned Preview" : "Viewport Preview");
    setText("previewTitle", preprocess ? "Cleaned model" : "Analyzed model");
    if (analysis.preview_mesh_path) {
      requestViewportMesh(analysis);
    } else {
      debugLog("analysis had no preview_mesh_path");
      $("previewStage").innerHTML = '<div class="empty-preview">Viewport preview data is unavailable</div>';
    }
    setText("metricOriginal", preprocess ? `${formatNumber(preprocess.original_triangle_count)} tris` : `${formatNumber(analysis.triangle_count)} tris`);
    setText("metricTarget", "-");
    setText("metricActual", preprocess ? `${formatNumber(preprocess.preprocessed_triangle_count)} tris` : `${formatNumber(analysis.triangle_count)} tris`);
    setText("metricReduction", preprocess ? `${formatFloat(preprocess.reduction_percentage, 2)}%` : "0.00%");
    setText("metricScore", "-");
    setText("metricRating", preprocess ? "Cleaned" : "Original");
    const notices = [...(analysis.warnings || []), ...(analysis.errors || [])];
    if (preprocess) {
      renderPreviewNotice(
        "cleaned",
        preprocess.errors && preprocess.errors.length ? "Safe preprocess found issues" : "Safe preprocess ready",
        preprocess.errors && preprocess.errors.length
          ? preprocess.errors
          : [
              `${formatNumber(preprocess.original_triangle_count)} -> ${formatNumber(preprocess.preprocessed_triangle_count)} tris (${formatFloat(preprocess.reduction_percentage, 2)}% removed)`,
              `Next preview/build will use ${basename(preprocess.preprocessed_blend_file)}.`,
              ...notices,
            ],
        preprocess.errors || [],
      );
    } else {
      renderPreviewNotice("", "", notices, analysis.errors || []);
    }
  } else {
    viewportUrl = null;
    cancelAnimationFrame(viewportFrame);
    setText("previewEyebrow", "Model Preview");
    setText("previewTitle", "Source model");
    $("previewStage").innerHTML = state.busy
      ? '<div class="empty-preview">Working in Blender...</div>'
      : '<div class="empty-preview">Select a .blend file to load the original model preview</div>';
    ["metricOriginal", "metricTarget", "metricActual", "metricReduction", "metricScore", "metricRating"]
      .forEach((id) => setText(id, "-"));
    renderPreviewNotice("", "", []);
  }

  const build = state.build;
  const deployedFbx = build ? (build.deployed_fbx_file || build.fbx_file) : null;
  const deployedTexture = build ? (build.deployed_diffuse_texture_file || build.diffuse_texture_file) : null;
  const buildNotice = $("buildNotice");
  const buildSummary = $("buildSummary");
  if (build) {
    const buildMode = buildModeText(build);
    const outputPath = build.deploy_folder || build.build_folder;
    buildNotice.hidden = false;
    buildNotice.classList.toggle("error", Boolean(build.errors && build.errors.length));
    buildNotice.innerHTML = build.errors && build.errors.length
      ? `<strong>Build failed</strong><span>${escapeHtml(build.errors.join(" "))}</span>`
      : `<strong>Build complete</strong><span>${escapeHtml(buildMode)} FBX and texture are ready in ${escapeHtml(outputPath)}</span>`;
    buildSummary.hidden = false;
    buildSummary.classList.toggle("error", Boolean(build.errors && build.errors.length));
    buildSummary.innerHTML = build.errors && build.errors.length
      ? `<strong>Build failed</strong><span>${escapeHtml(build.errors.join(" "))}</span>`
      : `<strong>Build complete</strong><span>${escapeHtml(buildMode)}</span><small>${escapeHtml(outputPath)}</small>`;
  } else {
    buildNotice.hidden = true;
    buildNotice.innerHTML = "";
    buildSummary.hidden = true;
    buildSummary.innerHTML = "";
  }
  setText("fbxValue", deployedFbx ? basename(deployedFbx) : "-");
  setText("textureValue", deployedTexture ? basename(deployedTexture) : "-");
  setText("deployFolderValue", build ? (build.deploy_folder || build.build_folder) : "-");
  setText("buildFolderValue", build ? build.build_folder : "-");
  setText("lodValue", "Main model only");

  renderGeometryReport(state.geometryReport);
  renderSimplificationReport(state.simplificationReport);
  renderQemHeatmap(state.qemHeatmap);
  renderScaleAnalysis(state.scaleAnalysis);
  continueAfterPreprocessIfNeeded();
  continueHeatmapDiagnosticsIfNeeded();
  refreshCleanedPreviewIfNeeded();
  startAutoPreprocessAfterImportIfNeeded();
}

function renderWorkflowSteps() {
  const hasFile = Boolean(state.selectedFile);
  const hasAnalysis = Boolean(state.analysis);
  const hasBuild = Boolean(state.build && !(state.build.errors && state.build.errors.length));
  $("stepSelect").classList.toggle("done", hasFile);
  $("stepReview").classList.toggle("done", hasAnalysis);
  $("stepBuild").classList.toggle("done", hasBuild);
  $("stepSelect").classList.toggle("active", !hasFile);
  $("stepReview").classList.toggle("active", hasFile && !hasAnalysis && !hasBuild);
  $("stepBuild").classList.toggle("active", hasAnalysis && !hasBuild);
}

function shouldAutoPreprocess() {
  return Boolean($("autoPreprocessToggle").checked && state.selectedFile && extension(state.selectedFile) === ".blend" && !state.preprocess);
}

function selectedFileKey() {
  return `${state.selectedFile || ""}:${state.analysis ? state.analysis.triangle_count : ""}`;
}

function startAutoPreprocessAfterImportIfNeeded() {
  if (!shouldAutoPreprocess() || state.busy || !state.analysis) return;
  const key = selectedFileKey();
  if (!key || autoPreprocessFileKey === key) return;
  autoPreprocessFileKey = key;
  appendLog("Auto cleanup started after model import.");
  bridge.preprocess();
}

function runWithOptionalPreprocess(action, pipelineStage = 1) {
  if (shouldAutoPreprocess()) {
    pendingAfterPreprocess = {
      action,
      target: targetValue(),
      pipelineStage,
      optimize: action === "build" && hasOptimizedPreviewForTarget(),
    };
    lastPreprocessContinuationKey = null;
    appendLog("Auto cleanup will run first, then OccamForge will continue automatically.");
    bridge.preprocess();
    return;
  }
  if (action === "preview") {
    bridge.generateRealPreview(targetValue(), pipelineStage);
  } else if (action === "build") {
    bridge.buildCitiesSkylinesAsset(targetValue(), hasOptimizedPreviewForTarget());
  } else if (action === "qem") {
    bridge.generateQemHeatmap();
  } else if (action === "scale") {
    bridge.generateScaleAnalysis();
  }
}

function continueAfterPreprocessIfNeeded() {
  if (!pendingAfterPreprocess || state.busy || !state.preprocess) return;
  const preprocessKey = `${state.preprocess.preprocessed_blend_file || ""}:${state.preprocess.preprocessed_triangle_count || ""}`;
  if (!preprocessKey || preprocessKey === lastPreprocessContinuationKey) return;
  lastPreprocessContinuationKey = preprocessKey;
  const pending = pendingAfterPreprocess;
  pendingAfterPreprocess = null;
  if (state.preprocess.errors && state.preprocess.errors.length) {
    appendLog("Auto cleanup failed; pending action was not started.");
    return;
  }
  if (pending.action === "preview") {
    appendLog(`Auto cleanup complete. Generating preview for ${formatNumber(pending.target)} tris.`);
    bridge.generateRealPreview(pending.target, pending.pipelineStage || 1);
  } else if (pending.action === "build") {
    appendLog("Auto cleanup complete. Building Cities Skylines asset.");
    bridge.buildCitiesSkylinesAsset(pending.target, pending.optimize);
  } else if (pending.action === "qem") {
    appendLog("Auto cleanup complete. Generating QEM heatmaps from the joined model.");
    bridge.generateQemHeatmap();
  } else if (pending.action === "scale") {
    appendLog("Auto cleanup complete. Generating scale analysis from the joined model.");
    bridge.generateScaleAnalysis();
  }
}

function continueHeatmapDiagnosticsIfNeeded() {
  if (!pendingHeatmapDiagnostics || state.busy || pendingAfterPreprocess) return;
  if (!state.qemHeatmap) {
    runWithOptionalPreprocess("qem");
    return;
  }
  if (!state.scaleAnalysis) {
    runWithOptionalPreprocess("scale");
    return;
  }
  pendingHeatmapDiagnostics = false;
  openScaleModal();
}

function openQemModal() {
  if (!state.qemHeatmap) return;
  $("qemModal").hidden = false;
}

function closeQemModal() {
  $("qemModal").hidden = true;
}

function openScaleModal() {
  if (!state.scaleAnalysis && !state.qemHeatmap) return;
  $("scaleModal").hidden = false;
}

function closeScaleModal() {
  $("scaleModal").hidden = true;
}

function openAFCostModal() {
  $("afcostModal").hidden = false;
}

function closeAFCostModal() {
  $("afcostModal").hidden = true;
}

function exportHeatmapComparison() {
  if (!bridge || !bridge.exportHeatmapComparison) return;
  appendLog(`Exporting ${heatmapInverted ? "inverted" : "normal"} heatmap comparison...`);
  bridge.exportHeatmapComparison(heatmapInverted, (payloadText) => {
    let payload = {};
    try {
      payload = JSON.parse(payloadText || "{}");
    } catch (error) {
      appendLog(`Export failed: ${error}`);
      return;
    }
    const errors = payload.errors || [];
    if (errors.length) {
      appendLog(`Export failed: ${errors.join("; ")}`);
      return;
    }
    appendLog(`Heatmap comparison exported: ${payload.path}`);
    if (payload.url) {
      window.open(payload.url, "_blank");
    }
  });
}

function exportAFCostCandidates() {
  if (!bridge || !bridge.exportAFCostCandidates) return;
  appendLog("Exporting AF cost candidate comparison...");
  bridge.exportAFCostCandidates((payloadText) => {
    let payload = {};
    try {
      payload = JSON.parse(payloadText || "{}");
    } catch (error) {
      appendLog(`Export failed: ${error}`);
      return;
    }
    const errors = payload.errors || [];
    if (errors.length) {
      appendLog(`Export failed: ${errors.join("; ")}`);
      return;
    }
    appendLog(`AF cost candidate comparison exported: ${payload.path}`);
    if (payload.url) {
      window.open(payload.url, "_blank");
    }
  });
}

function pipelineReviewKind() {
  if (!hasGeometryReport()) return "model_analysis";
  if (!hasPreviewForTarget()) return "conservative_reduce_plan";
  if (needsAggressiveReview()) return "advanced_reduce_plan";
  if (needsDetailSuppressionReview()) return "detail_cleanup_plan";
  if (previewRanDetailCleanup()) return "detail_cleanup_result";
  return previewRanAdvancedReduce() ? "advanced_reduce_result" : "conservative_reduce_result";
}

function openPipelineReviewModal() {
  const kind = pipelineReviewKind();
  pendingPipelineStage = kind === "detail_cleanup_plan" ? 3 : (kind === "advanced_reduce_plan" ? 2 : 1);
  const item = currentPreviewItem();
  const geometryReport = state.geometryReport || {};
  const overall = geometryReport.overall || {};
  const candidates = geometryReport.optimization_candidates || [];
  const candidateCounts = candidates.reduce((acc, candidate) => {
    const key = candidate.recommended_action || "unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  let title = "Conservative reduce";
  let eyebrow = "Stage Review";
  let imageUrl = geometryReport.heatmap_image_url;
  let stats = [];
  let noticeTitle = "Review before applying";
  let lines = [];
  let applyLabel = "Apply Conservative Reduce";
  let applyDisabled = false;
  let secondaryLabel = "Close";
  pipelineReviewAction = "apply_stage";

  if (kind === "conservative_reduce_plan") {
    title = "Conservative reduce";
    stats = [
      ["Current", `${formatNumber(overall.triangles)} tris`],
      ["Target", `${formatNumber(targetValue())} tris`],
      ["Protect", `${formatNumber(candidateCounts.protect_candidate || 0)} regions`],
      ["Reduce", `${formatNumber(candidateCounts.decimate_candidate || 0)} regions`],
    ];
    lines = [
      "This stage uses the current candidate report and only applies conservative reduction.",
      "If it cannot reach the target without crossing safety limits, OccamForge will stop and ask before advanced reduction.",
    ];
  } else if (kind === "advanced_reduce_plan") {
    title = "Conservative reduce result";
    eyebrow = "Continue Pipeline";
    imageUrl = item.preview_image_url;
    applyLabel = "Continue to Advanced Reduce";
    secondaryLabel = "Use Current Result";
    pipelineReviewAction = "apply_stage";
    stats = [
      ["Current result", `${formatNumber(item.actual_triangles)} tris`],
      ["Target", `${formatNumber(item.target_triangles)} tris`],
      ["Remaining gap", `${formatNumber(Math.max(0, Number(item.actual_triangles) - targetValue()))} tris`],
      ["Reduction so far", `${Number(item.reduction_percent).toFixed(2)}%`],
    ];
    lines = [
      "The conservative pass stopped at its safe reduction limit and did not reach the target.",
      "You can use this result now, or continue to the advanced reduce pass.",
      ...userFacingPipelineLines(item.warnings),
    ];
  } else if (kind === "detail_cleanup_plan") {
    title = "Advanced reduce result";
    eyebrow = "Continue Pipeline";
    imageUrl = item.preview_image_url;
    applyLabel = "Continue to Detail Cleanup";
    secondaryLabel = "Use Current Result";
    pipelineReviewAction = "apply_stage";
    stats = [
      ["Current result", `${formatNumber(item.actual_triangles)} tris`],
      ["Target", `${formatNumber(item.target_triangles)} tris`],
      ["Remaining gap", `${formatNumber(Math.max(0, Number(item.actual_triangles) - targetValue()))} tris`],
      ["Reduction so far", `${Number(item.reduction_percent).toFixed(2)}%`],
    ];
    lines = [
      "The advanced reduce pass preserved the main structure but stopped above target.",
      "Detail cleanup suppresses low-visibility small features, rings, bevel strips, and repeated surface details.",
      ...userFacingPipelineLines(item.warnings),
    ];
  } else {
    title = previewRanDetailCleanup(item) ? "Detail cleanup result" : (previewRanAdvancedReduce(item) ? "Advanced reduce result" : "Conservative reduce result");
    eyebrow = "Optimization Result";
    imageUrl = item.preview_image_url;
    applyLabel = "Use Current Result";
    secondaryLabel = "Close";
    pipelineReviewAction = "accept_current";
    stats = [
      ["Original", `${formatNumber(state.realPreview.original_triangle_count)} tris`],
      ["Target", `${formatNumber(item.target_triangles)} tris`],
      ["Actual", `${formatNumber(item.actual_triangles)} tris`],
      ["Reduction", `${Number(item.reduction_percent).toFixed(2)}%`],
    ];
    noticeTitle = previewReachedTarget(item) ? "Target reached" : "Stopped before aggressive reduction";
    lines = [
      ...userFacingPipelineLines(item.warnings),
      ...nonStageWarnings(item.warnings).slice(0, 8),
    ];
  }

  $("pipelineReviewEyebrow").textContent = eyebrow;
  $("pipelineReviewTitle").textContent = title;
  $("pipelineReviewImage").innerHTML = previewImageMarkup(imageUrl, title);
  $("pipelineReviewStats").innerHTML = stats
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
  $("pipelineReviewNotice").innerHTML = `
    <strong>${escapeHtml(noticeTitle)}</strong>
    ${lines.map((line) => `<span>${escapeHtml(line)}</span>`).join("")}
  `;
  $("applyPipelineStageBtn").textContent = applyLabel;
  $("applyPipelineStageBtn").disabled = state.busy || applyDisabled;
  $("stopPipelineBtn").textContent = secondaryLabel;
  $("pipelineModal").hidden = false;
}

function closePipelineReviewModal() {
  $("pipelineModal").hidden = true;
}

function refreshCleanedPreviewIfNeeded() {
  if (pendingAfterPreprocess || state.busy || !state.preprocess || !state.analysis) return;
  if (state.preprocess.errors && state.preprocess.errors.length) return;
  const key = `${state.preprocess.preprocessed_blend_file || ""}:${state.preprocess.preprocessed_triangle_count || ""}`;
  if (!key || cleanedPreviewRefreshKey === key) return;
  if (Number(state.analysis.triangle_count) === Number(state.preprocess.preprocessed_triangle_count)) return;
  cleanedPreviewRefreshKey = key;
  appendLog("Refreshing viewport from cleaned model.");
  bridge.analyzePipelineFile();
}

function renderGeometryReport(report) {
  if (!report) {
    lastGeometryReportKey = null;
    return;
  }
  const reportKey = `${report.report_json_path}:${report.heatmap_image_path}`;
  lastGeometryReportKey = reportKey;
}

function startOptimizePreview(pipelineStage = 1) {
  const stageName = pipelineStage >= 3
    ? "Detail cleanup"
    : (pipelineStage >= 2 ? "Advanced reduce" : "Conservative reduce");
  appendLog(`${stageName} confirmed for ${formatNumber(targetValue())} tris.`);
  closePipelineReviewModal();
  runWithOptionalPreprocess("preview", pipelineStage);
}

function acceptCurrentPreviewResult() {
  if (state.currentPreviewTarget && bridge.applyCurrentPreview) {
    bridge.applyCurrentPreview();
  }
  appendLog("Current optimization result accepted.");
  closePipelineReviewModal();
}

function renderSimplificationReport(report) {
  const panel = $("simplificationPanel");
  if (!report) {
    panel.hidden = true;
    lastSimplificationReportKey = null;
    return;
  }
  panel.hidden = false;
  $("simplificationHeatmap").innerHTML = previewImageMarkup(
    report.heatmap_image_url,
    "Simplification heatmap",
  );
  setText("simpOriginal", `${formatNumber(report.original_triangle_count)} tris`);
  setText("simpOptimized", `${formatNumber(report.optimized_triangle_count)} tris`);
  setText("simpRemoved", `${formatNumber(report.removed_triangle_count)} tris`);
  setText("simpReduction", `${formatFloat(report.reduction_percentage, 2)}%`);
  setText("simpSource", basename(report.source_blend_file));
  setText("simpOptimizedFile", basename(report.optimized_blend_file));
  $("simplificationRegionList").innerHTML = (report.regions || [])
    .slice(0, 20)
    .map((item) => `
      <div class="dense-row">
        <strong>${escapeHtml(item.object_name || "-")} / ${escapeHtml(item.region_id)}</strong>
        <span>${formatNumber(item.removed_triangles)} removed</span>
        <span>${formatNumber(item.original_triangles)} original</span>
        <span>${formatNumber(item.optimized_triangles)} optimized</span>
        <span>${formatFloat(item.reduction_percentage, 1)}%</span>
      </div>
    `)
    .join("");
  const reportKey = `${report.report_json_path}:${report.heatmap_image_path}`;
  if (lastSimplificationReportKey !== reportKey) {
    lastSimplificationReportKey = reportKey;
    window.requestAnimationFrame(() => {
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
}

function renderQemHeatmap(report) {
  if (!report) {
    lastQemHeatmapKey = null;
    return;
  }
  const isFeature = qemViewMode === "feature";
  const stats = isFeature ? (report.feature_cost_statistics || {}) : (report.cost_statistics || {});
  const boundary = isFeature
    ? (report.feature_boundary_statistics || {})
    : (report.boundary_statistics || {});
  const boundaryStats = boundary.cost_statistics || {};
  const visualization = report.visualization || {};
  const imageUrl = isFeature
    ? (heatmapInverted ? report.feature_heatmap_inverse_png_url : report.feature_heatmap_png_url)
    : (heatmapInverted ? report.heatmap_inverse_png_url : report.heatmap_png_url);
  const objectStats = isFeature
    ? (report.feature_object_statistics || [])
    : (report.object_statistics || []);
  const highEdges = isFeature
    ? (report.feature_top_50_highest_cost_edges || [])
    : (report.top_50_highest_cost_edges || []);
  const lowEdges = isFeature
    ? (report.feature_top_50_lowest_cost_edges || [])
    : (report.top_50_lowest_cost_edges || []);
  $("classicQemBtn").classList.toggle("active", !isFeature);
  $("featureQemBtn").classList.toggle("active", isFeature);
  $("qemHeatmapImage").innerHTML = previewImageMarkup(
    imageUrl,
    isFeature ? "Feature-aware QEM edge cost heatmap" : "Classic QEM edge cost heatmap",
  );
  $("qemStats").innerHTML = [
    ["Mode", isFeature ? "Feature-aware" : "Classic"],
    ["Vertices", formatNumber(report.vertex_count)],
    ["Faces", formatNumber(report.face_count)],
    ["Triangles", `${formatNumber(report.triangle_count)} tris`],
    ["Edges", formatNumber(report.edge_count)],
    ["Median Cost", formatCost(stats.median)],
    ["P90 / P99", `${formatCost(stats.p90)} / ${formatCost(stats.p99)}`],
    ["Max Cost", formatCost(stats.max)],
    ["Boundary P90+", `${formatNumber(boundary.boundary_p90_plus_edge_count)} / ${formatNumber(boundary.boundary_edge_count)}`],
    ["Fallback Solves", formatNumber(report.singular_fallback_edges)],
  ]
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
  $("qemNotice").innerHTML = `
    <strong>Diagnostic only</strong>
    <span>${escapeHtml(isFeature ? "Feature-aware cost adds boundary and sharp-normal penalties to Classic QEM." : "Classic QEM uses only vertex-to-plane quadric error.")} No edges are collapsed and the source model is not modified.</span>
    <small>Colors use ${escapeHtml(visualization.display_heat_normalization || "percentile_rank")} display scaling${heatmapInverted ? " with inverted values" : ""}. Boundary median: ${escapeHtml(formatCost(boundaryStats.median))}.</small>
  `;
  $("qemObjectStats").innerHTML = objectStats
    .slice(0, 24)
    .map((item) => {
      const itemStats = item.cost_statistics || {};
      return `
        <div class="dense-row qem-row">
          <strong>${escapeHtml(item.object_name || "-")}</strong>
          <span>${formatNumber(item.edge_count)} edges</span>
          <span>${formatNumber(item.global_p90_plus_edge_count)} p90+</span>
          <span>med ${formatCost(itemStats.median)}</span>
          <span>p99 ${formatCost(itemStats.p99)}</span>
        </div>
      `;
    })
    .join("");
  $("qemHighEdges").innerHTML = highEdges
    .slice(0, 18)
    .map((edge) => `
      <div class="dense-row qem-row">
        <strong>${escapeHtml(edge.object_name || "-")} #${formatNumber(edge.edge_id)}</strong>
        <span>${formatNumber(edge.v0)}-${formatNumber(edge.v1)}</span>
        <span>${formatCost(edge.cost)}</span>
        <span>${isFeature ? `+${formatCost((edge.boundary_penalty || 0) + (edge.normal_penalty || 0))}` : (edge.is_boundary ? "Boundary" : "Interior")}</span>
        <span>${escapeHtml(edge.placement_source || "-")}</span>
      </div>
    `)
    .join("");
  $("qemLowEdges").innerHTML = lowEdges
    .slice(0, 18)
    .map((edge) => `
      <div class="dense-row qem-row">
        <strong>${escapeHtml(edge.object_name || "-")} #${formatNumber(edge.edge_id)}</strong>
        <span>${formatNumber(edge.v0)}-${formatNumber(edge.v1)}</span>
        <span>${formatCost(edge.cost)}</span>
        <span>${edge.is_boundary ? "Boundary" : "Interior"}</span>
        <span>${escapeHtml(edge.placement_source || "-")}</span>
      </div>
    `)
    .join("");
  const reportKey = `${qemViewMode}:${imageUrl || ""}:${report.edge_count || ""}:${stats.max || ""}`;
  if (lastQemHeatmapKey !== reportKey) {
    lastQemHeatmapKey = reportKey;
    if (!pendingHeatmapDiagnostics) {
      window.requestAnimationFrame(openScaleModal);
    }
  }
}

function percent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${(number * 100).toFixed(1)}%`;
}

function renderScaleAnalysis(report) {
  if (!report && !state.qemHeatmap) {
    lastScaleAnalysisKey = null;
    return;
  }
  const hasScaleReport = Boolean(report && report.object_name);
  report = report || {};
  const persistenceStats = report.persistence_stats || {};
  const tinyStats = report.tiny_detail_stats || {};
  const curvatureStats = report.mean_curvature_stats || {};
  const centerStats = report.center_surround_stats || {};
  const interpretation = report.interpretation || {};
  const qem = state.qemHeatmap || {};
  $("diagClassicQemImage").innerHTML = previewImageMarkup(
    heatmapInverted ? qem.heatmap_inverse_png_url : qem.heatmap_png_url,
    "Classic QEM cost heatmap",
  );
  $("diagFeatureQemImage").innerHTML = previewImageMarkup(
    heatmapInverted ? qem.feature_heatmap_inverse_png_url : qem.feature_heatmap_png_url,
    "Feature-aware QEM cost heatmap",
  );
  $("meanCurvatureImage").innerHTML = hasScaleReport
    ? previewImageMarkup(
        heatmapInverted ? report.mean_curvature_heatmap_inverse_url : report.mean_curvature_heatmap_url,
        "Normal variation heatmap",
      )
    : emptyPreviewMarkup("Scale Analysis has not been generated yet");
  $("centerSurroundImage").innerHTML = hasScaleReport
    ? previewImageMarkup(
        heatmapInverted ? report.center_surround_heatmap_inverse_url : report.center_surround_heatmap_url,
        "Center-surround heatmap",
      )
    : emptyPreviewMarkup("Scale Analysis has not been generated yet");
  $("scalePersistenceImage").innerHTML = hasScaleReport
    ? previewImageMarkup(
        heatmapInverted ? report.scale_persistence_heatmap_inverse_url : report.scale_persistence_heatmap_url,
        "Scale persistence heatmap",
      )
    : emptyPreviewMarkup("Scale Analysis has not been generated yet");
  $("tinyDetailImage").innerHTML = hasScaleReport
    ? previewImageMarkup(
        heatmapInverted ? report.tiny_detail_heatmap_inverse_url : report.tiny_detail_heatmap_url,
        "Tiny detail heatmap",
      )
    : emptyPreviewMarkup("Scale Analysis has not been generated yet");
  $("scaleStats").innerHTML = [
    ["Object", report.object_name || "-"],
    ["Vertices", formatNumber(report.vertex_count)],
    ["Triangles", `${formatNumber(report.triangle_count)} tris`],
    ["BBox diagonal", formatFloat(report.bbox_diagonal, 4)],
    ["Normal variation mean", formatFloat(curvatureStats.mean, 3)],
    ["Center-surround p75", formatFloat(centerStats.p75, 3)],
    ["Persistence mean", formatFloat(persistenceStats.mean, 3)],
    ["Persistence p75", formatFloat(persistenceStats.p75, 3)],
    ["Tiny detail mean", formatFloat(tinyStats.mean, 3)],
    ["Tiny detail p75", formatFloat(tinyStats.p75, 3)],
    ["Low persistence", percent(interpretation.low_persistence_ratio)],
    ["High persistence", percent(interpretation.high_persistence_ratio)],
    ["Tiny detail", percent(interpretation.tiny_detail_ratio)],
    ["Scales", (report.scales || []).map((value) => formatFloat(value, 4)).join(", ")],
  ]
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
  $("scaleNotice").innerHTML = `
    <strong>Analysis only</strong>
    <span>Center-surround uses S(v,sigma)=abs(G(H,sigma)-G(H,2sigma)); in V0, H is adjacent face-normal variation at vertices, not QEM edge cost.</span>
    <span>QEM rows are edge-cost diagnostics; Scale rows are vertex scores projected onto mesh edges with neutral surface shading.</span>
    <span>${heatmapInverted ? "Invert mode is on: blue/red meanings are numerically swapped for every displayed heatmap." : "Normal mode is on: red means higher score or cost for every displayed heatmap."}</span>
    <span>Blue persistence means the signal appears only at small scale; red persistence means it survives across more scales.</span>
    <span>Red tiny-detail regions are candidates for later simplification, but no mesh reduction is performed here.</span>
  `;
  const reportKey = `${heatmapInverted}:${report.mean_curvature_heatmap_url || ""}:${report.center_surround_heatmap_url || ""}:${report.scale_persistence_heatmap_url || ""}:${report.tiny_detail_heatmap_url || ""}:${report.vertex_count || ""}:${tinyStats.p75 || ""}:${qem.heatmap_png_url || ""}`;
  if (hasScaleReport && lastScaleAnalysisKey !== reportKey) {
    lastScaleAnalysisKey = reportKey;
    window.requestAnimationFrame(openScaleModal);
  }
  renderAFCostCandidates(state.afcostCandidates);
}

function renderAFCostCandidates(report) {
  const notice = $("afcostNotice");
  const grid = $("afcostGrid");
  if (!report || !(report.candidates || []).length) {
    notice.innerHTML = `
      <strong>Not generated yet</strong>
      <span>Generate combo scores to compare AFCost_00 through AFCost_11.</span>
    `;
    grid.innerHTML = "";
    return;
  }
  const errors = report.errors || [];
  notice.classList.toggle("error", Boolean(errors.length));
  notice.innerHTML = `
    <strong>${errors.length ? "Generated with issues" : "Combination scores ready"}</strong>
    <span>lambda=${escapeHtml(formatFloat(report.lambda, 3))}, eps=${escapeHtml(formatFloat(report.eps, 6))}, edge projection: P(e)=max(Pu,Pv), D(e)=max(Du,Dv).</span>
    ${errors.map((line) => `<span>${escapeHtml(line)}</span>`).join("")}
  `;
  grid.innerHTML = (report.candidates || [])
    .map((candidate) => `
      <div class="afcost-card">
        <h4>${escapeHtml(candidate.name || "-")}</h4>
        <small>${escapeHtml(candidate.formula || "")}</small>
        <div class="geometry-preview">${previewImageMarkup(candidate.heatmap_png_url, `${candidate.name || "AFCost"} heatmap`)}</div>
        <div class="scale-colorbar"><span>Low score</span><i></i><span>High score</span></div>
      </div>
    `)
    .join("");
  const reportKey = `${report.candidate_count || ""}:${report.edge_count || ""}:${(report.candidates || []).map((candidate) => candidate.heatmap_png_url || "").join("|")}`;
  if (lastAFCostCandidateKey !== reportKey) {
    lastAFCostCandidateKey = reportKey;
    window.requestAnimationFrame(openAFCostModal);
  }
}

function appendLog(line) {
  const stamp = new Date().toLocaleTimeString();
  logLines.push(`[${stamp}] ${line}`);
  $("logOutput").textContent = logLines.slice(-120).join("\n");
  $("logOutput").scrollTop = $("logOutput").scrollHeight;
}

function parseState(payload) {
  try {
    debugLog(`state payload received (${formatNumber(payload.length)} chars)`);
    renderState(JSON.parse(payload));
  } catch (error) {
    appendLog(`Failed to parse state: ${error}`);
    if (bridge && bridge.debugLog) {
      bridge.debugLog(`state parse failed: ${error}`);
    }
  }
}

function targetValue() {
  const value = Number($("targetTriangles").value);
  return Number.isFinite(value) && value > 0 ? Math.round(value) : 3000;
}

function buildModeText(build) {
  if (!build) return "";
  return build.optimized
    ? `Built optimized asset: target ${formatNumber(build.target_triangle_count)}, final ${formatNumber(build.final_triangle_count)} tris.`
    : `Built current model: ${formatNumber(build.final_triangle_count)} tris.`;
}

function bindUi() {
  $("selectFileBtn").addEventListener("click", () => {
    appendLog("Opening file picker...");
    bridge.selectBlendFile();
  });
  $("browseBlenderBtn").addEventListener("click", () => {
    appendLog("Opening Blender picker...");
    bridge.browseBlender();
  });
  $("browseOutputBtn").addEventListener("click", () => {
    appendLog("Opening output folder picker...");
    bridge.browseOutputFolder();
  });
  $("fitViewBtn").addEventListener("click", () => {
    viewportZoom = 1.0;
    $("zoomSlider").value = Math.round(viewportZoom * 100);
    appendLog("Viewport fit applied.");
  });
  $("zoomSlider").addEventListener("input", () => {
    viewportZoom = Number($("zoomSlider").value) / 100;
  });
  $("workflowActionBtn").addEventListener("click", () => {
    runWorkflowAction();
  });
  $("invertHeatmapsToggle").addEventListener("change", () => {
    heatmapInverted = $("invertHeatmapsToggle").checked;
    appendLog(heatmapInverted ? "Heatmaps inverted." : "Heatmaps restored to normal.");
    renderQemHeatmap(state.qemHeatmap);
    renderScaleAnalysis(state.scaleAnalysis);
  });
  $("exportHeatmapComparisonBtn").addEventListener("click", () => {
    exportHeatmapComparison();
  });
  $("generateAFCostBtn").addEventListener("click", () => {
    appendLog("Generate Combo Scores clicked.");
    bridge.generateAFCostCandidates();
  });
  $("openAFCostBtn").addEventListener("click", () => {
    renderAFCostCandidates(state.afcostCandidates);
    openAFCostModal();
  });
  $("exportAFCostBtn").addEventListener("click", () => {
    exportAFCostCandidates();
  });
  $("closeAFCostBtn").addEventListener("click", () => {
    closeAFCostModal();
  });
  $("afcostModal").addEventListener("click", (event) => {
    if (event.target === $("afcostModal")) closeAFCostModal();
  });
  $("simplificationReportBtn").addEventListener("click", () => {
    appendLog("Compare Last Reduction clicked.");
    bridge.generateSimplificationReport();
  });
  $("applyPreviewBtn").addEventListener("click", () => {
    appendLog("Apply Current Preview clicked.");
    $("optimizeToggle").checked = true;
    state.optimizeEnabled = true;
    if (bridge.setOptimizeEnabled) bridge.setOptimizeEnabled(true);
    bridge.applyCurrentPreview();
  });
  $("buildBtn").addEventListener("click", () => {
    appendLog(
      hasOptimizedPreviewForTarget()
        ? `Build clicked with optimized target ${formatNumber(targetValue())} tris.`
        : "Build clicked without candidate optimization.",
    );
    runWithOptionalPreprocess("build");
  });
  $("closePipelineBtn").addEventListener("click", () => {
    closePipelineReviewModal();
  });
  $("stopPipelineBtn").addEventListener("click", () => {
    if (hasPreviewForTarget()) {
      acceptCurrentPreviewResult();
    } else {
      appendLog("Pipeline review closed without applying a stage.");
      closePipelineReviewModal();
    }
  });
  $("applyPipelineStageBtn").addEventListener("click", () => {
    if (pipelineReviewAction === "accept_current") {
      acceptCurrentPreviewResult();
    } else {
      startOptimizePreview(pendingPipelineStage);
    }
  });
  $("pipelineModal").addEventListener("click", (event) => {
    if (event.target === $("pipelineModal")) closePipelineReviewModal();
  });
  $("closeQemBtn").addEventListener("click", () => {
    closeQemModal();
  });
  $("classicQemBtn").addEventListener("click", () => {
    qemViewMode = "classic";
    renderQemHeatmap(state.qemHeatmap);
  });
  $("featureQemBtn").addEventListener("click", () => {
    qemViewMode = "feature";
    renderQemHeatmap(state.qemHeatmap);
  });
  $("qemModal").addEventListener("click", (event) => {
    if (event.target === $("qemModal")) closeQemModal();
  });
  $("closeScaleBtn").addEventListener("click", () => {
    closeScaleModal();
  });
  $("scaleModal").addEventListener("click", (event) => {
    if (event.target === $("scaleModal")) closeScaleModal();
  });
  $("autoPreprocessToggle").addEventListener("change", () => {
    appendLog($("autoPreprocessToggle").checked ? "Auto cleanup enabled." : "Auto cleanup disabled.");
    startAutoPreprocessAfterImportIfNeeded();
  });
  $("targetTriangles").addEventListener("input", () => {
    const value = targetValue();
    $("targetSlider").value = Math.min(Math.max(value, 1000), 30000);
    state.targetTriangles = value;
    if (bridge.setTargetTriangles) bridge.setTargetTriangles(value);
    updateBusy();
    renderGeometryReport(state.geometryReport);
  });
  $("targetSlider").addEventListener("input", () => {
    $("targetTriangles").value = $("targetSlider").value;
    state.targetTriangles = Number($("targetSlider").value);
    if (bridge.setTargetTriangles) bridge.setTargetTriangles(state.targetTriangles);
    updateBusy();
    renderGeometryReport(state.geometryReport);
  });
  document.querySelectorAll("[data-target]").forEach((button) => {
    button.addEventListener("click", () => {
      $("targetTriangles").value = button.dataset.target;
      $("targetSlider").value = button.dataset.target;
      state.targetTriangles = Number(button.dataset.target);
      if (bridge.setTargetTriangles) bridge.setTargetTriangles(state.targetTriangles);
      updateBusy();
      renderGeometryReport(state.geometryReport);
    });
  });
}

new QWebChannel(qt.webChannelTransport, (channel) => {
  bridge = channel.objects.assetForge;
  bridge.stateChanged.connect(parseState);
  bridge.logAdded.connect(appendLog);
  bindUi();
  bridge.initialState(parseState);
  appendLog("OccamForge UI ready.");
});
