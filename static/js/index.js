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

let activeMap = null;

function showMessage(message, kind = 'error') {
    formMessage.textContent = message;
    formMessage.className = `form-message ${kind}`;
}

function setLoading(loading) {
    analyzeButton.disabled = loading;
    analyzeButton.textContent = loading ? 'Analyzing repository...' : 'Map Repository';
}

function fileName(path) {
    return path.split('/').pop() || path;
}

function metric(value) {
    return Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '0';
}

function normalizeReport(report) {
    const hotspotFiles = new Set((report.hotspots?.files || []).map((item) => item.file));
    const entryFiles = new Set((report.entry_points || []).map((item) => item.file));
    const modules = (report.modules || []).map((module, moduleIndex) => ({
        id: module.module || `module-${moduleIndex}`,
        name: module.module || 'root',
        files: module.files || [],
        index: moduleIndex,
    }));
    const moduleByFile = new Map();
    modules.forEach((module) => module.files.forEach((path) => moduleByFile.set(path, module)));

    const files = (report.file_metrics || []).map((raw, index) => {
        const path = raw.file || `file-${index}`;
        const module = moduleByFile.get(path);
        return {
            id: path,
            path,
            name: fileName(path),
            module: module?.name || path.split('/')[0] || 'root',
            moduleIndex: module?.index ?? 0,
            loc: Number(raw.loc) || 1,
            functions: Number(raw.number_of_defined_functions) || 0,
            hotspot: Number(raw.hotspot_score) || 0,
            isHotspot: hotspotFiles.has(path) || Number(raw.hotspot_score) > 0.65,
            fanIn: (Number(raw.incoming_import_dependencies) || 0) + (Number(raw.incoming_call_dependencies) || 0),
            fanOut: (Number(raw.outgoing_import_dependencies) || 0) + (Number(raw.outgoing_call_dependencies) || 0),
            entry: Boolean(raw.is_entry_point) || entryFiles.has(path),
        };
    });
    const fileById = new Map(files.map((file) => [file.id, file]));
    const calls = (report.function_edges || []).map((edge) => ({
        from: edge.from,
        to: edge.to,
        fromFile: String(edge.from || '').split('::')[0],
        toFile: String(edge.to || '').split('::')[0],
    }));
    const callByPair = new Map();
    calls.forEach((call) => callByPair.set(`${call.fromFile}\n${call.toFile}`, call));
    const edges = (report.architecture_edges || [])
        .map((edge) => {
            const from = fileById.get(String(edge.from));
            const to = fileById.get(String(edge.to));
            const call = callByPair.get(`${String(edge.from)}\n${String(edge.to)}`);
            return { from, to, call, weight: (edge.import_count || 0) + (edge.call_count || 0) };
        })
        .filter((edge) => edge.from && edge.to && edge.from.id !== edge.to.id);

    const hotspotEdges = edges.filter((edge) => edge.from.isHotspot || edge.to.isHotspot);
    return { overview: report.overview || {}, modules, files, edges, hotspotEdges, report };
}

function colorForModule(index) {
    const colors = [
        0x3f72c8, 0x18a999, 0x8557b8, 0xc44770, 0x2f9fc0, 0x6b9144,
        0x5f61c7, 0x9d5a36, 0x237f9b, 0xb23d91, 0x4e8b72, 0x7b6db2,
        0x2f6f9f, 0xa86d2d, 0x347f62, 0x99516e,
    ];
    return colors[index % colors.length];
}

function makeLabel(text, color) {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    if (!context) return null;
    const scale = 2;
    context.font = '700 22px monospace';
    const width = Math.ceil(context.measureText(text).width) + 24;
    canvas.width = width * scale;
    canvas.height = 38 * scale;
    context.scale(scale, scale);
    context.font = '700 22px monospace';
    context.fillStyle = 'rgba(255, 255, 255, 0.94)';
    context.fillRect(0, 0, width, 38);
    context.fillStyle = color;
    context.fillText(text, 12, 26);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false, depthWrite: false });
    const sprite = new THREE.Sprite(material);
    sprite.renderOrder = 1000;
    sprite.scale.set(width / 2.8, 11, 1);
    return sprite;
}

function mapLabelScale(moduleCount) {
    return Math.max(1.25, Math.min(2.1, 1.8 - moduleCount * 0.05));
}

