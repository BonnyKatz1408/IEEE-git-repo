import * as THREE from 'three';
import { OrbitControls } from 'https://cdn.jsdelivr.net/npm/three@0.178.0/examples/jsm/controls/OrbitControls.js';

const formMessage = document.getElementById('form-message');
const analyzeButton = document.getElementById('analyze-btn');
const repositoryInput = document.getElementById('repo-url');
const landing = document.querySelector('.hero');
const analysisView = document.getElementById('analysis-view');
const analysisTitle = document.getElementById('analysis-title');
const newAnalysisButton = document.getElementById('new-analysis-btn');
const mapCanvas = document.getElementById('map-canvas');
const mapTooltip = document.getElementById('map-tooltip');
const mapSidebar = document.getElementById('map-sidebar');
const mapStats = document.getElementById('map-stats');
const analysisInspector = document.getElementById('analysis-inspector');
const mapPanel = document.querySelector('.map-panel');
const resetViewButton = document.getElementById('reset-view-btn');
const askPanel = document.getElementById('ask-panel');
const askButton = document.getElementById('ask-btn');
const repoQuestionInput = document.getElementById('repo-question');
const askResult = document.getElementById('ask-result');
const askChips = document.querySelectorAll('[data-question]');
const askReopen = document.getElementById('ask-reopen');
const askMinimize = document.getElementById('ask-minimize');
const askClose = document.getElementById('ask-close');

const HOTSPOT_ROOF = 0xf28a2d;
const HOTSPOT_EMPHASIS = 0xff5a36;

let activeMap = null;
let currentAnalysis = null;
let currentRepoUrl = '';
let currentFocusContext = {};
let aiPanelMinimized = false;

function syncAiPanelPosition() {
    if (!mapPanel || !analysisInspector) return;
    if (analysisInspector.classList.contains('hidden')) {
        mapPanel.style.setProperty('--ask-right-offset', '16px');
        return;
    }
    const mapBounds = mapPanel.getBoundingClientRect();
    const inspectorBounds = analysisInspector.getBoundingClientRect();
    const inspectorGap = 20;
    const rightOffset = Math.max(16, mapBounds.right - inspectorBounds.left + inspectorGap);
    mapPanel.style.setProperty('--ask-right-offset', `${rightOffset}px`);
}

const inspectorObserver = new MutationObserver(syncAiPanelPosition);
inspectorObserver.observe(analysisInspector, { attributes: true, attributeFilter: ['class'], childList: true });
window.addEventListener('resize', syncAiPanelPosition);

function setAiPanelState(open, minimized = false) {
    aiPanelMinimized = minimized;
    askPanel?.classList.toggle('hidden', !open);
    askReopen?.classList.toggle('hidden', open);
    syncAiPanelPosition();
}

function showMessage(message, kind = 'error') {
    formMessage.textContent = message;
    formMessage.className = `form-message ${kind}`;
}

function setLoading(loading) {
    analyzeButton.disabled = loading;
    analyzeButton.textContent = loading ? 'Analyzing repository...' : 'Map Repository';
}

function setAskLoading(loading) {
    askButton.disabled = loading;
    askButton.textContent = loading ? 'Asking...' : 'Ask';
}

function parseCitation(reference) {
    const match = String(reference || '').match(/^(.+?):(\d+)(?:-(\d+))?$/);
    if (!match) return { file: String(reference || ''), line: null };
    return { file: match[1], line: Number(match[2]) };
}

function sourceModeLabel(mode, grounded, sourceCount) {
    if (!grounded || !sourceCount) return 'Deterministic analysis · insufficient retrieved context';
    if (mode === 'deterministic-analysis') return 'Deterministic analysis';
    if (mode === 'gemini-rag') return 'Gemini explanation · grounded by retrieved source';
    return 'Deterministic analysis + retrieved source';
}

