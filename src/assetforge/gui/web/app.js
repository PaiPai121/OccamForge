let bridge = null;
let state = {};
const logLines = [];
let viewportUrl = null;
let viewportFrame = 0;
let lastAnalysisDebugKey = null;
let lastViewportDebugKey = null;
let firstViewportFrameLogged = false;
let viewportZoom = 1.0;
const VIEW_YAW = 0.62;
const VIEW_PITCH = -0.22;

const $ = (id) => document.getElementById(id);

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString();
}

function basename(path) {
  if (!path) return "No file selected";
  return String(path).split(/[\\/]/).pop();
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
  const optimizeEnabled = Boolean($("optimizeToggle").checked);
  $("analyzeBtn").disabled = state.busy || !hasFile;
  $("previewBtn").disabled = state.busy || !hasFile || !optimizeEnabled;
  $("buildBtn").disabled = state.busy || !hasFile;
  $("applyPreviewBtn").disabled = state.busy || !state.currentPreviewTarget || !optimizeEnabled;
  $("selectFileBtn").disabled = state.busy;
  $("browseBlenderBtn").disabled = state.busy;
  $("browseOutputBtn").disabled = false;
  $("targetTriangles").disabled = !optimizeEnabled;
  $("targetSlider").disabled = !optimizeEnabled;
  document.querySelectorAll("[data-target]").forEach((button) => {
    button.disabled = !optimizeEnabled;
  });
  $("optimizeControls").classList.toggle("enabled", optimizeEnabled);
}

