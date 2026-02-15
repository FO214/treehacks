//
//  ImmersiveView.swift
//  treehacks26
//

import SwiftUI
import RealityKit
import ARKit
import RealityKitContent
import UIKit

/// Agent state machine: thinking → working → testing.
/// Handles out-of-order messages: if a later-state message arrives before earlier ones,
/// the character is spawned directly in that state.
/// - thinking: Character spawned with thinking indicator, awaiting start_working
/// - working: No thinking indicator, awaiting agent_start_testing
/// - testing: Webview shown, character jumped up, persists until user closes
enum AgentState: String {
    case thinking
    case working
    case testing
}

/// Holds the root anchor entity (invisible), static desks, spawning characters, plane anchor, whiteboard, and cached templates.
@Observable
final class DemoBlockState {
    /// Invisible root entity anchored to surface; children are positioned relative to this.
    var rootEntity: Entity?
    /// Character entities by slot (1-9); desks are static.
    var characterEntities: [Int: Entity] = [:]
    /// Agent state per slot (1-9).
    var agentStates: [Int: AgentState] = [:]
    /// URL for webview above agent when in testing (agent_id -> vercel link).
    var testingWebviewURLs: [Int: String] = [:]
    /// Cached webview attachment entities (populated in make closure).
    var webviewEntities: [Int: Entity] = [:]
    var planeAnchor: AnchorEntity?
    var whiteboardEntity: Entity?
    /// Palm tree in corner of floor (for jump_ping animation).
    var palmTreeEntity: Entity?
    /// True while palm tree is mid-jump; ignores new jump_ping until done.
    var isPalmTreeJumping = false
    /// Cached charc.usdc; cloned when spawning.
    var characterTemplate: Entity?
    /// Cached thinking.usdz; shown above head when in thinking mode.
    var thinkingTemplate: Entity?
    /// Cached computerSpawn_2.usdz; used for static desks.
    var computerDeskTemplate: Entity?
    /// Thinking indicator entities per agent (child of character); shaken in update loop.
    var thinkingIndicatorEntities: [Int: Entity] = [:]
    /// When true, root follows gaze (where user is looking) instead of hand.
    var isRepositioningMode = false
    /// True after we've placed root near user; avoids spawn at plane anchor center (often far away).
    var hasInitialPlacement = false
    /// Previous palm state for repositioning (snap only on open transition).
    var wasPalmOpenForReposition = false
    /// Debug: last WebSocket message received (shown on-screen).
    var lastWsMessage: String = ""
    /// Debug: WebSocket connection status.
    var wsConnected: Bool = false

    /// User closed the webview for this agent; hide webview and remove character.
    func closeWebview(agentId: Int) {
        testingWebviewURLs.removeValue(forKey: agentId)
        webviewEntities[agentId]?.removeFromParent()
        thinkingIndicatorEntities[agentId]?.removeFromParent()
        thinkingIndicatorEntities.removeValue(forKey: agentId)
        characterEntities[agentId]?.removeFromParent()
        characterEntities.removeValue(forKey: agentId)
        agentStates.removeValue(forKey: agentId)
    }
}