function decodeAnswerText(value) {
    const decoder = document.createElement('textarea');
    decoder.innerHTML = String(value || '');
    return decoder.value
        .replace(/\\([\\`*_[\]{}()#+.!>-])/g, '$1')
        .replace(/\\n/g, '\n');
}

function renderInlineMarkdown(value) {
    const code = [];
    const withPlaceholders = decodeAnswerText(value).replace(/`([^`\n]+)`/g, (_, content) => {
        code.push(`<code>${escapeHtml(content.trim())}</code>`);
        return `\u0000${code.length - 1}\u0000`;
    });
    let html = escapeHtml(withPlaceholders)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/__(.+?)__/g, '<strong>$1</strong>')
        .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
        .replace(/(?<!_)_([^_\n]+)_(?!_)/g, '<em>$1</em>');
    html = html.replace(/\u0000(\d+)\u0000/g, (_, index) => code[Number(index)] || '');
    return html;
}

function renderMarkdownAnswer(value) {
    const lines = decodeAnswerText(value).split(/\r?\n/);
    const output = [];
    let paragraph = [];
    let listType = null;

    const closeList = () => {
        if (listType) output.push(`</${listType}>`);
        listType = null;
    };
    const flushParagraph = () => {
        if (paragraph.length) {
            output.push(`<p>${paragraph.map(renderInlineMarkdown).join('<br>')}</p>`);
            paragraph = [];
        }
    };

    lines.forEach((line) => {
        const heading = line.match(/^\s*(#{1,4})\s+(.+?)\s*$/);
        const ordered = line.match(/^\s*\d+[.)]\s+(.+?)\s*$/);
        const unordered = line.match(/^\s*[-*+]\s+(.+?)\s*$/);
        if (heading) {
            flushParagraph();
            closeList();
            const level = Math.min(heading[1].length + 2, 6);
            output.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
        } else if (ordered || unordered) {
            flushParagraph();
            const nextType = ordered ? 'ol' : 'ul';
            if (listType !== nextType) {
                closeList();
                output.push(`<${nextType}>`);
                listType = nextType;
            }
            output.push(`<li>${renderInlineMarkdown((ordered || unordered)[1])}</li>`);
        } else if (!line.trim()) {
            flushParagraph();
            closeList();
        } else {
            closeList();
            paragraph.push(line.trim());
        }
    });
    flushParagraph();
    closeList();
    return output.join('');
}

function renderDeterministicAnswer(response) {
    const sections = response.sections || [];
    if (!sections.length) return `<p class="ask-answer-copy">${escapeHtml(response.answer || 'No answer available.')}</p>`;
    return sections.map((section) => `
        <section class="answer-section">
            <h4>${escapeHtml(section.title || 'Details')}</h4>
            <div class="answer-items">
                ${(section.items || []).map((item, index) => {
                    const path = item.path || '';
                    const line = item.line ? Number(item.line) : null;
                    const endLine = item.end_line ? Number(item.end_line) : line;
                    const reference = path && line ? `${path}:${line}${endLine && endLine !== line ? `-${endLine}` : ''}` : path;
                    const label = item.label || path || 'Unspecified';
                    const metadata = item.meta || item.reason || '';
                    const focus = path && response.mode === 'deterministic-analysis'
                        ? `<button type="button" class="answer-item-link" data-citation-file="${escapeHtml(path)}" data-citation-line="${line || ''}">${escapeHtml(label)}</button>`
                        : `<span class="answer-item-label">${escapeHtml(label)}</span>`;
                    return `<div class="answer-item"><span class="answer-index">${String(index + 1).padStart(2, '0')}</span><div>${focus}${reference && reference !== label ? `<span class="answer-item-path">${escapeHtml(reference)}</span>` : ''}${metadata ? `<span class="answer-item-meta">${escapeHtml(metadata)}</span>` : ''}</div></div>`;
                }).join('') || '<div class="answer-empty">No deterministic items found.</div>'}
            </div>
        </section>
    `).join('');
}

function showAskResult(answer, sources = [], mode = 'deterministic-rag-fallback', grounded = true) {
    if (!askPanel) return;
    setAiPanelState(true, false);
    if (!askResult) return;
    askResult.classList.remove('hidden');
    const response = typeof answer === 'object' ? answer : { answer, sources, mode, grounded };
    const sourceList = response.sources || sources;
    const modeLabel = sourceModeLabel(response.mode || mode, response.grounded ?? grounded, sourceList.length);
    const sourceButtons = sourceList.length ? sourceList.map((source) => {
        const parsed = parseCitation(source);
        return `<button type="button" class="citation-button" data-citation-file="${escapeHtml(parsed.file)}" data-citation-line="${parsed.line ?? ''}">${escapeHtml(source)}</button>`;
    }).join('') : '';
    askResult.innerHTML = `
        <h3>Grounded answer</h3>
        <span class="ask-source-mode ${response.mode === 'gemini-rag' ? 'retrieved' : ''}">${escapeHtml(modeLabel)}</span>
        ${response.mode === 'deterministic-analysis' ? renderDeterministicAnswer(response) : `<div class="ask-markdown">${renderMarkdownAnswer(response.answer || 'No answer available.')}</div>`}
        ${sourceButtons ? `<div class="answer-section citations-section"><h4>Sources</h4><div class="ask-citations">${sourceButtons}</div></div>` : '<p class="ask-empty">No repo-relative source citations were returned for this question.</p>'}
    `;
    askResult.querySelectorAll('[data-citation-file]').forEach((button) => {
        button.addEventListener('click', () => {
            const filePath = button.dataset.citationFile;
            const line = Number(button.dataset.citationLine || 0);
            if (!filePath || !currentAnalysis) return;
            const mapFile = currentAnalysis.map?.buildings?.find((file) => file.path === filePath || file.id === filePath);
            if (!mapFile) {
                showMessage(`This citation is not represented as a map building: ${filePath}.`, 'loading');
                return;
            }
            if (activeMap?.focusFile) activeMap.focusFile(filePath);
            renderInspectorForFile(currentAnalysis, filePath);
            if (line && currentAnalysis) {
                const fileMetric = fileMetricForPath(currentAnalysis, filePath);
                if (fileMetric) {
                    const pathValue = [...analysisInspector.querySelectorAll('.inspector-metric-value')].find((item) => item.textContent.includes(filePath));
                    if (pathValue) pathValue.title = `Line ${line}`;
                }
            }
        });
    });
}

async function askRepository(questionOverride = null, context = {}) {
    const repoUrl = currentRepoUrl || repositoryInput.value.trim();
    const question = (questionOverride ?? repoQuestionInput.value).trim();
    const usesSelectedFile = !Object.keys(context).length && /this file|depends on this|calls this|call this|what does this depend on/i.test(question);
    const requestContext = usesSelectedFile ? currentFocusContext : context;
    if (!repoUrl) {
        showMessage('Map a repository before asking a question.');
        return;
    }
    if (!question) {
        showMessage('Please ask a question about the repository.');
        return;
    }
    setAskLoading(true);
    try {
        const response = await fetch('/api/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: repoUrl, question, context: requestContext }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'The repository Q&A request failed.');
        setAiPanelState(false, false);
        if (repoQuestionInput) repoQuestionInput.value = question;
        showAskResult(result, result.sources || [], result.mode, result.grounded);
    } catch (error) {
        if (askPanel) askPanel.classList.remove('hidden');
        showAskResult({ answer: error.message || 'The repository Q&A request failed.', sources: [], mode: 'unavailable', grounded: false });
    } finally {
        setAskLoading(false);
    }
}

function fileName(path) {
    return String(path || '').split('/').pop() || path;
}

function metric(value) {
    return Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '0';
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character]));
}

function colorForModule(index) {
    const colors = [
        0x1f7ab8, 0x1eaf9f, 0x8b5dc7, 0xd15a8b, 0x2e9ccf, 0x4d9d5e,
        0x4c6edb, 0xe2913d, 0x3a9bb0, 0xc759a6, 0x3f9f89, 0x667ac9,
        0x1e79a8, 0xb56b3d, 0x2e7f6a, 0x9a4c72,
    ];
    return colors[index % colors.length];
}

function mixHexColors(a, b, amount) {
    const start = Number(a);
    const end = Number(b);
    const r = Math.round(((start >> 16) & 255) * (1 - amount) + ((end >> 16) & 255) * amount);
    const g = Math.round(((start >> 8) & 255) * (1 - amount) + ((end >> 8) & 255) * amount);
    const bChannel = Math.round((start & 255) * (1 - amount) + (end & 255) * amount);
    return (r << 16) | (g << 8) | bChannel;
}

function pastelPlateColor(hex) {
    return mixHexColors(hex, 0xf4f1ee, 0.72);
}

function makeLabel(text, color) {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    if (!context) return null;
    const fontSize = 26;
    const paddingX = 18;
    const paddingY = 18;
    context.font = `700 ${fontSize}px monospace`;
    const width = Math.ceil(context.measureText(text).width) + paddingX * 2;
    const height = Math.ceil(fontSize + paddingY * 1.4);
    const backingScale = 3;
    canvas.width = width * backingScale;
    canvas.height = height * backingScale;
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.scale(backingScale, backingScale);
    context.clearRect(0, 0, width, height);
    context.font = `700 ${fontSize}px monospace`;
    context.textBaseline = 'middle';
    context.textAlign = 'left';
    context.fillStyle = 'rgba(255, 255, 255, 0.94)';
    context.fillRect(0, 0, width, height);
    context.fillStyle = color;
    context.fillText(text, paddingX, height / 2 + 1);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.needsUpdate = true;
    const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthTest: false,
        depthWrite: false,
        alphaTest: 0.05,
    });
    const sprite = new THREE.Sprite(material);
    sprite.renderOrder = 1000;
    sprite.scale.set(width / 4.2, height / 4.2, 1);
    return sprite;
}