function renderState(nextState) {
  state = nextState || {};
  $("targetTriangles").value = state.targetTriangles || 15000;
  $("targetSlider").value = Math.min(Math.max(Number(state.targetTriangles || 15000), 1000), 30000);
  $("optimizeToggle").checked = Boolean(state.optimizeEnabled);
  setText("fileTitle", basename(state.selectedFile));
  setText("statusText", state.status || "Ready");
  $("statusText").classList.toggle("success", Boolean(state.build && !(state.build.errors && state.build.errors.length)));
  setText("outputFolderValue", state.outputFolder || "-");
  setText("outputFolderSource", outputSourceLabel(state.outputFolderSource));
  updateBusy();

  const analysis = state.analysis;
  setText("bodyValue", analysis ? (analysis.has_vehicle_body ? "Detected" : "Missing") : "-");
  setText("wheelValue", analysis ? formatNumber(analysis.wheel_count) : "-");
  setText("objectValue", analysis ? formatNumber(analysis.object_count) : "-");
  setText("vertexValue", analysis ? formatNumber(analysis.vertex_count) : "-");
  setText("triangleValue", analysis ? formatNumber(analysis.triangle_count) : "-");

  const preview = state.realPreview;
  const item = preview && preview.items && preview.items.length ? preview.items[0] : null;
  if (item) {
    viewportUrl = null;
    cancelAnimationFrame(viewportFrame);
    setText("previewEyebrow", "Real Preview");
    setText("previewTitle", "Optimization result");
    $("previewStage").innerHTML = previewImageMarkup(item.preview_image_url, "Optimization preview");
    setText("metricOriginal", `${formatNumber(preview.original_triangle_count)} tris`);
    setText("metricTarget", `${formatNumber(item.target_triangles)} tris`);
    setText("metricActual", `${formatNumber(item.actual_triangles)} tris`);
    setText("metricReduction", `${Number(item.reduction_percent).toFixed(2)}%`);
    setText("metricScore", item.compatibility_score);
    setText("metricRating", item.rating);
    const notices = [...(item.warnings || []), ...(item.errors || [])];
    $("previewNotice").textContent = notices.join(" ");
  } else if (analysis && analysis.preview_mesh_url) {
    const debugKey = `${analysis.preview_mesh_url}:${analysis.triangle_count}`;
    if (lastAnalysisDebugKey !== debugKey) {
      lastAnalysisDebugKey = debugKey;
      debugLog(`analysis state received, busy=${Boolean(state.busy)}, triangles=${formatNumber(analysis.triangle_count)}, mesh_path=${analysis.preview_mesh_path || "none"}`);
    }
    setText("previewEyebrow", "Viewport Preview");
    setText("previewTitle", "Analyzed model");
    if (analysis.preview_mesh_path) {
      requestViewportMesh(analysis);
    } else {
      debugLog("analysis had no preview_mesh_path");
      $("previewStage").innerHTML = '<div class="empty-preview">Viewport preview data is unavailable</div>';
    }
    setText("metricOriginal", `${formatNumber(analysis.triangle_count)} tris`);
    setText("metricTarget", "-");
    setText("metricActual", `${formatNumber(analysis.triangle_count)} tris`);
    setText("metricReduction", "0.00%");
    setText("metricScore", "-");
    setText("metricRating", "Original");
    const notices = [...(analysis.warnings || []), ...(analysis.errors || [])];
    $("previewNotice").textContent = notices.join(" ");
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
    $("previewNotice").textContent = "";
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
  return Number.isFinite(value) && value > 0 ? Math.round(value) : 15000;
}

function buildModeText(build) {
  if (!build) return "";
  return build.optimized
    ? `Optimization ON: target ${formatNumber(build.target_triangle_count)}, final ${formatNumber(build.final_triangle_count)} tris.`
    : `Optimization OFF: preserved ${formatNumber(build.final_triangle_count)} tris.`;
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
  $("analyzeBtn").addEventListener("click", () => {
    appendLog("Refresh Model Info clicked.");
    bridge.analyze();
  });
  $("previewBtn").addEventListener("click", () => {
    appendLog(`Generate Real Preview clicked for ${formatNumber(targetValue())} tris.`);
    bridge.generateRealPreview(targetValue());
  });
  $("applyPreviewBtn").addEventListener("click", () => {
    appendLog("Apply Current Preview clicked.");
    $("optimizeToggle").checked = true;
    state.optimizeEnabled = true;
    if (bridge.setOptimizeEnabled) bridge.setOptimizeEnabled(true);
    bridge.applyCurrentPreview();
  });
  $("buildBtn").addEventListener("click", () => {
    const optimize = $("optimizeToggle").checked;
    appendLog(optimize ? `Build clicked with optimization target ${formatNumber(targetValue())} tris.` : "Build clicked without optimization.");
    bridge.buildCitiesSkylinesAsset(targetValue(), optimize);
  });
  $("optimizeToggle").addEventListener("change", () => {
    state.optimizeEnabled = $("optimizeToggle").checked;
    updateBusy();
    if (bridge.setOptimizeEnabled) bridge.setOptimizeEnabled(state.optimizeEnabled);
    appendLog(state.optimizeEnabled ? "Optimization enabled." : "Optimization disabled; original mesh will be preserved.");
  });
  $("targetTriangles").addEventListener("input", () => {
    const value = targetValue();
    $("targetSlider").value = Math.min(Math.max(value, 1000), 30000);
    state.targetTriangles = value;
  });
  $("targetSlider").addEventListener("input", () => {
    $("targetTriangles").value = $("targetSlider").value;
    state.targetTriangles = Number($("targetSlider").value);
  });
  document.querySelectorAll("[data-target]").forEach((button) => {
    button.addEventListener("click", () => {
      $("targetTriangles").value = button.dataset.target;
      $("targetSlider").value = button.dataset.target;
      state.targetTriangles = Number(button.dataset.target);
    });
  });
}

new QWebChannel(qt.webChannelTransport, (channel) => {
  bridge = channel.objects.assetForge;
  bridge.stateChanged.connect(parseState);
  bridge.logAdded.connect(appendLog);
  bindUi();
  bridge.initialState(parseState);
  appendLog("AssetForge UI ready.");
});