struct ImmersiveView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismissImmersiveSpace) private var dismissImmersiveSpace
    @State private var blockState = DemoBlockState()
    @State private var handTrackingManager = HandTrackingManager()
    @State private var setupTask: Task<Void, Never>?
    @State private var spawnWebSocketTask: Task<Void, Never>?
    @State private var updateSubscription: EventSubscription?
    @State private var spawnWebSocket: URLSessionWebSocketTask?

    private static let scaleFactor: Float = 12
    private static let maxAgents = 9
    private static let gridCols = 3
    /// Target bounding box size for grid objects (desks/robots).
    private static let targetBoundsSize: Float = 0.06 * scaleFactor
    /// Larger size for desk/table models (Office_Props_Pack).
    private static let deskTargetSize: Float = 0.15 * scaleFactor
    /// Character scale multiplier (characters need to be much larger to be visible).
    private static let characterScaleMultiplier: Float = 3
    /// Character size reduction (0.7 = 30% smaller).
    private static let characterSizeReduction: Float = 0.7
    /// Extra 2x scale for desks and characters only (not spacing).
    private static let deskAndCharacterSizeMultiplier: Float = 2
    private static let gridSpacing: Float = 0.12 * scaleFactor + 1

    /// 3×3 grid positions (floor of root), row-major order.
    private static var gridPositions: [SIMD3<Float>] {
        let half = Float(gridCols - 1) * gridSpacing / 2
        var positions: [SIMD3<Float>] = []
        for row in 0..<gridCols {
            for col in 0..<gridCols {
                positions.append([
                    half - Float(col) * gridSpacing,  // horizontal (reversed)
                    targetBoundsSize / 2, // sit on floor
                    Float(row) * gridSpacing - half
                ])
            }
        }
        return positions
    }

    var body: some View {
        ZStack {
            RealityView { content, attachments in
            // Root entity: invisible anchor for children, sits on surface
            let root = Entity()
            root.name = "demoRoot"
            root.position = [0, 0.2 * Self.scaleFactor, 0]

            // See-through floor under the root (horizontal XZ plane)
            let floorMesh = MeshResource.generatePlane(width: 0.5 * Self.scaleFactor, height: 0.5 * Self.scaleFactor)
            var floorMat = SimpleMaterial()
            floorMat.color = .init(tint: UIColor.white.withAlphaComponent(0))
            let floorEntity = ModelEntity(mesh: floorMesh, materials: [floorMat])
            floorEntity.name = "floor"
            floorEntity.orientation = simd_quatf(angle: -.pi / 2, axis: [1, 0, 0])  // horizontal
            floorEntity.position = [0, 0, 0]
            root.addChild(floorEntity)

            // Children are spawned when FastAPI sends spawn_agent via WebSocket

            // Plane anchor: snaps to ground (floor) only
            let anchor = AnchorEntity(.plane(.horizontal, classification: .floor, minimumBounds: [0.4 * Self.scaleFactor, 0.4 * Self.scaleFactor]))
            anchor.addChild(root)
            content.add(anchor)

            // Whiteboard: 1.5m closer than before (was 1.2m, now 0.3m in front)
            Task { @MainActor in
                if let whiteboard = try? await Entity(named: "fixed_whiteboard.usdc", in: realityKitContentBundle) {
                    whiteboard.name = "whiteboard"
                    whiteboard.position = [0, 0.5 * Self.scaleFactor - 2, -0.3 * Self.scaleFactor]  // 2m lower, in front of origin
                    anchor.addChild(whiteboard)
                    Self.scaleToBoundsSize(whiteboard, targetSize: Self.targetBoundsSize * 15 / 2)  // 2x size (was 15/4)
                    blockState.whiteboardEntity = whiteboard

                    // Diagram from project root (diagram.svg → diagram.png), snapped to front of whiteboard
                    let loadDiagram = true
                    if loadDiagram {
                        do {
                            let texture: TextureResource?
                            if let url = Bundle.main.url(forResource: "diagram", withExtension: "png") {
                                texture = try await TextureResource.load(contentsOf: url)
                            } else {
                                texture = try? await TextureResource.load(named: "diagram", in: .main)
                            }
                            if let texture, let diagramPlane = Self.makeDiagramPlane(texture: texture) {
                                diagramPlane.name = "diagram"
                                diagramPlane.position = [0, 0, 0.02 * Self.scaleFactor]  // Slightly in front of whiteboard face
                                whiteboard.addChild(diagramPlane)
                            }
                        } catch {
                            print("[ImmersiveView] Diagram texture load failed: \(error)")
                        }
                    }
                }
            }

            blockState.rootEntity = root
            blockState.characterEntities = [:]
            blockState.planeAnchor = anchor

            // Cache webview attachment entities for testing mode
            for i in 1...Self.maxAgents {
                if let entity = attachments.entity(for: "webview_\(i)") {
                    blockState.webviewEntities[i] = entity
                }
            }

            // Load templates and create 9 static desks (computer on desk)
            Task { @MainActor in
                if let character = try? await Entity(named: "charc.usdc", in: realityKitContentBundle) {
                    blockState.characterTemplate = character
                }
                if let thinking = try? await Entity(named: "thinking.usdz", in: realityKitContentBundle) {
                    blockState.thinkingTemplate = thinking
                }
                if let computer = try? await Entity(named: "computerSpawn_2.usdz", in: realityKitContentBundle),
                   let root = blockState.rootEntity {
                    // Create 9 static desks at grid positions (never removed)
                    for i in 0..<Self.maxAgents {
                        let desk = computer.clone(recursive: true)
                        desk.name = "desk_\(i)"
                        desk.orientation = simd_quatf(angle: .pi / 2, axis: [0, 1, 0])  // 90° counter clockwise
                        let gridPos = Self.gridPositions[i]
                        desk.position = [gridPos.x, Self.targetBoundsSize / 2 + 1.2 - 0.5, gridPos.z]  // lowered 50cm
                        root.addChild(desk)
                        Self.scaleToBoundsSize(desk, targetSize: Self.targetBoundsSize * Self.deskAndCharacterSizeMultiplier)
                    }

                    // Palm tree: 2m further from grid center than first desk
                    let gridPos0 = Self.gridPositions[0]
                    let epicenterOffset: Float = 2.0
                    let xz = SIMD2<Float>(gridPos0.x, gridPos0.z)
                    let dist = simd_length(xz)
                    let palmXZ: SIMD2<Float> = dist > 0.001
                        ? xz + epicenterOffset * (xz / dist)
                        : xz + [epicenterOffset, 0]  // fallback if at center
                    let deskTargetSize = Self.targetBoundsSize * Self.deskAndCharacterSizeMultiplier
                    let palmTree: Entity
                    if let model = try? await Entity(named: "palmtreelowpolygon.usdz", in: realityKitContentBundle) {
                        palmTree = model.clone(recursive: true)
                        Self.scaleToBoundsSize(palmTree, targetSize: deskTargetSize)
                    } else {
                        palmTree = Self.makePalmTreePlaceholder()
                        Self.scaleToBoundsSize(palmTree, targetSize: deskTargetSize)
                    }
                    palmTree.name = "palm_tree"
                    // Floor is at y=0; put base on floor (center at half-height for origin-at-center models)
                    let palmHalfHeight = deskTargetSize / 2
                    palmTree.position = [palmXZ.x, palmHalfHeight, palmXZ.y]
                    // Touch detection: CollisionComponent + InputTargetComponent
                    let collisionShape = ShapeResource.generateBox(size: [deskTargetSize, deskTargetSize, deskTargetSize])
                    palmTree.components.set([
                        CollisionComponent(shapes: [collisionShape]),
                        InputTargetComponent(),
                    ])
                    root.addChild(palmTree)
                    blockState.palmTreeEntity = palmTree
                }
            }

            // Place root near user on surface in front
            // SceneEvents.Update may run off main thread; HandTrackingManager is @MainActor
            updateSubscription = content.subscribe(to: SceneEvents.Update.self) { _ in
                Task { @MainActor in
                    // Shake thinking indicators
                    let t = Float(ProcessInfo.processInfo.systemUptime)
                    for (_, entity) in blockState.thinkingIndicatorEntities {
                        let shakeX = sin(t * 12) * 0.06
                        let shakeZ = sin(t * 10 + 1) * 0.06
                        let rotX = simd_quatf(angle: shakeX, axis: [1, 0, 0])
                        let rotZ = simd_quatf(angle: shakeZ, axis: [0, 0, 1])
                        entity.orientation = rotZ * rotX
                    }

                    guard let planeAnchor = blockState.planeAnchor,
                          let root = blockState.rootEntity else { return }

                    if let deviceAnchor = handTrackingManager.queryDeviceAnchor() {
                        let t = deviceAnchor.originFromAnchorTransform
                        let devicePos = SIMD3<Float>(t.columns.3.x, t.columns.3.y, t.columns.3.z)
                        let forward = SIMD3<Float>(t.columns.2.x, t.columns.2.y, t.columns.2.z)
                        let horizontalForward = simd_normalize(SIMD3<Float>(forward.x, 0, forward.z))

                        if simd_length(horizontalForward) > 0.1 {
                            let distanceInFront: Float = 2.0
                            let pointInFront = devicePos + horizontalForward * distanceInFront
                            let surfaceY = planeAnchor.position(relativeTo: nil).y
                            let hitWorld = SIMD3<Float>(pointInFront.x, surfaceY, pointInFront.z)
                            let localPos = planeAnchor.convert(position: hitWorld, from: nil)
                            let middleChildCenterOffset: Float = Self.targetBoundsSize / 2
                            let snapPosition = SIMD3<Float>(localPos.x, localPos.y - middleChildCenterOffset, localPos.z)

                            if !blockState.hasInitialPlacement {
                                // Initial placement: snap to 2m in front on surface
                                root.position = snapPosition
                                blockState.hasInitialPlacement = true
                            } else if blockState.isRepositioningMode {
                                let palmOpen = handTrackingManager.isPalmCurrentlyOpen()
                                if palmOpen, !blockState.wasPalmOpenForReposition {
                                    // Palm just opened: snap to surface in front
                                    root.position = snapPosition
                                }
                                blockState.wasPalmOpenForReposition = palmOpen
                            }
                        }
                    } else {
                        // Simulator or no tracking
                        if let root = blockState.rootEntity, let planeAnchor = blockState.planeAnchor {
                            root.position = [0, 0, -0.5 * Self.scaleFactor]
                            blockState.hasInitialPlacement = true
                        }
                    }
                }
            }
        } update: { content, attachments in
            // No color updates; models use static usdz appearance
        } attachments: {
            ForEach(1...Self.maxAgents, id: \.self) { agentId in
                Attachment(id: "webview_\(agentId)") {
                    WebViewWithClose(
                        url: URL(string: blockState.testingWebviewURLs[agentId] ?? "") ?? URL(string: "https://www.google.com"),
                        onClose: { blockState.closeWebview(agentId: agentId) }
                    )
                    .frame(width: 2000, height: 1500)
                    .glassBackgroundEffect()
                }
            }
        }
        .gesture(
            TapGesture()
                .targetedToAnyEntity()
                .onEnded { value in
                    if value.entity.name == "palm_tree" {
                        Task { @MainActor in
                            await handleJumpPing()
                            postPalmTouched()
                        }
                    }
                }
        )

            // Overlay: show when root is searching for a surface to latch to
            if !blockState.hasInitialPlacement {
                VStack {
                    HStack(spacing: 8) {
                        ProgressView()
                            .scaleEffect(0.9)
                        Text("Finding surface…")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                    .glassBackgroundEffect(in: .rect(cornerRadius: 16))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .allowsHitTesting(false)
            }

            // Debug overlay: WebSocket status (bottom-left)
            VStack(alignment: .leading, spacing: 4) {
                Text(blockState.wsConnected ? "WS: connected" : "WS: disconnected")
                    .font(.caption)
                    .foregroundStyle(blockState.wsConnected ? .green : .orange)
                if !blockState.lastWsMessage.isEmpty {
                    Text(blockState.lastWsMessage)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
            }
            .padding(12)
            .glassBackgroundEffect(in: .rect(cornerRadius: 12))
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
            .allowsHitTesting(false)
        }
        .onChange(of: appModel.repositioningMode) { _, newValue in
            blockState.isRepositioningMode = newValue
            handTrackingManager.isRepositioningMode = newValue
            blockState.wasPalmOpenForReposition = false
        }
        .onAppear {
            blockState.isRepositioningMode = appModel.repositioningMode
            handTrackingManager.isRepositioningMode = appModel.repositioningMode
            startSpawnWebSocket()
            // Defer hand tracking so the box renders first (ARKit session can delay initial render)
            // Skip on simulator: hand tracking is not supported and produces "not authorized" errors
            #if !targetEnvironment(simulator)
            setupTask = Task {
                try? await Task.sleep(for: .seconds(2.0))
                guard !Task.isCancelled else { return }
                setupHandTracking()
            }
            #endif
        }
        .onDisappear {
            updateSubscription?.cancel()
            updateSubscription = nil
            spawnWebSocket?.cancel(with: .goingAway, reason: nil)
            spawnWebSocket = nil
            spawnWebSocketTask?.cancel()
            spawnWebSocketTask = nil
            setupTask?.cancel()
            setupTask = nil
            handTrackingManager.stopTracking()
            handTrackingManager.onOpenPalmDetected = nil
            handTrackingManager.onOpenPalmForDrag = nil
            blockState.rootEntity = nil
            blockState.characterEntities = [:]
            blockState.agentStates = [:]
            blockState.thinkingIndicatorEntities = [:]
            blockState.testingWebviewURLs = [:]
            blockState.webviewEntities = [:]
            blockState.planeAnchor = nil
            blockState.whiteboardEntity = nil
            blockState.palmTreeEntity = nil
            blockState.isPalmTreeJumping = false
            blockState.characterTemplate = nil
            blockState.thinkingTemplate = nil
            blockState.computerDeskTemplate = nil
            blockState.hasInitialPlacement = false
            blockState.wasPalmOpenForReposition = false
            blockState.wsConnected = false
            blockState.lastWsMessage = ""
        }
    }

    /// Creates a plane with diagram texture for the whiteboard front (aspect ~3.22:1 from diagram.svg).
    private static func makeDiagramPlane(texture: TextureResource) -> ModelEntity? {
        let width: Float = 0.8 * Self.scaleFactor
        let height: Float = 0.25 * Self.scaleFactor  // ~3.22:1 aspect
        let mesh = MeshResource.generatePlane(width: width, height: height)
        var mat = SimpleMaterial()
        mat.color = .init(tint: .white, texture: .init(texture))
        return ModelEntity(mesh: mesh, materials: [mat])
    }

    /// Placeholder desk when usdz load fails (visible brown box).
    private static func makePlaceholderDesk() -> Entity {
        let mesh = MeshResource.generateBox(width: 0.06 * Self.scaleFactor, height: 0.06 * Self.scaleFactor, depth: 0.06 * Self.scaleFactor)
        let mat = SimpleMaterial(color: .systemBrown, isMetallic: false)
        return ModelEntity(mesh: mesh, materials: [mat])
    }

    /// Placeholder palm tree (green cylinder) when palm model is not available.
    private static func makePalmTreePlaceholder() -> Entity {
        let mesh = MeshResource.generateCylinder(height: 1.0, radius: 0.1)
        let mat = SimpleMaterial(color: .systemGreen, isMetallic: false)
        return ModelEntity(mesh: mesh, materials: [mat])
    }

    /// Placeholder thinking indicator (yellow sphere) when thinking.usdz is not available.
    private static func makeThinkingPlaceholder() -> Entity {
        let size: Float = 0.08 * Self.scaleFactor
        let mesh = MeshResource.generateSphere(radius: size / 2)
        let mat = SimpleMaterial(color: .systemYellow, isMetallic: false)
        return ModelEntity(mesh: mesh, materials: [mat])
    }

    /// Scales an entity so its visual bounding box fits within a cube of the given size.
    /// Falls back to 0.01 if bounds are empty or would produce invisible scale.
    private static func scaleToBoundsSize(_ entity: Entity, targetSize: Float) {
        let bounds = entity.visualBounds(relativeTo: entity)
        let extents = bounds.extents
        let maxExtent = max(extents.x, extents.y, extents.z)
        if maxExtent > 0 {
            let scaleFactor = targetSize / maxExtent
            // Clamp to avoid invisible (too small) or huge models
            let clamped = min(max(scaleFactor, 0.001), 100)
            entity.scale = [clamped, clamped, clamped]
        } else {
            entity.scale = [0.01, 0.01, 0.01]  // fallback for empty bounds
        }
    }

    private func startSpawnWebSocket() {
        guard let url = APIConfig.wsSpawnURL else {
            blockState.lastWsMessage = "Invalid WebSocket URL"
            return
        }
        spawnWebSocketTask = Task { @MainActor in
            blockState.lastWsMessage = "Connecting…"
            // Brief delay so RealityView has time to create root and load assets
            try? await Task.sleep(for: .seconds(1.5))
            guard !Task.isCancelled else { return }

            let wsTask = URLSession.shared.webSocketTask(with: url)
            spawnWebSocket = wsTask
            wsTask.resume()
            blockState.wsConnected = true
            blockState.lastWsMessage = "Connected to \(url.absoluteString)"

            while !Task.isCancelled {
                do {
                    let message = try await wsTask.receive()
                    switch message {
                    case .string(let text):
                        let preview = String(text.prefix(80)) + (text.count > 80 ? "…" : "")
                        blockState.lastWsMessage = preview
                        if let data = text.data(using: .utf8),
                           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                           let type = json["type"] as? String {
                            if let agentId = json["agent_id"] as? Int, (1...9).contains(agentId) {
                                switch type {
                                case "create_agent_thinking":
                                    await handleCreateAgentThinking(agentId: agentId, taskName: json["task_name"] as? String ?? "")
                                case "agent_start_working":
                                    await handleAgentStartWorking(agentId: agentId)
                                case "agent_start_testing":
                                    let vercel = json["vercel_link"] as? String ?? ""
                                    let browserbase = json["browserbase_link"] as? String ?? ""
                                    await handleAgentStartTesting(agentId: agentId, vercelLink: vercel, browserbaseLink: browserbase)
                                default:
                                    break
                                }
                            }
                        }
                    case .data:
                        break
                    @unknown default:
                        break
                    }
                } catch {
                    if !Task.isCancelled {
                        blockState.lastWsMessage = "Error: \(error.localizedDescription)"
                    }
                    break
                }
            }
            blockState.wsConnected = false
        }
    }

    private func handleCreateAgentThinking(agentId: Int, taskName: String) async {
        await MainActor.run {
            spawnOrResetCharacter(agentId: agentId, targetState: .thinking)
        }
    }

    private func postPalmTouched() {
        guard let url = URL(string: "\(APIConfig.baseURL)/palm-touched") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = "{\"type\":\"jump_ping\"}".data(using: .utf8)
        URLSession.shared.dataTask(with: request) { _, _, _ in }.resume()
    }

    private func handleJumpPing() async {
        await MainActor.run {
            guard !blockState.isPalmTreeJumping else { return }  // Ignore if already jumping
            guard let palmTree = blockState.palmTreeEntity, let parent = palmTree.parent else { return }
            blockState.isPalmTreeJumping = true

            let jumpHeight: Float = 0.5
            let duration: TimeInterval = 0.25

            var upTransform = palmTree.transform
            upTransform.translation.y += jumpHeight
            palmTree.move(to: upTransform, relativeTo: parent, duration: duration, timingFunction: .easeOut)

            Task { @MainActor in
                try? await Task.sleep(for: .seconds(duration))
                var downTransform = palmTree.transform
                downTransform.translation.y -= jumpHeight
                palmTree.move(to: downTransform, relativeTo: parent, duration: duration, timingFunction: .easeIn)
                try? await Task.sleep(for: .seconds(duration))
                blockState.isPalmTreeJumping = false  // Ready for next jump
            }
        }
    }

    private func handleAgentStartWorking(agentId: Int) async {
        await MainActor.run {
            if let character = blockState.characterEntities[agentId] {
                // Character exists: transition thinking → working (remove thinking indicator)
                if blockState.agentStates[agentId] == .thinking {
                    blockState.thinkingIndicatorEntities[agentId]?.removeFromParent()
                    blockState.thinkingIndicatorEntities.removeValue(forKey: agentId)
                    blockState.agentStates[agentId] = .working
                }
                // Already working or testing: no-op
            } else {
                // No character: spawn directly in working state (e.g. missed create_agent_thinking)
                spawnOrResetCharacter(agentId: agentId, targetState: .working)
            }
        }
    }

    private func handleAgentStartTesting(agentId: Int, vercelLink: String, browserbaseLink: String) async {
        await MainActor.run {
            guard blockState.agentStates[agentId] == .working,
                  let character = blockState.characterEntities[agentId] else { return }
            blockState.agentStates[agentId] = .testing

            // Show webview: prefer Browserbase replay, else Vercel preview, else placeholder
            let url = !browserbaseLink.isEmpty ? browserbaseLink : (!vercelLink.isEmpty ? vercelLink : "https://google.com")
            blockState.testingWebviewURLs[agentId] = url
            if let webviewEntity = blockState.webviewEntities[agentId] {
                webviewEntity.removeFromParent()
                webviewEntity.position = [0, 1.0, 1.0]  // 1m above character, 1m forward (Z)
                character.addChild(webviewEntity)
            }
        }
    }

    /// Spawns or resets a character in the given state. Handles out-of-order messages.
    private func spawnOrResetCharacter(agentId: Int, targetState: AgentState, vercelLink: String = "") {
        guard let root = blockState.rootEntity else { return }

        // Full reset of slot (idempotent)
        blockState.testingWebviewURLs.removeValue(forKey: agentId)
        blockState.webviewEntities[agentId]?.removeFromParent()
        blockState.thinkingIndicatorEntities[agentId]?.removeFromParent()
        blockState.thinkingIndicatorEntities.removeValue(forKey: agentId)
        blockState.agentStates.removeValue(forKey: agentId)
        if let existing = blockState.characterEntities[agentId] {
            existing.removeFromParent()
            blockState.characterEntities.removeValue(forKey: agentId)
        }

        let gridIndex = agentId - 1
        let gridPos = Self.gridPositions[gridIndex]
        let targetY = Self.targetBoundsSize / 2 + 1.2 - 0.5

        // Container: no rotation; handles position and jump. Webview/thinking indicator stay world-aligned.
        let container = Entity()
        container.name = "character_\(agentId)"
        container.position = [gridPos.x, targetY - 1.0, gridPos.z - 2.5]  // 1.5m closer towards user (was -1.0)
        root.addChild(container)
        blockState.characterEntities[agentId] = container
        blockState.agentStates[agentId] = targetState

        // Char model: rotation applied only to the visual mesh, not to container children
        let charModel: Entity
        if let template = blockState.characterTemplate {
            charModel = template.clone(recursive: true)
            let baseSize = Self.deskTargetSize * Self.characterScaleMultiplier * Self.deskAndCharacterSizeMultiplier
            Self.scaleToBoundsSize(charModel, targetSize: baseSize / 4 * Self.characterSizeReduction)
        } else {
            charModel = Self.makePlaceholderDesk()
        }
        charModel.name = "char_model_\(agentId)"
        charModel.position = [0, 0, 0]
        let rotY = simd_quatf(angle: 90 * .pi / 180, axis: [0, 1, 0])
        let rotZ = simd_quatf(angle: 180 * .pi / 180, axis: [0, 0, 1])
        let rotZ90 = simd_quatf(angle: 90 * .pi / 180, axis: [0, 0, 1])  // 90° CCW on Z
        charModel.orientation = rotY * rotZ * rotZ90
        container.addChild(charModel)

        if targetState == .thinking {
            let thinkingIndicator: Entity
            if let template = blockState.thinkingTemplate {
                thinkingIndicator = template.clone(recursive: true)
                Self.scaleToBoundsSize(thinkingIndicator, targetSize: Self.targetBoundsSize * 0.8)
            } else {
                thinkingIndicator = Self.makeThinkingPlaceholder()
                Self.scaleToBoundsSize(thinkingIndicator, targetSize: Self.targetBoundsSize * 0.8)
            }
            thinkingIndicator.name = "thinking_\(agentId)"
            thinkingIndicator.position = [0, 0.25, 0]
            container.addChild(thinkingIndicator)
            blockState.thinkingIndicatorEntities[agentId] = thinkingIndicator
        }

        if targetState == .testing {
            blockState.testingWebviewURLs[agentId] = vercelLink.isEmpty ? "https://www.google.com" : vercelLink
            applyTestingState(container: container, agentId: agentId)
        }

        var targetTransform = container.transform
        targetTransform.translation = [gridPos.x, targetY, gridPos.z - 2.5]  // 1.5m closer towards user
        container.move(to: targetTransform, relativeTo: root, duration: 0.6, timingFunction: .easeOut)
    }

    /// Attaches webview and jumps container up; used when entering testing state.
    private func applyTestingState(container: Entity, agentId: Int) {
        if let webviewEntity = blockState.webviewEntities[agentId] {
            webviewEntity.removeFromParent()
            webviewEntity.position = [0, 1.0, 1.0]
            container.addChild(webviewEntity)
        }
        var targetTransform = container.transform
        targetTransform.translation.y += 1.0
        container.move(to: targetTransform, relativeTo: container.parent, duration: 0.8, timingFunction: .easeOut)
    }

    private func setupHandTracking() {
        handTrackingManager.onOpenPalmDetected = {
            await triggerRecordOnce()
        }

        // Repositioning is now gaze-based (see SceneEvents.Update subscription)
        handTrackingManager.onOpenPalmForDrag = { _ in }

        Task {
            await handTrackingManager.startTracking()
        }
    }

    private func triggerRecordOnce() async {
        // Call record-once (proxied via FastAPI to voice server)
        guard let url = URL(string: "\(APIConfig.baseURL)/record-once") else {
            print("[HandTracking] Invalid voice server URL")
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = "{}".data(using: .utf8)

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let httpResponse = response as? HTTPURLResponse {
                print("[HandTracking] record-once response: \(httpResponse.statusCode)")
            }
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                print("[HandTracking] record-once result: \(json)")
            }
        } catch {
            print("[HandTracking] record-once failed: \(error)")
        }
    }
}

#Preview(immersionStyle: .mixed) {
    ImmersiveView()
        .environment(AppModel())
}