function mapData(report) {
    const layout = report.map || {};
    const files = (layout.buildings || []).map((item) => ({
        ...item,
        isHotspot: item.is_hotspot || item.isHotspot,
        fanIn: item.fan_in ?? item.fanIn,
        fanOut: item.fan_out ?? item.fanOut,
        moduleIndex: item.module_index ?? item.moduleIndex ?? 0,
    }));
    return {
        report,
        overview: report.overview || {},
        modules: layout.modules || [],
        districts: layout.districts || [],
        files,
        fileById: new Map(files.map((file) => [file.id, file])),
        fileEdges: layout.file_edges || [],
        moduleEdges: layout.module_edges || [],
        districtEdges: layout.district_edges || [],
        importantFiles: new Set(layout.important_files || []),
        labelImportantFiles: new Set((layout.important_files || []).slice(0, 12)),
        bounds: layout.bounds || { min_x: -80, max_x: 80, min_z: -80, max_z: 80, max_y: 40 },
    };
}

function createArc(from, to, color, opacity, radius = 0.7) {
    const start = new THREE.Vector3(from.x, from.y, from.z);
    const end = new THREE.Vector3(to.x, to.y, to.z);
    const distance = start.distanceTo(end);
    const control = new THREE.Vector3(
        (start.x + end.x) / 2,
        Math.max(start.y, end.y) + 28 + Math.min(42, distance * 0.12),
        (start.z + end.z) / 2,
    );
    const curve = new THREE.QuadraticBezierCurve3(start, control, end);
    const geometry = new THREE.TubeGeometry(curve, 16, radius, 5, false);
    const material = new THREE.MeshBasicMaterial({ color, transparent: true, opacity });
    const mesh = new THREE.Mesh(geometry, material);
    return mesh;
}