function createMap(report, onHover, onEdgeHover = () => {}) {
    const data = normalizeReport(report);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf8f7f4);
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
    const positions = new Map();
    const districtObjects = new Map();
    const columns = Math.max(1, Math.ceil(Math.sqrt(Math.max(data.modules.length, 1))));
    const moduleRows = Math.max(1, Math.ceil(data.modules.length / columns));
    const moduleLayouts = data.modules.map((module) => {
        const fileCount = data.files.filter((file) => file.module === module.name).length;
        const fileColumns = Math.max(1, Math.ceil(Math.sqrt(fileCount)));
        const fileRows = Math.max(1, Math.ceil(fileCount / fileColumns));
        return {
            fileColumns,
            fileRows,
            width: Math.max(80, fileColumns * 24 + 34),
            depth: Math.max(80, fileRows * 24 + 34),
        };
    });
    const cellSize = Math.max(190, ...moduleLayouts.map((layout) => Math.max(layout.width, layout.depth) + 70));
    const bounds = { minX: Infinity, maxX: -Infinity, minZ: Infinity, maxZ: -Infinity, maxY: 0 };

    data.modules.forEach((module, moduleIndex) => {
        const moduleFiles = data.files.filter((file) => file.module === module.name);
        if (!moduleFiles.length) return;
        const moduleColumn = moduleIndex % columns;
        const moduleRow = Math.floor(moduleIndex / columns);
        const baseX = (moduleColumn - (columns - 1) / 2) * cellSize;
        const baseZ = (moduleRow - (moduleRows - 1) / 2) * cellSize;
        const layout = moduleLayouts[moduleIndex];
        const moduleColumns = layout.fileColumns;
        const plateWidth = layout.width;
        const plateDepth = layout.depth;
        const plate = new THREE.Mesh(
            new THREE.BoxGeometry(plateWidth, 5, plateDepth),
            new THREE.MeshStandardMaterial({ color: colorForModule(moduleIndex), transparent: true, opacity: 0.16, roughness: 0.9 }),
        );
        const districtGroup = { plate, label: null, objects: [], visible: true };
        districtObjects.set(module.name, districtGroup);
        plate.position.set(baseX, -3, baseZ);
        root.add(plate);
        bounds.minX = Math.min(bounds.minX, baseX - plateWidth / 2);
        bounds.maxX = Math.max(bounds.maxX, baseX + plateWidth / 2);
        bounds.minZ = Math.min(bounds.minZ, baseZ - plateDepth / 2);
        bounds.maxZ = Math.max(bounds.maxZ, baseZ + plateDepth / 2);

        const label = makeLabel(module.name.toUpperCase(), '#49637c');
        if (label) {
            label.position.set(baseX, 14, baseZ - plateDepth / 2 - 8);
            label.scale.multiplyScalar(Math.max(1, mapLabelScale(data.modules.length)));
            root.add(label);
            districtGroup.label = label;
        }

        moduleFiles.forEach((file, fileIndex) => {
            const column = fileIndex % moduleColumns;
            const row = Math.floor(fileIndex / moduleColumns);
            const x = baseX + (column - (moduleColumns - 1) / 2) * 24;
            const z = baseZ + (row - (moduleColumns - 1) / 2) * 24;
            const buildingHeight = Math.max(8, Math.min(file.isHotspot ? 155 : 115, Math.log1p(file.loc) * (file.isHotspot ? 18 : 14)));
            const buildingWidth = Math.max(file.isHotspot ? 15 : 10, Math.min(file.isHotspot ? 25 : 18, (10 + file.functions * 0.25 + file.fanOut * 0.5) * (file.isHotspot ? 1.3 : 1)));
            const buildingDepth = Math.max(file.isHotspot ? 15 : 10, Math.min(file.isHotspot ? 25 : 18, (10 + file.fanIn * 0.45 + file.loc / 500) * (file.isHotspot ? 1.3 : 1)));
            bounds.maxY = Math.max(bounds.maxY, buildingHeight);
            const isHotspot = file.isHotspot;
            const bodyMaterial = new THREE.MeshStandardMaterial({
                color: colorForModule(moduleIndex),
                roughness: 0.68,
                metalness: 0.04,
                emissive: file.entry ? 0x214f61 : 0x000000,
                emissiveIntensity: file.entry ? 0.7 : 0,
            });
            const roofMaterial = new THREE.MeshStandardMaterial({
                color: isHotspot ? 0xff9f43 : colorForModule(moduleIndex),
                roughness: 0.6,
                metalness: 0.04,
                emissive: file.entry ? 0x214f61 : 0x000000,
                emissiveIntensity: file.entry ? 0.7 : 0,
            });
            const building = new THREE.Mesh(
                new THREE.BoxGeometry(buildingWidth, buildingHeight, buildingDepth),
                [bodyMaterial, bodyMaterial, roofMaterial, bodyMaterial, bodyMaterial, bodyMaterial],
            );
            building.position.set(x, buildingHeight / 2, z);
            building.userData.file = file;
            building.castShadow = true;
            root.add(building);
            districtGroup.objects.push(building);
            positions.set(file.id, { x, y: buildingHeight + 2, z });

            if (file.entry) {
                const beacon = new THREE.Mesh(
                    new THREE.CylinderGeometry(2.6, 2.6, 3, 12),
                    new THREE.MeshStandardMaterial({ color: 0x78e0e8, emissive: 0x78e0e8, emissiveIntensity: 0.8 }),
                );
                beacon.position.set(x, buildingHeight + 3, z);
                root.add(beacon);
                districtGroup.objects.push(beacon);
            }
        });
    });

    const centerX = (bounds.minX + bounds.maxX) / 2 || 0;
    const centerZ = (bounds.minZ + bounds.maxZ) / 2 || 0;
    const mapSpan = Math.max(bounds.maxX - bounds.minX, bounds.maxZ - bounds.minZ, 100);
    const groundSize = Math.max(mapSpan * 3.2, 720);
    const ground = new THREE.Mesh(
        new THREE.PlaneGeometry(groundSize, groundSize),
        new THREE.MeshStandardMaterial({ color: 0xf8f7f4, roughness: 1, metalness: 0 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -7;
    ground.position.x = centerX;
    ground.position.z = centerZ;
    ground.receiveShadow = true;
    root.add(ground);

    const grid = new THREE.GridHelper(Math.max(mapSpan * 2.8, 640), 48, 0xc8d0d8, 0xe1e5e8);
    grid.position.y = -6.8;
    grid.position.x = centerX;
    grid.position.z = centerZ;
    root.add(grid);

    const edgeMaterial = new THREE.MeshBasicMaterial({ color: 0x7892ad, transparent: true, opacity: 0.2 });
    const connectionObjects = [];
    const visibleEdges = data.edges
        .sort((a, b) => b.weight - a.weight)
        .slice(0, 120);
    visibleEdges.forEach((edge) => {
        const from = positions.get(edge.from.id);
        const to = positions.get(edge.to.id);
        if (!from || !to) return;
        const start = new THREE.Vector3(from.x, from.y, from.z);
        const end = new THREE.Vector3(to.x, to.y, to.z);
        const distance = start.distanceTo(end);
        const control = new THREE.Vector3(
            (start.x + end.x) / 2,
            Math.max(start.y, end.y) + 28 + Math.min(42, distance * 0.12),
            (start.z + end.z) / 2,
        );
        const curve = new THREE.QuadraticBezierCurve3(start, control, end);
        const geometry = new THREE.TubeGeometry(curve, 24, 0.65, 6, false);
        const connection = new THREE.Mesh(geometry, edgeMaterial.clone());
        connection.userData.edge = edge;
        connection.visible = Boolean(edge.from.isHotspot || edge.to.isHotspot);
        connectionObjects.push(connection);
        root.add(connection);
    });

    const camera = new THREE.OrthographicCamera(-width / 2, width / 2, height / 2, -height / 2, 0.1, mapSpan * 8 + 1000);
    camera.position.set(centerX + mapSpan * 0.9, bounds.maxY + mapSpan * 0.82, centerZ + mapSpan * 0.9);
    camera.lookAt(centerX, 0, centerZ);
    camera.zoom = (Math.min(width, height) / (mapSpan * 1.3)) * 1.12;
    camera.updateProjectionMatrix();
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enableRotate = false;
    controls.enablePan = true;
    controls.screenSpacePanning = true;
    controls.mouseButtons.LEFT = THREE.MOUSE.PAN;
    controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
    controls.minZoom = 0.45;
    controls.maxZoom = 4;
    controls.target.set(centerX, 0, centerZ);
    controls.update();

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const buildings = root.children.filter((object) => object.userData.file);
    let hovered = null;
    let selectedBuilding = null;

    function showConnectionsFor(file) {
        connectionObjects.forEach((connection) => {
            const edge = connection.userData.edge;
            connection.visible = Boolean(
                edge.from.isHotspot || edge.to.isHotspot ||
                (file && (edge.from.id === file.id || edge.to.id === file.id)),
            );
        });
    }

    function toggleDistrict(moduleName) {
        const district = districtObjects.get(moduleName);
        if (!district) return false;
        district.visible = !district.visible;
        const opacity = district.visible ? 1 : 0.16;
        const setOpacity = (object) => {
            const materials = Array.isArray(object.material) ? object.material : [object.material];
            materials.forEach((material) => {
                material.transparent = true;
                material.opacity = opacity;
                material.needsUpdate = true;
            });
        };
        setOpacity(district.plate);
        district.objects.forEach(setOpacity);
        if (district.label?.material) district.label.material.opacity = district.visible ? 1 : 0.16;
        return district.visible;
    }

    function setBuildingEmphasis(building, selected) {
        if (!building) return;
        const materials = Array.isArray(building.material) ? building.material : [building.material];
        materials.forEach((material, index) => {
            material.emissive.setHex(selected ? 0xffffff : building.userData.file.entry ? 0x214f61 : 0x000000);
            material.emissiveIntensity = selected ? 0.35 : building.userData.file.entry ? 0.7 : 0;
            if (!selected && index === 2) material.color.setHex(building.userData.file.isHotspot ? 0xff9f43 : colorForModule(building.userData.file.moduleIndex));
        });
    }

    function pick(event) {
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);
        return raycaster.intersectObjects(buildings, false)[0]?.object?.userData.file || null;
    }

    function pickConnection(event) {
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);
        return raycaster.intersectObjects(connectionObjects, false)[0]?.object?.userData.edge || null;
    }

    function pointerMove(event) {
        const file = pick(event);
        const edge = file ? null : pickConnection(event);
        const building = raycaster.intersectObjects(buildings, false)[0]?.object || null;
        if (hovered && hovered !== file) setBuildingEmphasis(hovered.__mesh, false);
        if (building) setBuildingEmphasis(building, true);
        hovered = file;
        if (file) file.__mesh = building;
        renderer.domElement.style.cursor = file || edge ? 'pointer' : 'default';
        onHover(file, event);
        onEdgeHover(edge, event);
    }

    function pointerDown(event) {
        const file = pick(event);
        const hit = raycaster.intersectObjects(buildings, false)[0]?.object || null;
        if (selectedBuilding && selectedBuilding !== hit) setBuildingEmphasis(selectedBuilding, false);
        selectedBuilding = hit;
        setBuildingEmphasis(selectedBuilding, true);
        showConnectionsFor(file);
    }

    renderer.domElement.addEventListener('pointermove', pointerMove);
    renderer.domElement.addEventListener('pointerdown', pointerDown);
    renderer.domElement.addEventListener('pointerleave', () => {
        if (hovered?.__mesh && hovered.__mesh !== selectedBuilding) setBuildingEmphasis(hovered.__mesh, false);
        hovered = null;
        onHover(null);
        onEdgeHover(null);
    });

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

    return {
        toggleDistrict,
        dispose() {
            cancelAnimationFrame(frame);
            resizeObserver.disconnect();
            renderer.domElement.removeEventListener('pointermove', pointerMove);
            renderer.domElement.removeEventListener('pointerdown', pointerDown);
            controls.dispose();
            root.traverse((object) => {
                if (!(object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Sprite)) return;
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

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character]));
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
    const call = edge.call;
    const source = call?.from?.split('::').pop() || edge.from.name;
    const target = call?.to?.split('::').pop() || edge.to.name;
    mapTooltip.innerHTML = `<strong>${escapeHtml(source)} → ${escapeHtml(target)}</strong><span>${escapeHtml(edge.from.path)} → ${escapeHtml(edge.to.path)}</span><span>${edge.weight} dependency signal${edge.weight === 1 ? '' : 's'}</span>`;
    const rect = mapCanvas.getBoundingClientRect();
    mapTooltip.style.left = `${event.clientX - rect.left + 14}px`;
    mapTooltip.style.top = `${event.clientY - rect.top + 14}px`;
    mapTooltip.classList.remove('hidden');
}

function renderSidebar(data) {
    const report = data.report;
    const hotspotCount = report.hotspots?.files?.length || data.files.filter((file) => file.isHotspot).length;
    const entryCount = data.files.filter((file) => file.entry).length;
    const topModules = [...data.modules].sort((a, b) => b.files.length - a.files.length);
    mapSidebar.innerHTML = `
        <section class="guide-section">
            <p class="sidebar-title">Reading the map <span>⌄</span></p>
            <div class="guide-item"><b class="guide-icon height-icon">▂▅▇</b><span><strong>Height</strong><small>Lines of code, on a log scale.</small></span></div>
            <div class="guide-item"><b class="guide-icon colour-icon">▰</b><span><strong>Colour</strong><small>The top-level directory a file lives in.</small></span></div>
            <div class="guide-item"><b class="guide-icon plate-icon">▱</b><span><strong>Plate</strong><small>One district, sized to the files it holds.</small></span></div>
            <div class="guide-item"><b class="guide-icon arc-icon">⌁</b><span><strong>Arcs</strong><small>Dependencies connected to hotspot files.</small></span></div>
        </section>
        <section class="guide-section landmarks">
            <p class="sidebar-title">Landmarks</p>
            <div class="landmark-row"><b class="diamond hotspot-diamond"></b><span><strong>Hotspot <em>${hotspotCount}</em></strong><small>Unusually large or complex files.</small></span></div>
            <div class="landmark-row"><b class="diamond entry-diamond"></b><span><strong>Entry point <em>${entryCount}</em></strong><small>Likely places where execution starts.</small></span></div>
        </section>
        <section class="guide-section districts-section">
            <p class="sidebar-title">Districts <em>${data.modules.length}</em></p>
            ${topModules.slice(0, 12).map((module, index) => `<button class="district-row" type="button" data-module="${escapeHtml(module.name)}"><i style="background:#${colorForModule(index).toString(16).padStart(6, '0')}"></i><code>${escapeHtml(module.name)}</code><span>${module.files.length}</span></button>`).join('')}
        </section>
    `;
}

function renderStats(data) {
    const totalLoc = data.files.reduce((sum, file) => sum + file.loc, 0);
    mapStats.innerHTML = `<span>Files <b>${metric(data.files.length)}</b></span><span>Lines <b>${metric(totalLoc)}</b></span><span>Districts <b>${metric(data.modules.length)}</b></span><span>Hotspot links <b>${metric(data.hotspotEdges.length)}</b></span><span>Median file <b>${metric(median(data.files.map((file) => file.loc)))} lines</b></span><span class="language-strip">${(data.overview.languages || []).map((language, index) => `<i style="background:#${colorForModule(index).toString(16).padStart(6, '0')}"></i>${escapeHtml(language)}`).join(' ')}</span>`;
}

function median(values) {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : Math.round((sorted[middle - 1] + sorted[middle]) / 2);
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
        const overview = result.overview || {};
        analysisTitle.textContent = url.replace(/^https?:\/\/(www\.)?github\.com\//i, '').replace(/\/$/, '');
        landing.classList.add('hidden');
        analysisView.classList.remove('hidden');
        document.body.classList.add('analysis-active');
        showMessage('');
        const normalized = normalizeReport(result);
        renderSidebar(normalized);
        renderStats(normalized);
        activeMap?.dispose();
        activeMap = createMap(result, renderTooltip, renderEdgeTooltip);
        mapSidebar.querySelectorAll('[data-module]').forEach((row) => {
            row.addEventListener('click', () => {
                const visible = activeMap.toggleDistrict(row.dataset.module);
                row.classList.toggle('district-muted', !visible);
            });
        });
        analysisTitle.title = `${metric(overview.file_count)} files · ${metric(overview.function_count)} functions`;
    } catch (error) {
        showMessage(error.message || 'Analysis failed.');
    } finally {
        setLoading(false);
    }
}

analyzeButton.addEventListener('click', analyzeRepository);
repositoryInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') analyzeRepository();
});
newAnalysisButton.addEventListener('click', () => {
    activeMap?.dispose();
    activeMap = null;
    analysisView.classList.add('hidden');
    landing.classList.remove('hidden');
    document.body.classList.remove('analysis-active');
    repositoryInput.focus();
});