function createMap(report, onHover, onEdgeHover = () => {}) {
    const data = mapData(report);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf3f1ee);
    const width = Math.max(1, mapCanvas.clientWidth);
    const height = Math.max(1, mapCanvas.clientHeight);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mapCanvas.replaceChildren(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xdce9ff, 0x18202b, 2.2));
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.8);
    keyLight.position.set(100, 180, 80);
    scene.add(keyLight);

    const root = new THREE.Group();
    scene.add(root);
    const bounds = data.bounds;
    const centerX = ((bounds.min_x + bounds.max_x) / 2) || 0;
    const centerZ = ((bounds.min_z + bounds.max_z) / 2) || 0;
    const mapSpan = Math.max(bounds.max_x - bounds.min_x, bounds.max_z - bounds.min_z, 100);
    const ground = new THREE.Mesh(
        new THREE.PlaneGeometry(Math.max(mapSpan * 3.2, 720), Math.max(mapSpan * 3.2, 720)),
        new THREE.MeshStandardMaterial({ color: 0xf6f3ef, roughness: 1, metalness: 0 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(centerX, -7, centerZ);
    root.add(ground);
    const grid = new THREE.GridHelper(Math.max(mapSpan * 2.8, 640), 48, 0xc4ced9, 0xdfe5ee);
    grid.position.set(centerX, -6.8, centerZ);
    root.add(grid);

    const districtObjects = new Map();
    const moduleObjects = new Map();
    const buildings = [];
    const positions = new Map();
    const districtLabels = [];
    const moduleLabels = [];
    const fileLabels = [];

    data.districts.forEach((district) => {
        const plateColor = district.color ? pastelPlateColor(district.color) : 0xe9edf3;
        const plate = new THREE.Mesh(
            new THREE.BoxGeometry(district.width, 3, district.depth),
            new THREE.MeshStandardMaterial({ color: plateColor, transparent: true, opacity: 0.9, roughness: 1 }),
        );
        plate.position.set(district.x, -5.2, district.z);
        root.add(plate);
        const label = makeLabel(String(district.name).toUpperCase(), '#3d5368');
        if (label) {
            label.position.set(district.x, 28, district.z - district.depth / 2 - 10);
            label.scale.multiplyScalar(1.8);
            root.add(label);
            districtLabels.push(label);
        }
        districtObjects.set(district.id, { plate, label, visible: true });
    });

    data.modules.forEach((module) => {
        const plateColor = module.color ? pastelPlateColor(module.color) : pastelPlateColor(colorForModule(module.index || 0));
        const plate = new THREE.Mesh(
            new THREE.BoxGeometry(module.width, 5, module.depth),
            new THREE.MeshStandardMaterial({ color: plateColor, transparent: true, opacity: 0.98, roughness: 0.75 }),
        );
        plate.position.set(module.x, -3, module.z);
        root.add(plate);
        const label = makeLabel(String(module.name).toUpperCase(), '#49637c');
        if (label) {
            label.position.set(module.x, 16, module.z - module.depth / 2 - 10);
            label.scale.multiplyScalar(1.5);
            root.add(label);
            moduleLabels.push(label);
        }
        moduleObjects.set(module.id, { plate, label, objects: [], visible: true });
    });

    data.files.forEach((file) => {
        const moduleColor = colorForModule(file.moduleIndex);
        const bodyMaterial = new THREE.MeshStandardMaterial({
            color: moduleColor,
            roughness: 0.68,
            metalness: 0.04,
            emissive: file.isHotspot ? HOTSPOT_EMPHASIS : file.entry ? 0x214f61 : 0x000000,
            emissiveIntensity: file.isHotspot ? 0.55 : file.entry ? 0.7 : 0,
        });
        const roofMaterial = new THREE.MeshStandardMaterial({
            color: file.isHotspot ? HOTSPOT_ROOF : moduleColor,
            roughness: 0.45,
            metalness: 0.1,
            emissive: 0x000000,
            emissiveIntensity: 0,
        });
        const building = new THREE.Mesh(
            new THREE.BoxGeometry(file.width, file.height, file.depth),
            [bodyMaterial, bodyMaterial, roofMaterial, bodyMaterial, bodyMaterial, bodyMaterial],
        );
        building.position.set(file.x, file.height / 2, file.z);
        building.userData.file = file;
        root.add(building);
        buildings.push(building);
        positions.set(file.id, { x: file.x, y: file.height + 2, z: file.z });
        moduleObjects.get(file.module)?.objects.push(building);
        if (file.entry) {
            const beacon = new THREE.Mesh(
                new THREE.CylinderGeometry(2.6, 2.6, 3, 12),
                new THREE.MeshStandardMaterial({ color: 0x78e0e8, emissive: 0x78e0e8, emissiveIntensity: 0.8 }),
            );
            beacon.position.set(file.x, file.height + 3, file.z);
            root.add(beacon);
            moduleObjects.get(file.module)?.objects.push(beacon);
        }
        if (file.isHotspot || file.entry || data.labelImportantFiles.has(file.id)) {
            const label = makeLabel(file.name, file.isHotspot ? '#b45309' : file.entry ? '#0f766e' : '#31526d');
            if (label) {
                label.position.set(file.x, file.height + 15, file.z);
                label.scale.multiplyScalar(1.2);
                label.userData.fileId = file.id;
                label.userData.important = true;
                root.add(label);
                fileLabels.push(label);
            }
        }
    });

    const districtArcs = [];
    data.districtEdges.forEach((edge) => {
        const from = data.districts.find((item) => item.id === edge.from);
        const to = data.districts.find((item) => item.id === edge.to);
        if (!from || !to) return;
        const mesh = createArc({ x: from.x, y: 18, z: from.z }, { x: to.x, y: 18, z: to.z }, 0x5b7c99, 0.28, 1.4);
        mesh.userData.kind = 'district';
        root.add(mesh);
        districtArcs.push(mesh);
    });
    const moduleArcs = [];
    data.moduleEdges.forEach((edge) => {
        const from = data.modules.find((item) => item.id === edge.from);
        const to = data.modules.find((item) => item.id === edge.to);
        if (!from || !to) return;
        const mesh = createArc({ x: from.x, y: 16, z: from.z }, { x: to.x, y: 16, z: to.z }, 0x6d8bab, 0.22, 0.9);
        mesh.userData.kind = 'module';
        root.add(mesh);
        moduleArcs.push(mesh);
    });
    const fileArcs = [];
    data.fileEdges.slice(0, 80).forEach((edge) => {
        const from = positions.get(edge.from);
        const to = positions.get(edge.to);
        if (!from || !to) return;
        const source = data.fileById.get(edge.from);
        const target = data.fileById.get(edge.to);
        const mesh = createArc(from, to, 0x7892ad, 0.2, 0.55);
        mesh.userData.edge = { ...edge, from: source, to: target };
        mesh.visible = Boolean(source?.isHotspot || target?.isHotspot);
        root.add(mesh);
        fileArcs.push(mesh);
    });

    const camera = new THREE.OrthographicCamera(-width / 2, width / 2, height / 2, -height / 2, 0.1, mapSpan * 8 + 1000);
    const defaultCameraState = {
        position: new THREE.Vector3(centerX + mapSpan * 0.9, (bounds.max_y || 40) + mapSpan * 0.82, centerZ + mapSpan * 0.9),
        target: new THREE.Vector3(centerX, 0, centerZ),
        zoom: (Math.min(width, height) / (mapSpan * 1.3)) * 1.12,
        minZoom: 0.45,
        maxZoom: 4,
        enableRotate: false,
    };
    camera.position.copy(defaultCameraState.position);
    camera.lookAt(defaultCameraState.target);
    camera.zoom = defaultCameraState.zoom;
    camera.updateProjectionMatrix();
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enableRotate = false;
    controls.enablePan = true;
    controls.screenSpacePanning = true;
    controls.mouseButtons.LEFT = THREE.MOUSE.PAN;
    controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
    controls.minZoom = defaultCameraState.minZoom;
    controls.maxZoom = defaultCameraState.maxZoom;
    controls.target.copy(defaultCameraState.target);
    controls.update();

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let hovered = null;
    let selectedBuilding = null;

    function setBuildingEmphasis(building, selected) {
        if (!building) return;
        const file = building.userData.file;
        const materials = Array.isArray(building.material) ? building.material : [building.material];
        materials.forEach((material, index) => {
            const isRoof = index === 2;
            if (isRoof) {
                material.color.setHex(file.isHotspot ? HOTSPOT_ROOF : colorForModule(file.moduleIndex));
                material.emissive.setHex(selected ? 0xffffff : 0x000000);
                material.emissiveIntensity = selected ? 0.18 : 0;
                return;
            }
            material.color.setHex(colorForModule(file.moduleIndex));
            material.emissive.setHex(selected ? 0xffffff : file.isHotspot ? HOTSPOT_EMPHASIS : file.entry ? 0x214f61 : 0x000000);
            material.emissiveIntensity = selected ? 0.45 : file.isHotspot ? 0.55 : file.entry ? 0.8 : 0;
        });
    }

    function showConnectionsFor(file) {
        fileArcs.forEach((connection) => {
            const edge = connection.userData.edge;
            connection.visible = Boolean(
                edge?.from?.isHotspot || edge?.to?.isHotspot ||
                (file && (edge.from.id === file.id || edge.to.id === file.id)),
            );
        });
    }

    function lodLevel() {
        const relative = camera.zoom / defaultCameraState.zoom;
        if (relative < 0.72) return 'districts';
        if (relative < 0.95) return 'modules';
        if (relative < 1.55) return 'important';
        return 'detail';
    }

    function updateLod() {
        const level = lodLevel();
        const target = controls.target;
        districtLabels.forEach((label, index) => {
            label.visible = index < 24;
        });
        moduleLabels.forEach((label, index) => {
            label.visible = (level === 'modules' || level === 'important') && index < 36;
        });
        buildings.forEach((building) => {
            const file = building.userData.file;
            const important = file.isHotspot || file.entry || data.importantFiles.has(file.id);
            const dx = file.x - target.x;
            const dz = file.z - target.z;
            const near = (dx * dx + dz * dz) < (mapSpan * 0.18) ** 2;
            if (level === 'districts') building.visible = false;
            else if (level === 'modules') building.visible = important;
            else if (level === 'important') building.visible = important;
            else building.visible = important || near;
        });
        fileLabels.forEach((label) => {
            label.visible = level === 'important' || level === 'detail';
        });
        districtArcs.forEach((arc) => { arc.visible = level === 'districts'; });
        moduleArcs.forEach((arc) => { arc.visible = level === 'modules' || level === 'important'; });
        if (level === 'districts' || level === 'modules') {
            fileArcs.forEach((arc) => { arc.visible = false; });
        } else {
            showConnectionsFor(selectedBuilding?.userData.file || null);
        }
        data.districts.forEach((district) => {
            const object = districtObjects.get(district.id);
            if (object?.plate) object.plate.visible = level === 'districts';
        });
    }

    function clearSelection() {
        if (selectedBuilding) {
            setBuildingEmphasis(selectedBuilding, false);
            selectedBuilding = null;
        }
        showConnectionsFor(null);
        analysisInspector.classList.add('hidden');
        updateLod();
    }

    function pick(event) {
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);
        const hits = raycaster.intersectObjects(buildings.filter((item) => item.visible), false);
        return hits[0]?.object || null;
    }

    function pointerMove(event) {
        const hit = pick(event);
        const file = hit?.userData.file || null;
        const edgeHit = file ? null : raycaster.intersectObjects(fileArcs.filter((item) => item.visible), false)[0]?.object?.userData.edge || null;
        if (hovered && hovered !== hit && hovered !== selectedBuilding) setBuildingEmphasis(hovered, false);
        if (hit) setBuildingEmphasis(hit, true);
        hovered = hit;
        renderer.domElement.style.cursor = file || edgeHit ? 'pointer' : 'default';
        onHover(file, event);
        onEdgeHover(edgeHit, event);
    }

    function pointerDown(event) {
        const hit = pick(event);
        if (!hit) {
            clearSelection();
            return;
        }
        if (selectedBuilding && selectedBuilding !== hit) setBuildingEmphasis(selectedBuilding, false);
        selectedBuilding = hit;
        setBuildingEmphasis(selectedBuilding, true);
        const file = hit.userData.file;
        showConnectionsFor(file);
        renderInspectorForFile(currentAnalysis, file.path);
    }

    renderer.domElement.addEventListener('pointermove', pointerMove);
    renderer.domElement.addEventListener('pointerdown', pointerDown);
    renderer.domElement.addEventListener('pointerleave', () => {
        if (hovered && hovered !== selectedBuilding) setBuildingEmphasis(hovered, false);
        hovered = null;
        onHover(null);
        onEdgeHover(null);
    });
    controls.addEventListener('change', updateLod);

    const resizeObserver = new ResizeObserver(() => {
        const nextWidth = Math.max(1, mapCanvas.clientWidth);
        const nextHeight = Math.max(1, mapCanvas.clientHeight);
        renderer.setSize(nextWidth, nextHeight);
        camera.left = -nextWidth / 2;
        camera.right = nextWidth / 2;
        camera.top = nextHeight / 2;
        camera.bottom = -nextHeight / 2;
        camera.updateProjectionMatrix();
    });
    resizeObserver.observe(mapCanvas);

    let frame = 0;
    function animate() {
        frame = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
    }
    animate();
    updateLod();

    function focusOn(x, y, z, distanceScale = 0.55) {
        const direction = defaultCameraState.position.clone().sub(defaultCameraState.target).normalize();
        const focus = new THREE.Vector3(x, y, z);
        const distance = Math.max(90, mapSpan * distanceScale);
        controls.enableRotate = false;
        controls.minZoom = defaultCameraState.minZoom;
        controls.maxZoom = defaultCameraState.maxZoom;
        controls.target.copy(focus);
        camera.position.copy(focus.clone().add(direction.multiplyScalar(distance)));
        camera.updateProjectionMatrix();
        controls.update();
        updateLod();
    }

    function resetView() {
        controls.enableRotate = defaultCameraState.enableRotate;
        controls.minZoom = defaultCameraState.minZoom;
        controls.maxZoom = defaultCameraState.maxZoom;
        camera.position.copy(defaultCameraState.position);
        camera.zoom = defaultCameraState.zoom;
        controls.target.copy(defaultCameraState.target);
        camera.updateProjectionMatrix();
        controls.update();
        clearSelection();
    }

    return {
        toggleDistrict(moduleName) {
            const district = moduleObjects.get(moduleName);
            if (!district) return false;
            district.visible = !district.visible;
            const opacity = district.visible ? 1 : 0.16;
            const apply = (object) => {
                const materials = Array.isArray(object.material) ? object.material : [object.material];
                materials.forEach((material) => {
                    material.transparent = true;
                    material.opacity = object === district.plate ? (district.visible ? 0.16 : 0.05) : opacity;
                });
            };
            apply(district.plate);
            district.objects.forEach(apply);
            if (district.label?.material) district.label.material.opacity = district.visible ? 1 : 0.16;
            return district.visible;
        },
        focusFile(filePath) {
            const file = data.files.find((item) => item.path === filePath || item.id === filePath);
            if (!file) return;
            const matching = buildings.find((mesh) => mesh.userData.file.id === file.id);
            if (matching) {
                if (selectedBuilding && selectedBuilding !== matching) setBuildingEmphasis(selectedBuilding, false);
                selectedBuilding = matching;
                setBuildingEmphasis(matching, true);
                showConnectionsFor(file);
            }
            focusOn(file.x, file.height, file.z, 0.42);
            renderInspectorForFile(data.report, file.path);
        },
        focusModule(moduleName) {
            const module = data.modules.find((item) => item.id === moduleName || item.name === moduleName);
            if (!module) return;
            focusOn(module.x, 20, module.z, 0.7);
            renderInspectorForModule(data.report, moduleName);
        },
        focusFunction(qualifiedName, analysis) {
            const functionMetric = functionMetricForQualifiedName(analysis, qualifiedName);
            if (functionMetric?.file) this.focusFile(functionMetric.file);
            renderInspectorForEntry(analysis, qualifiedName);
        },
        resetView,
        dispose() {
            cancelAnimationFrame(frame);
            resizeObserver.disconnect();
            controls.removeEventListener('change', updateLod);
            renderer.domElement.removeEventListener('pointermove', pointerMove);
            renderer.domElement.removeEventListener('pointerdown', pointerDown);
            controls.dispose();
            root.traverse((object) => {
                if (!(object instanceof THREE.Mesh || object instanceof THREE.Sprite)) return;
                object.geometry?.dispose();
                const material = object.material;
                if (Array.isArray(material)) material.forEach((entry) => entry.dispose());
                else material?.dispose();
            });
            renderer.dispose();
            renderer.domElement.remove();
        },
    };
}

function renderTooltip(file, event) {
    if (!file) {
        mapTooltip.classList.add('hidden');
        return;
    }
    mapTooltip.innerHTML = `<strong>${escapeHtml(file.name)}</strong><span>${escapeHtml(file.path)}</span><span>${metric(file.loc)} LOC · ${metric(file.functions)} functions · hotspot ${Number(file.hotspot).toFixed(2)}</span>`;
    const rect = mapCanvas.getBoundingClientRect();
    mapTooltip.style.left = `${event.clientX - rect.left + 14}px`;
    mapTooltip.style.top = `${event.clientY - rect.top + 14}px`;
    mapTooltip.classList.remove('hidden');
}

function renderEdgeTooltip(edge, event) {
    if (!edge) return;
    mapTooltip.innerHTML = `<strong>${escapeHtml(edge.from?.path || '')} → ${escapeHtml(edge.to?.path || '')}</strong><span>${edge.weight || 0} architecture signal${edge.weight === 1 ? '' : 's'}</span>`;
    const rect = mapCanvas.getBoundingClientRect();
    mapTooltip.style.left = `${event.clientX - rect.left + 14}px`;
    mapTooltip.style.top = `${event.clientY - rect.top + 14}px`;
    mapTooltip.classList.remove('hidden');
}

function collectFlowNodes(node, items = []) {
    if (!node) return items;
    const name = node.qualified_name || node.node;
    if (name) items.push(name);
    (node.children || []).forEach((child) => collectFlowNodes(child, items));
    return items;
}

function fileMetricForPath(report, filePath) {
    return (report?.file_metrics || []).find((item) => item.file === filePath) || null;
}

function moduleMetricForName(report, moduleName) {
    return (report?.modules || []).find((item) => item.module === moduleName) || null;
}

function functionMetricForQualifiedName(report, qualifiedName) {
    return (report?.function_metrics || []).find((item) => item.qualified_name === qualifiedName) || null;
}

function unique(values) {
    return [...new Set(values.filter(Boolean))];
}

function listBlock(title, values) {
    const items = unique(values).slice(0, 8);
    if (!items.length) return '';
    return `<div class="inspector-why"><h3>${escapeHtml(title)}</h3><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>`;
}

function renderInspectorForFile(report, filePath) {
    const fileMetric = fileMetricForPath(report, filePath);
    if (!fileMetric) return;
    const moduleName = filePath.split('/').slice(0, -1).join('/') || '.';
    const moduleMetric = moduleMetricForName(report, moduleName);
    const hotspot = (report.hotspots?.files || []).find((item) => item.file === filePath);
    const reading = (report.reading_order || []).find((item) => item.file === filePath);
    const entry = (report.entry_points || []).find((item) => item.file === filePath);
    const reasons = unique([
        ...(hotspot?.evidence || []),
        ...(reading?.evidence || []),
        ...(entry?.explanation?.basis || []),
        ...(fileMetric.evidence || []),
    ]);
    const role = fileMetric.is_test ? 'test' : entry ? 'likely entry point' : hotspot ? 'hotspot' : 'implementation file';
    const imports = (report.import_edges || []).filter((edge) => edge.from === filePath).map((edge) => edge.to);
    const importedBy = (report.import_edges || []).filter((edge) => edge.to === filePath).map((edge) => edge.from);
    const calls = (report.function_edges || []).filter((edge) => String(edge.from || '').split('::')[0] === filePath).map((edge) => edge.to);
    const callers = (report.function_edges || []).filter((edge) => String(edge.to || '').split('::')[0] === filePath).map((edge) => edge.from);
    currentFocusContext = { type: 'file', file: filePath, analysis: { role, loc: fileMetric.loc || 0, hotspot_score: fileMetric.hotspot_score || 0 } };
    analysisInspector.classList.remove('hidden');
    analysisInspector.innerHTML = `
        <div class="inspector-header">
            <div>
                <h3>File</h3>
                <span class="inspector-title">${escapeHtml(fileName(filePath))}</span>
            </div>
        </div>
        <div class="inspector-metrics">
            <div class="inspector-metric"><span class="inspector-metric-label">Path</span><span class="inspector-metric-value">${escapeHtml(filePath)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">LOC</span><span class="inspector-metric-value">${metric(fileMetric.loc || 0)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Functions</span><span class="inspector-metric-value">${metric(fileMetric.number_of_defined_functions || 0)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Hotspot</span><span class="inspector-metric-value">${Number(fileMetric.hotspot_score || 0).toFixed(2)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Fan-in</span><span class="inspector-metric-value">${metric((fileMetric.incoming_call_dependencies || 0) + (fileMetric.incoming_import_dependencies || 0))}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Fan-out</span><span class="inspector-metric-value">${metric((fileMetric.outgoing_call_dependencies || 0) + (fileMetric.outgoing_import_dependencies || 0))}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Role</span><span class="inspector-metric-value">${escapeHtml(role)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Module</span><span class="inspector-metric-value">${escapeHtml(moduleMetric?.module || moduleName)}</span></div>
        </div>
        <div class="inspector-why">
            <h3>Why it stands out</h3>
            <ul>${(reasons.length ? reasons : ['No elevated structural score.']).map((reason) => `<li>${escapeHtml(reason)}</li>`).join('')}</ul>
        </div>
        <button type="button" class="inspector-action" data-explain-question="${escapeHtml(`Explain this file: ${filePath}`)}" data-explain-context="file">Explain this file</button>
        ${listBlock('Imports', imports)}
        ${listBlock('Imported by', importedBy)}
        ${listBlock('Calls', calls)}
        ${listBlock('Called by', callers)}
    `;

    const explainButton = analysisInspector.querySelector('[data-explain-question]');
    if (explainButton) {
        explainButton.addEventListener('click', () => {
            askRepository(explainButton.dataset.explainQuestion, {
                type: 'file',
                file: filePath,
                analysis: { role, hotspot: fileMetric.hotspot_score || 0, loc: fileMetric.loc || 0 },
            });
        });
    }
}

function renderInspectorForEntry(report, entryPoint) {
    const flow = (report?.flows || []).find((item) => item.entry_point === entryPoint) || null;
    const functionMetric = functionMetricForQualifiedName(report, entryPoint);
    const how = (report?.how_it_works || report?.ui_summary?.how_it_works || []).find((item) => item.entry_point === entryPoint);
    const rootName = entryPoint ? entryPoint.split('::').slice(-1)[0] : 'entry';
    const chain = flow?.tree ? collectFlowNodes(flow.tree, []) : [];
    analysisInspector.classList.remove('hidden');
    analysisInspector.innerHTML = `
        <div class="inspector-header">
            <div>
                <h3>Function</h3>
                <span class="inspector-title">${escapeHtml(rootName)}</span>
            </div>
        </div>
        <div class="inspector-metrics">
            <div class="inspector-metric"><span class="inspector-metric-label">File</span><span class="inspector-metric-value">${escapeHtml(functionMetric?.file || '')}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">LOC</span><span class="inspector-metric-value">${metric(functionMetric?.loc || 0)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Fan-in</span><span class="inspector-metric-value">${metric(functionMetric?.fan_in || 0)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Fan-out</span><span class="inspector-metric-value">${metric(functionMetric?.fan_out || 0)}</span></div>
        </div>
        <div class="inspector-flow">
            <h3>How execution moves</h3>
            <ul>
                ${(how?.steps || []).map((step) => `<li><strong>${escapeHtml(String(step.function || '').split('::').slice(-1)[0])}</strong> ${escapeHtml(step.text || '')}</li>`).join('') || chain.map((node) => `<li>${escapeHtml(node.split('::').slice(-1)[0])}</li>`).join('') || '<li>No bounded dependency chain.</li>'}
            </ul>
        </div>
        <button type="button" class="inspector-action" data-explain-question="${escapeHtml(`Explain this function: ${entryPoint}`)}" data-explain-context="function">Explain this function</button>
    `;

    const explainButton = analysisInspector.querySelector('[data-explain-question]');
    if (explainButton) {
        explainButton.addEventListener('click', () => {
            askRepository(explainButton.dataset.explainQuestion, {
                type: 'function',
                qualified_name: entryPoint,
                file: functionMetric?.file || '',
                analysis: { fan_in: functionMetric?.fan_in || 0, fan_out: functionMetric?.fan_out || 0 },
            });
        });
    }
}

function renderInspectorForModule(report, moduleName) {
    const item = moduleMetricForName(report, moduleName);
    if (!item) return;
    analysisInspector.classList.remove('hidden');
    analysisInspector.innerHTML = `
        <div class="inspector-header">
            <div>
                <h3>Module</h3>
                <span class="inspector-title">${escapeHtml(moduleName)}</span>
            </div>
        </div>
        <div class="inspector-metrics">
            <div class="inspector-metric"><span class="inspector-metric-label">LOC</span><span class="inspector-metric-value">${metric(item.total_loc || 0)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Files</span><span class="inspector-metric-value">${metric((item.files || []).length)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Definitions</span><span class="inspector-metric-value">${metric(item.number_of_definitions || 0)}</span></div>
            <div class="inspector-metric"><span class="inspector-metric-label">Hotspot</span><span class="inspector-metric-value">${Number(item.hotspot_score || 0).toFixed(2)}</span></div>
        </div>
        <div class="inspector-why">
            <h3>Why this matters</h3>
            <ul>${(item.evidence || [item.description]).filter(Boolean).map((reason) => `<li>${escapeHtml(reason)}</li>`).join('')}</ul>
        </div>
    `;
}

function bindFocusButtons(root) {
    root.querySelectorAll('[data-focus-type]').forEach((button) => {
        button.addEventListener('click', () => {
            if (!currentAnalysis || !activeMap) return;
            const type = button.dataset.focusType;
            const value = button.dataset.focusValue || '';
            if (type === 'file' || type === 'hotspot' || type === 'reading') activeMap.focusFile(value);
            if (type === 'module') activeMap.focusModule(value);
            if (type === 'entry' || type === 'flow') activeMap.focusFunction(value, currentAnalysis);
        });
    });
}

function renderSidebar(report) {
    const data = report.ui_summary || {};
    const overview = data.overview || report.overview || {};
    const entries = data.entry_points || [];
    const hotspots = data.top_hotspots || [];
    const modules = data.major_modules || [];
    const reading = data.reading_order || [];
    const flows = data.flows || report.flows || [];
    mapSidebar.innerHTML = `
        <section class="guide-section">
            <p class="sidebar-title">What this repo is</p>
            <strong>${metric(overview.file_count || 0)} files</strong>
            <small>${metric(overview.function_count || 0)} functions · ${metric(overview.module_count || 0)} modules · ${(overview.languages || []).join(', ') || 'mixed'}</small>
        </section>
        <section class="guide-section">
            <p class="sidebar-title">Where execution starts</p>
            <div class="brief-list">${entries.length ? entries.map((entry) => `<button type="button" data-focus-type="entry" data-focus-value="${escapeHtml(entry.qualified_name || '')}"><strong>${escapeHtml(entry.name || fileName(entry.file))}</strong><small>${escapeHtml(entry.file || '')}${entry.structural_hints?.length ? ` · ${escapeHtml(entry.structural_hints.join(', '))}` : ''}</small></button>`).join('') : '<small>No likely entry points.</small>'}</div>
        </section>
        <section class="guide-section">
            <p class="sidebar-title">What matters</p>
            <div class="brief-list">${hotspots.length ? hotspots.map((item) => `<button type="button" data-focus-type="hotspot" data-focus-value="${escapeHtml(item.file || '')}"><strong>${escapeHtml(fileName(item.file))}</strong><small>${escapeHtml((item.evidence || []).slice(0, 3).join(' · ') || `hotspot ${Number(item.hotspot_score || 0).toFixed(2)}`)}</small></button>`).join('') : '<small>No hotspot files.</small>'}</div>
        </section>
        <section class="guide-section">
            <p class="sidebar-title">Major parts</p>
            <div class="brief-list">${modules.length ? modules.map((item) => {
                const name = !item.module || item.module === '.' ? 'root' : item.module;
                return `<button type="button" data-focus-type="module" data-focus-value="${escapeHtml(item.module || '.')}"><strong>${escapeHtml(name)}</strong><small>${escapeHtml(item.description || `${metric(item.file_count || 0)} files`)}</small></button>`;
            }).join('') : '<small>No module groups.</small>'}</div>
        </section>
        <section class="guide-section">
            <p class="sidebar-title">How the main flow works</p>
            <div class="brief-list">${flows.length ? flows.map((flow) => {
                const chain = collectFlowNodes(flow.tree, []).slice(0, 6).map((node) => node.split('::').slice(-1)[0]).join(' → ');
                return `<button type="button" data-focus-type="flow" data-focus-value="${escapeHtml(flow.entry_point || '')}"><strong>${escapeHtml(String(flow.entry_point || '').split('::').slice(-1)[0])}</strong><small>${escapeHtml(chain)}</small></button>`;
            }).join('') : '<small>No bounded execution flows.</small>'}</div>
        </section>
        <section class="guide-section">
            <p class="sidebar-title">Where to start reading</p>
            <div class="brief-list">${reading.length ? reading.map((item) => `<button type="button" data-focus-type="reading" data-focus-value="${escapeHtml(item.file || '')}"><strong>${escapeHtml(item.display_name || fileName(item.file))}</strong><small>${escapeHtml((item.evidence || item.reason || []).slice(0, 3).join(' · ') || 'ranked starting file')}</small></button>`).join('') : '<small>No reading order.</small>'}</div>
        </section>
        <section class="guide-section">
            <p class="sidebar-title">Map language</p>
            <div class="guide-item"><b class="guide-icon height-icon">▂▅▇</b><span><strong>Height</strong><small>Lines of code, log-scaled.</small></span></div>
            <div class="guide-item"><b class="guide-icon colour-icon">▰</b><span><strong>Colour</strong><small>Module district.</small></span></div>
            <div class="landmark-row"><b class="diamond hotspot-diamond"></b><span><strong>Orange roof</strong><small>Hotspot landmark.</small></span></div>
            <div class="landmark-row"><b class="diamond entry-diamond"></b><span><strong>Cyan beacon</strong><small>Likely entry point.</small></span></div>
        </section>
    `;
    bindFocusButtons(mapSidebar);
}

function median(values) {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : Math.round((sorted[middle - 1] + sorted[middle]) / 2);
}

function renderStats(report) {
    const files = report.map?.buildings || report.file_metrics || [];
    const totalLoc = files.reduce((sum, file) => sum + (file.loc || 0), 0);
    mapStats.innerHTML = `<span>Files <b>${metric(files.length)}</b></span><span>Lines <b>${metric(totalLoc)}</b></span><span>Districts <b>${metric((report.map?.districts || report.modules || []).length)}</b></span><span>Median file <b>${metric(median(files.map((file) => file.loc || 0)))} lines</b></span><span class="language-strip">${(report.overview?.languages || []).map((language, index) => `<i style="background:#${colorForModule(index).toString(16).padStart(6, '0')}"></i>${escapeHtml(language)}`).join(' ')}</span>`;
}

async function analyzeRepository() {
    const url = repositoryInput.value.trim();
    if (!url) {
        showMessage('Paste a GitHub repository URL first.');
        repositoryInput.focus();
        return;
    }
    setLoading(true);
    showMessage('The analyzer is scanning, parsing, and weighting the repository...', 'loading');
    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Analysis failed.');
        analysisTitle.textContent = result.overview?.repository || url.replace(/^https?:\/\/(www\.)?github\.com\//i, '').replace(/\/$/, '');
        landing.classList.add('hidden');
        analysisView.classList.remove('hidden');
        document.body.classList.add('analysis-active');
        if (askPanel) askPanel.classList.remove('hidden');
        showMessage('');
        currentAnalysis = result;
        currentRepoUrl = url;
        renderSidebar(result);
        renderStats(result);
        activeMap?.dispose();
        activeMap = createMap(result, renderTooltip, renderEdgeTooltip);
        analysisTitle.title = result.version?.sha ? `${result.version.owner}/${result.version.repo}@${result.version.sha.slice(0, 12)}` : '';
        if (repoQuestionInput) repoQuestionInput.value = 'Explain the architecture of this repository.';
    } catch (error) {
        showMessage(error.message || 'Analysis failed.');
    } finally {
        setLoading(false);
    }
}

analyzeButton.addEventListener('click', analyzeRepository);
askButton.addEventListener('click', () => askRepository());
askReopen?.addEventListener('click', () => setAiPanelState(true, aiPanelMinimized));
askMinimize?.addEventListener('click', () => setAiPanelState(false, true));
askClose?.addEventListener('click', () => setAiPanelState(false, false));
askChips.forEach((chip) => {
    chip.addEventListener('click', () => askRepository(chip.dataset.question));
});
repoQuestionInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') askRepository();
});
repositoryInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') analyzeRepository();
});
resetViewButton.addEventListener('click', () => {
    activeMap?.resetView?.();
    analysisInspector.classList.add('hidden');
});
newAnalysisButton.addEventListener('click', () => {
    activeMap?.dispose();
    activeMap = null;
    analysisView.classList.add('hidden');
    landing.classList.remove('hidden');
    document.body.classList.remove('analysis-active');
    setAiPanelState(false, false);
    repositoryInput.focus();
});
